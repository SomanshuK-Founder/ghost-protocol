"""Actual offline OpenSSL verification via MemoryBIO; no sockets or provider calls."""

import asyncio
import shutil
import ssl
import subprocess
import traceback
from pathlib import Path

import certifi
import httpx
import pytest

from app.agent.controlled_execution import ControlledExecutionClient
from app.agent.execution_contracts import ExecutionProvenance
from app.agent.http_gateway import AuthenticatedHttpToolGateway, GatewayTransportError
from app.agent.integration_runtime import gateway_runtime
from app.agent.workflow_transport import WorkflowControlClient
from app.llm.config import NebiusSettings
from app.llm.nebius_provider import NebiusModelProvider
from app.tls import TLSConfigurationError, tls_verification
from tests.agent.test_http_gateway import TASK, envelope, request, token
from tests.agent.test_nebius_provider import completion
from tests.agent.test_nebius_provider import request as inference_request


@pytest.fixture(scope="module")
def certificates(tmp_path_factory):
    # Existing Git-for-Windows OpenSSL is a local test tool, not a new dependency.
    executable = shutil.which("openssl")
    if executable is None:
        candidate = Path("C:/Program Files/Git/usr/bin/openssl.exe")
        if candidate.is_file():
            executable = str(candidate)
    assert executable, "Local OpenSSL test tool required; never download it automatically"
    directory = tmp_path_factory.mktemp("synthetic-tls")

    def run(*args):
        result = subprocess.run([executable, *args], cwd=directory, capture_output=True, timeout=15)
        assert result.returncode == 0, "Synthetic certificate generation failed"

    for name in ("root", "other"):
        run(
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "2",
            "-subj",
            f"/CN=Synthetic {name}",
            "-keyout",
            f"{name}.key",
            "-out",
            f"{name}.pem",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
        )
    run(
        "req",
        "-new",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-subj",
        "/CN=localhost",
        "-keyout",
        "leaf.key",
        "-out",
        "leaf.csr",
    )
    (directory / "index").write_text("")
    (directory / "serial").write_text("1000\n")
    (directory / "ca.cnf").write_text(
        "[ca]\ndefault_ca=test\n[test]\n"
        "database=index\nserial=serial\nnew_certs_dir=.\n"
        "certificate=root.pem\nprivate_key=root.key\ndefault_md=sha256\n"
        "default_days=2\npolicy=names\nx509_extensions=server\nunique_subject=no\n"
        "[names]\ncommonName=supplied\n[server]\nbasicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\nsubjectAltName=DNS:localhost\n"
    )
    for name, dates in (
        ("valid", ()),
        ("expired", ("-startdate", "20000101000000Z", "-enddate", "20000102000000Z")),
    ):
        run("ca", "-batch", "-config", "ca.cnf", "-in", "leaf.csr", "-out", f"{name}.pem", *dates)
    return directory


def handshake(context, certificates, *, leaf="valid", hostname="localhost"):
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(certificates / f"{leaf}.pem", certificates / "leaf.key")
    incoming, outgoing = [ssl.MemoryBIO(), ssl.MemoryBIO()], [ssl.MemoryBIO(), ssl.MemoryBIO()]
    peers = [
        context.wrap_bio(incoming[0], outgoing[0], server_hostname=hostname),
        server_context.wrap_bio(incoming[1], outgoing[1], server_side=True),
    ]
    done = [False, False]
    for _ in range(20):
        for i, peer in enumerate(peers):
            if not done[i]:
                try:
                    peer.do_handshake()
                    done[i] = True
                except ssl.SSLWantReadError:
                    pass
            data = outgoing[i].read()
            if data:
                incoming[1 - i].write(data)
        if all(done):
            return
    pytest.fail("Synthetic TLS handshake did not finish")


