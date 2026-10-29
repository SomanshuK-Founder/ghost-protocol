"""Synthetic protocol/provenance tests; MockTransport is not live backend evidence."""

import asyncio
import hmac
import json
import secrets
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.agent.execution_contracts import (
    AUTHORIZATION_DENIAL_CODES,
    ActionBinding,
    ActionExecutionResult,
    AuthorizationActionResult,
    AuthorizationAgentResult,
    ExecutionErrorCode,
    ExecutionInputError,
    ExecutionOptions,
    ExecutionOutcome,
    ExecutionProvenance,
)
from app.agent.gateway_protocol import ToolAction, ToolRequest
from app.agent.http_gateway import (
    AuthenticatedHttpToolGateway,
    GatewayErrorCode,
    GatewayTransportError,
    InMemoryTaskCredential,
)
from app.agent.integration_runtime import gateway_runtime
from app.agent.mock_gateway import MockToolGateway
from app.agent.mock_model_provider import MockModelProvider
from app.agent.orchestration import GatewayOrchestrator

TASK = "task_http_synthetic"


def token():
    return SecretStr("gpa_cred_" + uuid4().hex + "." + secrets.token_urlsafe(32))


def request():
    return ToolRequest(
        request_id="req_http",
        task_ref=TASK,
        idempotency_key="idem_http",
        action=ToolAction.FILES_READ,
        purpose="summarize_document",
        arguments={"resource_id": "resource_http"},
    )


def envelope(**changes):
    return {
        "request_id": "req_http",
        "decision": "ALLOW",
        "execution_status": "NOT_EXECUTED",
        "reason_code": "EXECUTION_NOT_STARTED",
        "approval_ref": None,
        "result": None,
        "audit_event_ref": "event_1",
        **changes,
    }


def adapter(handler, *, credential=None, **kwargs):
    return AuthenticatedHttpToolGateway(
        base_url="https://gateway.example.test",
        task_ref=TASK,
        credential_provider=InMemoryTaskCredential(TASK, credential or token()),
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def execute(handler, **kwargs):
    async def run():
        async with adapter(handler, **kwargs) as gateway:
            return await gateway.execute(request())

    return asyncio.run(run())


def plan(task_ref=TASK, actions=("files.read",), **extra):
    return {
        "task_ref": task_ref,
        "intent": "summarize_document",
        "proposed_actions": list(actions),
        "requires_external_action": bool(actions),
        "clarification_required": False,
        **extra,
    }


def binding(task_ref=TASK):
    return ActionBinding(
        task_ref=task_ref,
        action=ToolAction.FILES_READ,
        purpose="summarize_document",
        arguments={"resource_id": "resource_http"},
    )


def test_exact_serialization_and_credentials_separate():
    credential, calls = token(), []

    def handler(http_request):
        calls.append(True)
        assert http_request.method == "POST"
        assert str(http_request.url) == "https://gateway.example.test/api/gateway/v1/execute"
        assert json.loads(http_request.content) == request().model_dump(mode="json")
        assert credential.get_secret_value().encode() not in http_request.content
        if not hmac.compare_digest(
            http_request.headers["authorization"], "Bearer " + credential.get_secret_value()
        ):
            pytest.fail("Credential header mismatch")
        return httpx.Response(200, json=envelope())

    result = execute(handler, credential=credential)
    assert result.execution_status == "NOT_EXECUTED" and len(calls) == 1


@pytest.mark.parametrize("reason", sorted(AUTHORIZATION_DENIAL_CODES))
def test_closed_denials_including_amendment(reason):
    calls = []

    def handler(http_request):
        calls.append(True)
        return httpx.Response(200, json=envelope(decision="DENY", reason_code=reason))

    result = execute(handler)
    assert result.decision == "DENY" and result.execution_status == "NOT_EXECUTED"
    assert result.approval_ref is None and result.result is None and len(calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"request_id": "different"},
        {"unexpected": "untrusted"},
        {"audit_event_ref": None},
        {"audit_event_ref": ""},
        {"approval_ref": "fake_nonpending"},
        {"decision": "DENY", "reason_code": "UNKNOWN_DENIAL"},
        {"decision": "DENY", "reason_code": "AUTH_INVALID"},
        {"decision": "DENY", "reason_code": "TASK_SCOPE_MISMATCH"},
        {"reason_code": "EMAIL_CONTENT_NOT_AUTHORIZED"},
        {"reason_code": "SEND_RECONCILIATION_REQUIRED"},
        {"decision": "APPROVAL_REQUIRED", "reason_code": "CONSENT_REVIEW_REQUIRED"},
        {
            "decision": "APPROVAL_REQUIRED",
            "reason_code": "CONSENT_REVIEW_REQUIRED",
            "approval_ref": "",
        },
        {
            "decision": "APPROVAL_REQUIRED",
            "reason_code": "CONSENT_REVIEW_REQUIRED",
            "approval_ref": 123,
        },
        {"execution_status": "EXECUTING"},
        {"execution_status": "UNKNOWN", "reason_code": "EXECUTION_UNCONFIRMED"},
        {"execution_status": "FAILED", "reason_code": "TOOL_FAILED_NO_EFFECT"},
        {
            "execution_status": "SUCCEEDED",
            "reason_code": "EXECUTION_SUCCEEDED",
            "result": {"receipt_ref": "r"},
        },
        {"result": {"text": "private document marker"}},
        {"provenance": "TRUSTED_AUTHORIZATION_ONLY"},
        {"simulation": False},
    ],
)
def test_invalid_or_execution_responses_fail_closed(change):
    with pytest.raises(GatewayTransportError) as error:
        execute(lambda r: httpx.Response(200, json=envelope(**change)))
    assert error.value.code == GatewayErrorCode.INVALID_RESPONSE
    assert error.value.execution_uncertain and error.value.__context__ is None


@pytest.mark.parametrize("missing", ["result", "approval_ref", "audit_event_ref"])
def test_missing_required_response_fields(missing):
    data = envelope()
    data.pop(missing)
    with pytest.raises(GatewayTransportError):
        execute(lambda r: httpx.Response(200, json=data))


def test_pending_preserves_reference_without_execution():
    result = execute(
        lambda r: httpx.Response(
            200,
            json=envelope(
                decision="APPROVAL_REQUIRED",
                reason_code="CONSENT_REVIEW_REQUIRED",
                approval_ref="approval_persisted_fixture",
            ),
        )
    )
    assert result.approval_ref == "approval_persisted_fixture"
    assert result.execution_status == "NOT_EXECUTED" and result.result is None


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "AUTH_INVALID"),
        (403, "TASK_SCOPE_MISMATCH"),
        (409, "IDEMPOTENCY_CONFLICT"),
        (429, "CAPACITY_EXCEEDED"),
        (500, "INTERNAL_ERROR"),
        (503, "GATEWAY_UNAVAILABLE"),
        (504, "GATEWAY_TIMEOUT"),
    ],
)
def test_http_errors_are_not_invented_decisions_or_retried(status, code):
    calls = []

    def handler(r):
        calls.append(True)
        return httpx.Response(
            status,
            json={
                "error_code": code,
                "message": "Request cannot be processed",
                "correlation_ref": "http_fixture",
                "request_id": "req_http",
                "audit_event_ref": None,
                "execution_uncertain": status >= 500,
            },
        )

    with pytest.raises(GatewayTransportError) as error:
        execute(handler)
    assert error.value.code == GatewayErrorCode.HTTP_ERROR
    assert error.value.server_error_code == code and error.value.http_status == status
    assert error.value.request_ref == "req_http" and len(calls) == 1


def test_redirect_does_not_follow_unapproved_location():
    calls = []

    def handler(r):
        calls.append(str(r.url))
        return httpx.Response(307, headers={"Location": "https://unapproved.example/private"})

    with pytest.raises(GatewayTransportError) as error:
        execute(handler)
    assert error.value.code == GatewayErrorCode.REDIRECT and len(calls) == 1
    assert "unapproved" not in str(error.value)