def test_standard_runtime_preserves_public_roots_and_ignores_environment(monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", "untrusted-model-path")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "untrusted-requests-path")
    assert tls_verification() is True
    assert ssl.create_default_context(cafile=certifi.where()).get_ca_certs()


def test_openshell_ca_handshake_and_public_roots_preserved(certificates, monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", str(certificates / "root.pem"))
    context = tls_verification(openshell=True)
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    public = ssl.create_default_context(cafile=certifi.where()).get_ca_certs(binary_form=True)
    assert set(public) <= set(context.get_ca_certs(binary_form=True))
    handshake(context, certificates)


@pytest.mark.parametrize("failure", ["untrusted", "expired", "hostname"])
def test_actual_certificate_verification_failures(certificates, failure):
    context = tls_verification(
        openshell=True,
        ca_bundle=certificates / ("other.pem" if failure == "untrusted" else "root.pem"),
    )
    with pytest.raises(ssl.SSLCertVerificationError):
        handshake(
            context,
            certificates,
            leaf="expired" if failure == "expired" else "valid",
            hostname="wrong.test" if failure == "hostname" else "localhost",
        )


def test_explicit_bundle_precedes_environment_without_global_mutation(certificates, monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", str(certificates / "other.pem"))
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "invalid")
    monkeypatch.setenv("CURL_CA_BUNDLE", "invalid")
    context = tls_verification(openshell=True, ca_bundle=certificates / "root.pem")
    handshake(context, certificates)
    import os

    assert os.environ["SSL_CERT_FILE"] == str(certificates / "other.pem")


@pytest.mark.parametrize("fallback", ["REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_DIR"])
def test_other_library_settings_cannot_replace_ssl_cert_file(certificates, monkeypatch, fallback):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setenv(fallback, str(certificates / "root.pem"))
    with pytest.raises(TLSConfigurationError):
        tls_verification(openshell=True)


@pytest.mark.parametrize("value", [None, "", "relative.pem", False, 42])
def test_missing_or_invalid_source_fails_closed(monkeypatch, value):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    with pytest.raises(TLSConfigurationError):
        tls_verification(openshell=True, ca_bundle=value)


@pytest.mark.parametrize(
    "kind", ["missing", "invalid", "empty", "oversized", "private-key", "directory"]
)
def test_bad_bundle_fails_closed_without_path_or_content_leak(tmp_path, caplog, kind):
    path = tmp_path / "PRIVATE_PATH_MARKER.pem"
    if kind == "directory":
        path.mkdir()
    elif kind != "missing":
        path.write_bytes(
            {
                "invalid": b"PRIVATE_CONTENT_MARKER",
                "empty": b"",
                "oversized": b"x" * (1024 * 1024 + 1),
                "private-key": b"-----BEGIN PRIVATE KEY-----",
            }[kind]
        )
    with pytest.raises(TLSConfigurationError) as exc:
        tls_verification(openshell=True, ca_bundle=path)
    rendered = "".join(traceback.format_exception(exc.type, exc.value, exc.tb)) + caplog.text
    assert str(path) not in rendered and "PRIVATE_CONTENT_MARKER" not in rendered
    assert "PRIVATE_PATH_MARKER.pem" not in str(exc.value)


def test_unreadable_bundle_is_sanitized(certificates, monkeypatch):
    def denied(*args):
        raise PermissionError("PRIVATE_CONTENT_MARKER")

    monkeypatch.setattr("app.tls.os.open", denied)
    with pytest.raises(TLSConfigurationError) as exc:
        tls_verification(openshell=True, ca_bundle=certificates / "root.pem")
    assert "PRIVATE_CONTENT_MARKER" not in str(exc.value)


@pytest.mark.parametrize(
    "configuration",
    [
        {"openshell": "true"},
        {"openshell": 1},
        {"ca_bundle": "/unapproved.pem"},
        {"verify": False},
        {"check_hostname": False},
    ],
)
def test_insecure_or_implicit_configuration_not_accepted(configuration):
    with pytest.raises((TypeError, TLSConfigurationError)):
        tls_verification(**configuration)


def credential_provider():
    from app.agent.http_gateway import InMemoryTaskCredential

    return InMemoryTaskCredential(TASK, token())


@pytest.mark.parametrize("execution", [False, True])
def test_gateway_and_execution_construct_with_verified_ca(certificates, monkeypatch, execution):
    captured = []
    original = httpx.AsyncClient

    def client(**kwargs):
        captured.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    cls = ControlledExecutionClient if execution else AuthenticatedHttpToolGateway
    extra = {"enabled": True} if execution else {}
    instance = cls(
        base_url="https://gateway.example.test",
        task_ref=TASK,
        credential_provider=credential_provider(),
        openshell=True,
        ca_bundle=certificates / "root.pem",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=envelope())),
        **extra,
    )
    assert captured[0]["trust_env"] is False and captured[0]["follow_redirects"] is False
    handshake(captured[0]["verify"], certificates)

    async def run():
        if not execution:
            response = await instance.execute(request())
            assert response.execution_status == "NOT_EXECUTED"
        await instance.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["nebius", "gateway", "execution"])