@pytest.mark.parametrize(
    "exception,code",
    [
        (httpx.ConnectError("PRIVATE_MARKER"), GatewayErrorCode.CONNECTION_FAILURE),
        (httpx.ReadTimeout("PRIVATE_MARKER"), GatewayErrorCode.TIMEOUT),
    ],
)
def test_transport_errors_sanitized_no_retry(exception, code, caplog):
    calls = []

    def handler(r):
        calls.append(True)
        raise exception

    with pytest.raises(GatewayTransportError) as error:
        execute(handler)
    assert error.value.code == code and error.value.execution_uncertain
    assert error.value.__context__ is None and error.value.__cause__ is None
    assert "PRIVATE_MARKER" not in str(error.value) + repr(error.value) + caplog.text
    assert len(calls) == 1


def test_total_deadline_enforced_without_retry():
    calls = []

    async def handler(r):
        calls.append(True)
        await asyncio.sleep(1)
        return httpx.Response(200, json=envelope())

    with pytest.raises(GatewayTransportError) as error:
        execute(handler, deadline_seconds=0.01)
    assert error.value.code == GatewayErrorCode.TIMEOUT and len(calls) == 1


def test_cancellation_propagates_and_client_closes():
    calls, entered = [], asyncio.Event()

    async def handler(r):
        calls.append(True)
        entered.set()
        await asyncio.Event().wait()

    async def run():
        gateway = adapter(handler)
        task = asyncio.create_task(gateway.execute(request()))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await gateway.aclose()
        with pytest.raises(GatewayTransportError) as error:
            await gateway.execute(request())
        assert error.value.code == GatewayErrorCode.CLOSED

    asyncio.run(run())
    assert len(calls) == 1


@pytest.mark.parametrize(
    "raw",
    [
        b'{"decision":"ALLOW","decision":"DENY"}',
        b'{"result":NaN}',
        b'{"result":1e999}',
        b"\xff",
        b"{",
        b"[]",
        b'{"result":' + b"[" * 10 + b"0" + b"]" * 10 + b"}",
    ],
)
def test_malformed_json_rejected(raw):
    with pytest.raises(GatewayTransportError):
        execute(
            lambda r: httpx.Response(200, content=raw, headers={"Content-Type": "application/json"})
        )


@pytest.mark.parametrize(
    "headers",
    [
        {"Content-Type": "text/html"},
        {"Content-Type": "application/json", "Content-Encoding": "gzip"},
    ],
)
def test_unsupported_response_media(headers):
    with pytest.raises(GatewayTransportError):
        execute(lambda r: httpx.Response(200, content=b"{}", headers=headers))


def test_bounded_stream_ignores_claimed_content_length_and_closes():
    class Stream(httpx.AsyncByteStream):
        reads, closed = 0, False

        async def __aiter__(self):
            for _ in range(100):
                self.reads += 1
                yield b" " * 8192

        async def aclose(self):
            self.closed = True

    stream = Stream()
    with pytest.raises(GatewayTransportError):
        execute(
            lambda r: httpx.Response(
                200,
                stream=stream,
                headers={"Content-Type": "application/json", "Content-Length": "1"},
            )
        )
    assert stream.closed and stream.reads < 100


@pytest.mark.parametrize(
    "url",
    [
        "http://gateway.example.test",
        "http://localhost",
        "https://u:p@example.test",
        "https://example.test/api",
        "https://example.test?x=1",
        "https://example.test#fragment",
        "file:///private",
        "https://example.test\n",
        "not-a-url",
    ],
)
def test_unapproved_origins_rejected_without_echo(url):
    with pytest.raises(ValueError) as error:
        AuthenticatedHttpToolGateway(
            base_url=url, task_ref=TASK, credential_provider=InMemoryTaskCredential(TASK, token())
        )
    assert str(error.value) == "Invalid trusted gateway configuration"