def test_real_httpx_transport_receives_verifying_context_without_network(certificates, kind):
    configuration = dict(openshell=True, ca_bundle=certificates / "root.pem")
    if kind == "nebius":
        instance = NebiusModelProvider(
            NebiusSettings(
                api_key="synthetic-key",
                base_url="https://api.tokenfactory.nebius.com/v1/",
                model_super="nvidia/nemotron-3-super-120b-a12b",
            ),
            **configuration,
        )
        transport = instance._client._client._transport
    else:
        cls = ControlledExecutionClient if kind == "execution" else AuthenticatedHttpToolGateway
        instance = cls(
            base_url="https://gateway.example.test",
            task_ref=TASK,
            credential_provider=credential_provider(),
            **({"enabled": True} if kind == "execution" else {}),
            **configuration,
        )
        auth = instance._auth if kind == "execution" else instance
        transport = auth._client._transport
    context = transport._pool._ssl_context
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    handshake(context, certificates)
    asyncio.run(instance.aclose())


def test_execution_ca_path_preserves_strict_mock_result_and_identity(certificates):
    from tests.agent.test_controlled_execution import client_for, fixture_values

    proposal, binding, result = fixture_values()
    calls = []

    def handler(r):
        calls.append(r)
        return httpx.Response(200, json=result)

    async def run():
        async with client_for(
            handler, openshell=True, ca_bundle=certificates / "root.pem"
        ) as client:
            observed = await client.execute_completed(
                binding, proposal, resume_ref="resume_one", expected_version="version_one"
            )
            assert observed.mode == "SIMULATED" and observed.request_id == proposal.request_id

    asyncio.run(run())
    assert len(calls) == 1 and calls[0].url.host == "backend.test"


def test_execution_ca_path_rejects_redirect_without_forwarding_credentials(certificates):
    from tests.agent.test_controlled_execution import client_for, fixture_values

    proposal, binding, _ = fixture_values()
    calls = []

    def handler(r):
        calls.append(r)
        return httpx.Response(307, headers={"location": "https://unapproved.test/steal"})

    async def run():
        async with client_for(
            handler, openshell=True, ca_bundle=certificates / "root.pem"
        ) as client:
            with pytest.raises(GatewayTransportError):
                await client.execute_completed(
                    binding, proposal, resume_ref="resume_one", expected_version="version_one"
                )

    asyncio.run(run())
    assert len(calls) == 1 and calls[0].url.host == "backend.test"


def test_gateway_authorization_with_ca_and_redirect_never_leaks_credential(certificates):
    calls = []

    def handler(r):
        calls.append(r)
        return httpx.Response(307, headers={"location": "https://unapproved.test/steal"})

    async def run():
        async with AuthenticatedHttpToolGateway(
            base_url="https://gateway.example.test",
            task_ref=TASK,
            credential_provider=credential_provider(),
            openshell=True,
            ca_bundle=certificates / "root.pem",
            transport=httpx.MockTransport(handler),
        ) as gateway:
            with pytest.raises(GatewayTransportError):
                await gateway.execute(request())

    asyncio.run(run())
    assert len(calls) == 1 and calls[0].url.host == "gateway.example.test"
    assert calls[0].headers["authorization"].startswith("Bearer ")