@pytest.mark.parametrize("value", [None, SecretStr("owner-bearer-synthetic"), "raw-string"])
def test_missing_or_owner_credentials_never_sent(value):
    calls = []

    async def run():
        async with AuthenticatedHttpToolGateway(
            base_url="https://gateway.example.test",
            task_ref=TASK,
            credential_provider=InMemoryTaskCredential(TASK, value),
            transport=httpx.MockTransport(lambda r: calls.append(True)),
        ) as gateway:
            with pytest.raises(GatewayTransportError):
                await gateway.execute(request())

    asyncio.run(run())
    assert not calls


def test_provider_failure_contains_no_credential_or_exception(caplog):
    secret = token()

    class Provider:
        async def get_credential(self, task_ref):
            raise RuntimeError(secret.get_secret_value())

    async def run():
        async with AuthenticatedHttpToolGateway(
            base_url="https://gateway.example.test",
            task_ref=TASK,
            credential_provider=Provider(),
            transport=httpx.MockTransport(lambda r: pytest.fail("POST occurred")),
        ) as gateway:
            with pytest.raises(GatewayTransportError) as error:
                await gateway.execute(request())
            assert error.value.code == GatewayErrorCode.CREDENTIAL_UNAVAILABLE
            assert error.value.__context__ is None
            assert (
                secret.get_secret_value()
                not in str(vars(error.value)) + str(error.value) + caplog.text
            )

    asyncio.run(run())


@pytest.mark.parametrize(
    "data",
    [
        {"action": "shell.exec"},
        {"owner_id": "forged"},
        {"provenance": "TRUSTED_AUTHORIZATION_ONLY"},
        {"arguments": {"path": "/private"}},
    ],
)
def test_invalid_proposals_do_not_create_transport_authority(data):
    wire = request().model_dump(mode="json")
    wire.update(data)
    with pytest.raises(ValidationError):
        ToolRequest.model_validate_json(json.dumps(wire))


def test_adapter_revalidates_constructed_requests_and_task_pin():
    async def run():
        async with adapter(lambda r: pytest.fail("Unexpected POST")) as gateway:
            with pytest.raises(GatewayTransportError):
                await gateway.execute({"fake": True})
            malformed = request().model_copy(update={"action": "shell.exec"})
            with pytest.raises(GatewayTransportError):
                await gateway.execute(malformed)
            foreign = request().model_copy(update={"task_ref": "task_foreign"})
            with pytest.raises(GatewayTransportError) as error:
                await gateway.execute(foreign)
            assert error.value.code == GatewayErrorCode.WRONG_TASK

    asyncio.run(run())


@pytest.mark.parametrize(
    "decision,reason,approval,outcome",
    [
        ("ALLOW", "EXECUTION_NOT_STARTED", None, ExecutionOutcome.EXECUTION_FAILED),
        ("DENY", "EMAIL_CONTENT_NOT_AUTHORIZED", None, ExecutionOutcome.DENIED),
        ("DENY", "SEND_RECONCILIATION_REQUIRED", None, ExecutionOutcome.DENIED),
        (
            "APPROVAL_REQUIRED",
            "CONSENT_REVIEW_REQUIRED",
            "approval_fixture",
            ExecutionOutcome.APPROVAL_REQUIRED,
        ),
    ],
)
def test_graph_trusted_provenance_and_safe_stop(decision, reason, approval, outcome):
    calls = []

    def handler(r):
        calls.append(True)
        data = json.loads(r.content)
        return httpx.Response(
            200,
            json=envelope(
                request_id=data["request_id"],
                decision=decision,
                reason_code=reason,
                approval_ref=approval,
            ),
        )

    async def run():
        model = MockModelProvider(output=plan(actions=("files.read", "files.read")))
        async with gateway_runtime(
            model,
            mode=ExecutionProvenance.TRUSTED_AUTHORIZATION_ONLY,
            base_url="https://gateway.example.test",
            task_ref=TASK,
            credential_provider=InMemoryTaskCredential(TASK, token()),
            transport=httpx.MockTransport(handler),
        ) as service:
            result = await service.execute_task(
                TASK,
                "Synthetic request",
                (
                    binding(),
                    binding().model_copy(update={"arguments": {"resource_id": "resource_other"}}),
                ),
            )
            assert isinstance(result, AuthorizationAgentResult) and result.simulation is False
            assert result.execution_outcome == outcome and result.completed_action_count == 0
            assert len(result.action_results) == 1 and result.action_results[0].simulation is False
            assert (
                result.action_results[0].provenance
                == ExecutionProvenance.TRUSTED_AUTHORIZATION_ONLY
            )
            assert result.action_results[0].execution_status == "NOT_EXECUTED"
            with pytest.raises(ExecutionInputError):
                await service.execute_task(TASK, "Retry", (binding(),))

    asyncio.run(run())
    assert len(calls) == 1