def test_nebius_provider_native_contract_with_ca(certificates, monkeypatch, caplog):
    from app.llm.config import InferenceMode
    from tests.agent.test_nebius_provider import Summary

    captured, calls = [], []
    from app.llm import nebius_provider

    original = nebius_provider.DefaultAsyncHttpxClient

    def client(**kwargs):
        captured.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(nebius_provider, "DefaultAsyncHttpxClient", client)

    def handler(r):
        calls.append(r)
        return httpx.Response(200, json=completion())

    settings = NebiusSettings(
        api_key="synthetic-only-secret",
        base_url="https://api.tokenfactory.nebius.com/v1/",
        model_super="nvidia/nemotron-3-super-120b-a12b",
    )

    async def run():
        async with NebiusModelProvider(
            settings,
            openshell=True,
            ca_bundle=certificates / "root.pem",
            mode=InferenceMode.JSON_SCHEMA,
            response_model=Summary,
            transport=httpx.MockTransport(handler),
        ) as provider:
            assert provider.settings.max_attempts == 3 and provider._client.max_retries == 0
            result = await provider.infer(inference_request())
            assert result.output == {"summary": "Synthetic"}

    asyncio.run(run())
    assert len(calls) == 1 and str(calls[0].url) == str(settings.base_url) + "chat/completions"
    assert captured[0]["trust_env"] is False and captured[0]["follow_redirects"] is False
    handshake(captured[0]["verify"], certificates)
    assert settings.api_key.get_secret_value() not in caplog.text


def test_nebius_ca_path_rejects_redirect_without_forwarding_credentials(certificates):
    from app.llm.errors import NebiusInferenceError

    calls = []

    def handler(r):
        calls.append(r)
        return httpx.Response(307, headers={"location": "https://unapproved.test/steal"})

    async def run():
        async with NebiusModelProvider(
            NebiusSettings(
                api_key="synthetic-key",
                base_url="https://api.tokenfactory.nebius.com/v1/",
                model_super="nvidia/nemotron-3-super-120b-a12b",
                max_attempts=1,
            ),
            openshell=True,
            ca_bundle=certificates / "root.pem",
            transport=httpx.MockTransport(handler),
        ) as provider:
            with pytest.raises(NebiusInferenceError):
                await provider.infer(inference_request())

    asyncio.run(run())
    assert len(calls) == 1 and calls[0].url.host == "api.tokenfactory.nebius.com"


def test_runtime_propagates_trusted_options_only(certificates):
    async def run():
        async with gateway_runtime(
            None,
            mode=ExecutionProvenance.TRUSTED_AUTHORIZATION_ONLY,
            base_url="https://gateway.example.test",
            task_ref=TASK,
            credential_provider=credential_provider(),
            openshell=True,
            ca_bundle=certificates / "root.pem",
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=envelope())),
        ):
            pass
        with pytest.raises(ValueError):
            async with gateway_runtime(None, openshell=True):
                pass

    asyncio.run(run())


def test_model_request_cannot_select_tls_or_disable_verification():
    from pydantic import ValidationError

    from app.agent.gateway_protocol import ToolRequest
    from app.llm.contracts import InferenceRequest

    for model, value in (
        (ToolRequest, request().model_dump(mode="json")),
        (InferenceRequest, inference_request().model_dump(mode="json")),
    ):
        with pytest.raises(ValidationError):
            model.model_validate({**value, "ca_bundle": "/untrusted.pem", "openshell": True})


def test_owner_workflow_transport_stays_outside_sandbox(monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", "/untrusted.pem")
    client = WorkflowControlClient(
        base_url="https://gateway.example.test",
        owner_credential_provider=lambda: token(),
        transport=httpx.MockTransport(lambda r: httpx.Response(500)),
    )
    asyncio.run(client.aclose())


def test_invalid_ca_before_http_client_creation(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("HTTP client must not be constructed for invalid CA")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    with pytest.raises(TLSConfigurationError):
        AuthenticatedHttpToolGateway(
            base_url="https://gateway.example.test",
            task_ref=TASK,
            credential_provider=credential_provider(),
            openshell=True,
            ca_bundle="/missing.pem",
        )