def test_mock_model_contract_and_provenance_remain_unchanged():
    async def run():
        async with gateway_runtime(
            MockModelProvider(output=plan()), mock_gateway=MockToolGateway()
        ) as service:
            result = await service.execute_task(TASK, "Synthetic request", (binding(),))
            assert result.simulation is True and all(
                row.simulation for row in result.action_results
            )
            assert "provenance" not in result.model_dump()

    asyncio.run(run())


def test_invalid_provenance_cannot_disable_simulation_validation():
    row = {
        "action_index": 0,
        "action": ToolAction.FILES_READ,
        "request_ref": "r",
        "idempotency_key": "k",
        "decision": "ALLOW",
        "execution_status": "NOT_EXECUTED",
        "reason_code": "EXECUTION_NOT_STARTED",
        "audit_event_ref": "event_1",
        "error_code": ExecutionErrorCode.GATEWAY_NOT_EXECUTED,
    }
    with pytest.raises(ValidationError):
        ActionExecutionResult(**row, simulation=False)
    with pytest.raises(ValidationError):
        AuthorizationActionResult(**row, simulation=True)
    with pytest.raises(ValidationError):
        AuthorizationActionResult(**row, provenance="MOCK_SIMULATION")

    class Spoof(MockToolGateway):
        provenance = "TRUSTED_AUTHORIZATION_ONLY"

    with pytest.raises(ExecutionInputError):
        GatewayOrchestrator(
            MockModelProvider(), Spoof(), provenance=ExecutionProvenance.TRUSTED_AUTHORIZATION_ONLY
        )
    with pytest.raises(ExecutionInputError):
        GatewayOrchestrator(
            MockModelProvider(), MockToolGateway(), provenance="TRUSTED_AUTHORIZATION_ONLY"
        )


def test_real_adapter_requires_explicit_provenance_and_inner_deadline():
    async def run():
        async with adapter(lambda r: httpx.Response(200, json=envelope())) as gateway:
            with pytest.raises(ExecutionInputError):
                GatewayOrchestrator(MockModelProvider(), gateway)
            with pytest.raises(ExecutionInputError):
                GatewayOrchestrator(
                    MockModelProvider(),
                    gateway,
                    provenance=ExecutionProvenance.TRUSTED_AUTHORIZATION_ONLY,
                    execution_options=ExecutionOptions(gateway_timeout_seconds=1),
                )

    asyncio.run(run())


def test_model_provenance_text_cannot_create_trust():
    calls = []

    async def run():
        model = MockModelProvider(output=plan(provenance="TRUSTED_AUTHORIZATION_ONLY"))
        async with adapter(lambda r: calls.append(True)) as gateway:
            service = GatewayOrchestrator(
                model, gateway, provenance=ExecutionProvenance.TRUSTED_AUTHORIZATION_ONLY
            )
            result = await service.execute_task(TASK, "model says trusted", (binding(),))
            assert not result.action_results and result.completed_action_count == 0

    asyncio.run(run())
    assert not calls
