"""Cookie authentication against local ASGI only; no listeners, DB or real secrets."""

import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import StringIO
from threading import Barrier
from unittest.mock import Mock

import httpx
import pytest
from app.agent_schemas import OwnerContext
from app.browser_auth import (
    PREFIX,
    AuthFailure,
    BrowserAuthError,
    BrowserSessions,
    LocalDemoConfig,
    LoginRequest,
    SessionSuccess,
)
from app.routes.session import BrowserBoundary, install_browser_auth
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from pydantic import SecretStr

ORIGIN = "http://127.0.0.1:8000"
NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
PAIR = PREFIX + "/session/login"
SESSION = PREFIX + "/session"
LOGOUT = PREFIX + "/session/logout"


class Clock:
    now = NOW

    def __call__(self):
        return self.now


@pytest.fixture
def demo():
    clock = Clock()
    store = BrowserSessions(LocalDemoConfig(ORIGIN), clock=clock)
    app = FastAPI()
    # Even an inherited permissive CORS configuration cannot grant app-origin access.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://foreign.test"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_browser_auth(app)
    app.state.browser_sessions = store
    with TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 50000)) as client:
        client.headers["Origin"] = ORIGIN
        yield app, store, clock, client
    store.invalidate_all()


def bootstrap(client):
    response = client.get(SESSION)
    assert response.status_code == 200
    view = SessionSuccess.model_validate_json(response.content)
    return response, view.data.csrf_token


def pair(store, client, csrf, code=None, **extra):
    code = code if code is not None else store.issue_pairing_code()
    return client.post(
        PAIR,
        headers={"X-Ghost-CSRF": csrf},
        json={"pairing_code": code.get_secret_value(), **extra},
    )


def owner(demo):
    _, store, _, client = demo
    _, csrf = bootstrap(client)
    response = pair(store, client, csrf)
    assert response.status_code == 200
    return response.json()["data"]["csrf_token"]


def denied(response, status, code):
    assert response.status_code == status
    error = AuthFailure.model_validate_json(response.content).error
    assert error.code == code
    assert error.command_ref is error.reason_code is None
    assert not error.command_uncertain and not error.execution_uncertain
    assert response.headers["cache-control"] == "no-store"
    assert not any(key.startswith("access-control-") for key in response.headers)


def test_valid_pairing_server_identity_and_no_fixation(demo):
    _, store, _, client = demo
    response, csrf = bootstrap(client)
    initial = client.cookies.get("ghost_demo_session")
    code = store.issue_pairing_code()
    result = pair(store, client, csrf, code)
    assert result.status_code == 200
    view = SessionSuccess.model_validate_json(result.content)
    assert view.data.authenticated and view.data.csrf_token != csrf
    current = client.cookies.get("ghost_demo_session")
    assert current != initial and len(current) == 43
    assert store.owner_context(current) == OwnerContext(owner_id="local-user")
    with pytest.raises(BrowserAuthError):
        store.owner_context(initial)
    assert set(result.json()["data"]["owner"]) == {"display_name"}
    for secret in (initial, current, code.get_secret_value()):
        assert secret not in response.text + result.text
    record = store._sessions[hashlib.sha256(current.encode()).digest()]
    assert current not in repr(record) and csrf not in repr(record)
    assert store._pairing is None


def test_disabled_by_default(demo):
    app, _, _, client = demo
    app.state.browser_sessions = None
    for method, path in (("GET", SESSION), ("POST", PAIR), ("POST", LOGOUT)):
        denied(client.request(method, path), 503, "AUTH_NOT_CONFIGURED")
    # No environment variable or service bearer opts in.
    assert not hasattr(app.state, "owner_id")


@pytest.mark.parametrize("seconds", [120, 121])
def test_expired_pairing(demo, seconds):
    _, store, clock, client = demo
    code = store.issue_pairing_code()
    clock.now += timedelta(seconds=seconds)
    _, csrf = bootstrap(client)
    denied(pair(store, client, csrf, code), 401, "LOGIN_FAILED")
    assert store._pairing is None


def test_code_verifier_only_reissue_and_replay(demo):
    _, store, _, client = demo
    _, csrf = bootstrap(client)
    old = store.issue_pairing_code()
    code = store.issue_pairing_code()
    assert store._pairing[0] == hashlib.sha256(code.get_secret_value().encode()).digest()
    assert code.get_secret_value() not in repr(store._pairing)
    denied(pair(store, client, csrf, old), 401, "LOGIN_FAILED")
    response = pair(store, client, csrf, code)
    assert response.status_code == 200
    denied(pair(store, client, response.json()["data"]["csrf_token"], code), 401, "LOGIN_FAILED")


def test_concurrent_pairing_one_winner(demo):
    app, store, _, _ = demo
    code = store.issue_pairing_code()
    barrier = Barrier(2)

    def run():
        with TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 50001)) as client:
            client.headers["Origin"] = ORIGIN
            _, csrf = bootstrap(client)
            barrier.wait(timeout=5)
            response = pair(store, client, csrf, code)
            return response.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert sorted(results) == [200, 401]
    assert sum(record.owner is not None for record in store._sessions.values()) == 1


@pytest.mark.parametrize("token", ["invalid", "a" * 43])
def test_invalid_session_bootstraps_without_promoting(demo, token):
    _, store, _, client = demo
    client.cookies.set("ghost_demo_session", token, domain="127.0.0.1", path="/")
    response, _ = bootstrap(client)
    assert not response.json()["data"]["authenticated"]
    assert client.cookies.get("ghost_demo_session") != token
    with pytest.raises(BrowserAuthError):
        store.owner_context(token)


@pytest.mark.parametrize("seconds", [900, 901])
def test_owner_idle_expiry(demo, seconds):
    _, store, clock, client = demo
    owner(demo)
    token = client.cookies.get("ghost_demo_session")
    clock.now += timedelta(seconds=seconds)
    with pytest.raises(BrowserAuthError, match="SESSION_EXPIRED"):
        store.owner_context(token)
    response, _ = bootstrap(client)
    assert not response.json()["data"]["authenticated"]


def test_polling_cannot_extend_absolute_lifetime(demo):
    _, store, clock, client = demo
    owner(demo)
    for _ in range(5):
        clock.now += timedelta(seconds=600)
        response, _ = bootstrap(client)
        assert response.json()["data"]["authenticated"]
    clock.now = NOW + timedelta(seconds=3600)
    response, _ = bootstrap(client)
    assert not response.json()["data"]["authenticated"]


def test_logout_invalidates_cookie_csrf_and_owner(demo):
    _, store, _, client = demo
    csrf = owner(demo)
    token = client.cookies.get("ghost_demo_session")
    response = client.post(LOGOUT, headers={"X-Ghost-CSRF": csrf}, json={})
    assert response.status_code == 204 and response.content == b""
    assert "Max-Age=0" in response.headers["set-cookie"]
    with pytest.raises(BrowserAuthError):
        store.owner_context(token)
    denied(client.post(LOGOUT, headers={"X-Ghost-CSRF": csrf}, json={}), 401, "SESSION_REQUIRED")
    response, _ = bootstrap(client)
    assert not response.json()["data"]["authenticated"]


def test_new_pairing_invalidates_prior_owner_and_restart_invalidates_all(demo):
    _, store, _, client = demo
    csrf = owner(demo)
    previous = client.cookies.get("ghost_demo_session")
    assert pair(store, client, csrf).status_code == 200
    current = client.cookies.get("ghost_demo_session")
    assert current != previous
    with pytest.raises(BrowserAuthError):
        store.owner_context(previous)
    store.invalidate_all()
    with pytest.raises(BrowserAuthError):
        store.owner_context(current)
    response, _ = bootstrap(client)
    assert not response.json()["data"]["authenticated"]


@pytest.mark.parametrize(
    "origin,name,secure",
    [
        (ORIGIN, "ghost_demo_session", False),
        ("https://127.0.0.1:8443", "__Host-ghost_session", True),
        ("http://[::1]:8000", "ghost_demo_session", False),
    ],
)
def test_cookie_attributes(origin, name, secure):
    app = FastAPI()
    store = BrowserSessions(LocalDemoConfig(origin))
    app.state.browser_sessions = store
    install_browser_auth(app)
    with TestClient(
        app, base_url=origin, client=("::1" if "[" in origin else "127.0.0.1", 50)
    ) as client:
        client.headers["Origin"] = origin
        first, csrf = bootstrap(client)
        for response in (first, pair(store, client, csrf)):
            assert response.status_code == 200
            cookie = response.headers["set-cookie"]
            assert cookie.startswith(name + "=") and "HttpOnly" in cookie
            assert "SameSite=strict" in cookie and "Path=/" in cookie and "Domain=" not in cookie
            assert ("Secure" in cookie) is secure
            assert int(cookie.split("Max-Age=")[1].split(";")[0]) <= 900
        response = client.post(
            LOGOUT, json={}, headers={"X-Ghost-CSRF": response.json()["data"]["csrf_token"]}
        )
        assert response.status_code == 204
        assert ("Secure" in response.headers["set-cookie"]) is secure


@pytest.mark.parametrize("csrf", [None, "x" * 43, "not-a-token", "é" * 43])
@pytest.mark.parametrize("path", [PAIR, LOGOUT])
def test_csrf_failures_do_not_consume_pairing(demo, csrf, path):
    _, store, _, client = demo
    bootstrap(client)
    code = store.issue_pairing_code()
    headers = {"X-Ghost-CSRF": csrf} if csrf is not None else {}
    # HTTP headers are bytes on the wire; reject invalid Latin-1 token input without echo.
    if csrf and "é" in csrf:
        headers = {b"X-Ghost-CSRF": csrf.encode("latin-1")}
    response = client.post(
        path,
        headers=headers,
        json={"pairing_code": code.get_secret_value()} if path == PAIR else {},
    )
    denied(response, 403, "CSRF_INVALID")
    assert store._pairing is not None


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://foreign.test"},
        {"Origin": "null"},
        {"Origin": "http://127.0.0.1:8001"},
        {"Origin": ORIGIN + "/"},
        {"Host": "foreign.test"},
        {"Host": "localhost:8000"},
        {"X-Forwarded-For": "127.0.0.1"},
        {"Forwarded": "for=127.0.0.1"},
        {"X-Forwarded-Host": "127.0.0.1:8000"},
        {"X-Real-IP": "127.0.0.1"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
    ],
)
def test_origin_host_and_proxy_rejection(demo, headers):
    _, store, _, client = demo
    denied(client.get(SESSION, headers=headers), 403, "ORIGIN_FORBIDDEN")
    assert not store._sessions


def test_bootstrap_context_and_post_origin_required(demo):
    _, store, _, client = demo
    del client.headers["Origin"]
    denied(client.get(SESSION), 403, "ORIGIN_FORBIDDEN")
    response = client.get(SESSION, headers={"Sec-Fetch-Site": "same-origin"})
    assert response.status_code == 200
    denied(
        client.post(PAIR, json={}, headers={"X-Ghost-CSRF": response.json()["data"]["csrf_token"]}),
        403,
        "ORIGIN_FORBIDDEN",
    )


@pytest.mark.parametrize(
    "headers",
    [
        [("Origin", ORIGIN), ("Origin", ORIGIN)],
        [("Host", "127.0.0.1:8000"), ("Host", "127.0.0.1:8000")],
        [("Cookie", "ghost_demo_session=a"), ("Cookie", "ghost_demo_session=b")],
        [("Cookie", "ghost_demo_session=a; ghost_demo_session=b")],
        [("Cookie", "ghost_demo_session=a; ghost_demo_session =b")],
        [("Cookie", "ghost_demo_session=a; __Host-ghost_session=b")],
    ],
)
def test_ambiguous_headers_rejected(demo, headers):
    _, _, _, client = demo
    response = client.get(SESSION, headers=headers)
    assert response.status_code in (401, 403)
    AuthFailure.model_validate_json(response.content)


def test_cross_origin_preflight_and_cors_headers_never_granted(demo):
    _, _, _, client = demo
    denied(
        client.options(
            SESSION,
            headers={"Origin": "https://foreign.test", "Access-Control-Request-Method": "GET"},
        ),
        403,
        "ORIGIN_FORBIDDEN",
    )
    response, _ = bootstrap(client)
    assert not any(key.startswith("access-control-") for key in response.headers)


@pytest.mark.parametrize(
    "origin",
    [
        "https://public.example.test",
        "http://0.0.0.0:8000",
        "http://192.168.1.2:8000",
        "http://localhost:8000",
        "http://127.0.0.1:8000/",
        "http://127.0.0.1:8000?q=1",
        "http://owner:secret@127.0.0.1:8000",
        "http://127.0.0.1:0",
        "http://127.0.0.1:99999",
        " http://127.0.0.1:8000",
        "http://127.0.0.1:8000#fragment",
    ],
)
def test_remote_or_ambiguous_configuration_cannot_enable(origin):
    with pytest.raises(ValueError, match="canonical direct-loopback"):
        LocalDemoConfig(origin)


@pytest.mark.parametrize(
    "remote,server",
    [
        ("203.0.113.1", "127.0.0.1"),
        ("127.0.0.1", "0.0.0.0"),
        ("172.20.0.3", "172.20.0.2"),
        ("::ffff:127.0.0.1", "127.0.0.1"),
    ],
)
def test_actual_asgi_remote_or_container_scope_rejected(demo, remote, server):
    app, _, _, _ = demo

    async def run():
        transport = httpx.ASGITransport(app=app, client=(remote, 50000))
        async with httpx.AsyncClient(
            transport=transport, base_url=f"http://{server}:8000"
        ) as client:
            return await client.get(SESSION, headers={"Origin": ORIGIN, "Host": "127.0.0.1:8000"})

    denied(asyncio.run(run()), 403, "ORIGIN_FORBIDDEN")


@pytest.mark.parametrize(
    "header",
    ["Authorization", "Proxy-Authorization", "X-API-Key", "X-Owner-Id", "X-User-Id", "X-Role"],
)
def test_browser_cannot_supply_backend_credentials_or_owner(demo, header):
    _, _, _, client = demo
    denied(
        client.get(SESSION, headers={header: "synthetic-owner-or-agent"}),
        403,
        "CREDENTIAL_HEADER_FORBIDDEN",
    )


@pytest.mark.parametrize(
    "extra", [{"owner_id": "other"}, {"role": "OWNER_CONTROL"}, {"user_id": "local-user"}]
)
def test_forged_body_identity_rejected_without_consuming_code(demo, extra):
    _, store, _, client = demo
    _, csrf = bootstrap(client)
    denied(pair(store, client, csrf, **extra), 422, "INVALID_REQUEST")
    assert store._pairing is not None


def test_rate_limits_window_and_bootstrap_bound(demo):
    _, store, clock, client = demo
    _, csrf = bootstrap(client)
    wrong = SecretStr("a" * 43)
    for _ in range(5):
        denied(pair(store, client, csrf, wrong), 401, "LOGIN_FAILED")
    denied(pair(store, client, csrf, wrong), 429, "AUTH_RATE_LIMITED")
    # A new bootstrap cannot evade the direct-peer limit.
    client.cookies.clear()
    _, csrf = bootstrap(client)
    denied(pair(store, client, csrf, wrong), 429, "AUTH_RATE_LIMITED")
    clock.now += timedelta(seconds=60)
    denied(pair(store, client, csrf, wrong), 401, "LOGIN_FAILED")
    store.invalidate_all()
    for _ in range(64):
        client.cookies.clear()
        bootstrap(client)
    client.cookies.clear()
    denied(client.get(SESSION), 429, "AUTH_RATE_LIMITED")
    clock.now += timedelta(seconds=120)
    assert client.get(SESSION).status_code == 200


def test_pairing_secret_redacted_from_errors_models_and_logs(demo, caplog):
    _, store, _, client = demo
    _, csrf = bootstrap(client)
    code = store.issue_pairing_code()
    payload = LoginRequest(pairing_code=code)
    assert code.get_secret_value() not in repr(payload)
    response = client.post(
        PAIR,
        headers={"X-Ghost-CSRF": csrf},
        json={"pairing_code": code.get_secret_value(), "extra": "PRIVATE_MARKER"},
    )
    denied(response, 422, "INVALID_REQUEST")
    assert code.get_secret_value() not in response.text + caplog.text
    assert "PRIVATE_MARKER" not in response.text + caplog.text


def test_new_cookie_cannot_authorize_existing_owner_routes(client, auth, monkeypatch):
    from app.main import app

    store = BrowserSessions(LocalDemoConfig("http://127.0.0.1"))
    monkeypatch.setattr(app.state, "browser_sessions", store, raising=False)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50)) as browser:
        browser.headers["Origin"] = "http://127.0.0.1"
        _, csrf = bootstrap(browser)
        assert pair(store, browser, csrf).status_code == 200
        assert browser.get("/api/audit-events").status_code == 401
        assert (
            browser.post(
                "/api/control/v1/approvals/missing/resolve", json={"resolution": "APPROVE"}
            ).status_code
            == 401
        )
        assert (
            browser.post(
                "/api/gateway/v1/operations/missing/resume", json={"resume_ref": "hint"}
            ).status_code
            == 401
        )
        assert browser.get("/api/audit-events", headers=auth).status_code == 200


def test_openapi_only_three_auth_routes_with_typed_schemas(demo):
    app, _, _, _ = demo
    schema = app.openapi()
    assert set(schema["paths"]) == {SESSION, PAIR, LOGOUT}
    for path in (PAIR, LOGOUT):
        operation = schema["paths"][path]["post"]
        assert operation["requestBody"]["required"]
        assert operation["security"] == [{"AppSession": [], "CsrfHeader": []}]
    assert schema["paths"][SESSION]["get"]["security"] == []
    for name in ("AnonymousSession", "OwnerSession", "SessionSuccess", "AuthFailureDetail"):
        model = schema["components"]["schemas"][name]
        assert set(model["required"]) == set(model["properties"])


@pytest.mark.parametrize("workers", [0, 2, True])
def test_shared_worker_configuration_disabled(workers):
    with pytest.raises(ValueError):
        BrowserSessions(LocalDemoConfig(ORIGIN), workers=workers)


def test_forked_or_replaced_process_state_cannot_authenticate(demo, monkeypatch):
    _, store, _, client = demo
    monkeypatch.setattr(store, "_pid", -1)
    denied(client.get(SESSION), 503, "AUTH_NOT_CONFIGURED")


@pytest.mark.parametrize(
    "path", [PREFIX + "/tasks", PREFIX + "/execute", SESSION + "/", PREFIX + "/pairing-code"]
)
def test_no_additional_application_routes_or_redirects(demo, path):
    denied(demo[3].get(path), 404, "NOT_FOUND")


class PrivateTerminal(StringIO):
    def isatty(self):
        return True


def test_explicit_launcher_is_single_process_no_proxy_or_access_logs(monkeypatch):
    from app.main import app

    from app import local_demo

    output = PrivateTerminal()
    monkeypatch.setattr(local_demo.sys, "stdin", PrivateTerminal())
    monkeypatch.setattr(local_demo.sys, "stdout", output)
    run = Mock()
    monkeypatch.setattr("uvicorn.run", run)
    local_demo.main(["--origin", ORIGIN, "--pair"])
    assert run.call_args.kwargs == dict(
        host="127.0.0.1",
        port=8000,
        workers=1,
        reload=False,
        proxy_headers=False,
        forwarded_allow_ips="",
        access_log=False,
        ssl_certfile=None,
        ssl_keyfile=None,
    )
    assert output.getvalue().count("One-use local pairing code") == 1
    assert app.state.browser_sessions is None


@pytest.mark.parametrize(
    "arguments",
    [
        ["--origin", "http://0.0.0.0:8000", "--pair"],
        ["--origin", ORIGIN],
        ["--origin", "https://127.0.0.1:8443", "--pair"],
        ["--origin", ORIGIN, "--pair", "--workers", "2"],
    ],
)
def test_unsafe_launcher_configuration_never_starts_server(arguments, monkeypatch):
    from app import local_demo

    monkeypatch.setattr(local_demo.sys, "stdin", PrivateTerminal())
    monkeypatch.setattr(local_demo.sys, "stdout", PrivateTerminal())
    run = Mock()
    monkeypatch.setattr("uvicorn.run", run)
    with pytest.raises(SystemExit):
        local_demo.main(arguments)
    run.assert_not_called()


def test_launcher_refuses_redirected_secret_output(monkeypatch):
    from app import local_demo

    monkeypatch.setattr(local_demo.sys, "stdout", StringIO())
    run = Mock()
    monkeypatch.setattr("uvicorn.run", run)
    with pytest.raises(SystemExit):
        local_demo.main(["--origin", ORIGIN, "--pair"])
    run.assert_not_called()


@pytest.mark.parametrize(
    "content,status,code",
    [
        (b'{"pairing_code":"a","pairing_code":"b"}', 400, "DUPLICATE_JSON_FIELD"),
        (b'{"pairing_code":NaN}', 400, "MALFORMED_JSON"),
        (b'{"pairing_code":1e999}', 400, "MALFORMED_JSON"),
        (b"{", 400, "MALFORMED_JSON"),
        (b"\xff", 400, "MALFORMED_JSON"),
        (b"[]", 422, "INVALID_REQUEST"),
        (b"{}", 422, "INVALID_REQUEST"),
        (b'{"pairing_code":true}', 422, "INVALID_REQUEST"),
        (b'{"pairing_code":"a"}', 422, "INVALID_REQUEST"),
        (b'{"pairing_code":"' + b"!" * 43 + b'"}', 422, "INVALID_REQUEST"),
        (b'{"pairing_code":"' + b"a" * 32768 + b'"}', 413, "PAYLOAD_TOO_LARGE"),
        (json.dumps({"x": [[[[[[[[[[0]]]]]]]]]]}).encode(), 422, "INVALID_REQUEST"),
    ],
    ids=[
        "duplicate",
        "nan",
        "overflow",
        "malformed",
        "utf8",
        "array",
        "missing",
        "boolean",
        "short",
        "invalid-alphabet",
        "oversized",
        "depth",
    ],
)
def test_strict_bounded_json_and_redacted_errors(demo, content, status, code):
    _, store, _, client = demo
    _, csrf = bootstrap(client)
    issued = store.issue_pairing_code()
    response = client.post(
        PAIR, content=content, headers={"X-Ghost-CSRF": csrf, "Content-Type": "application/json"}
    )
    denied(response, status, code)
    assert issued.get_secret_value() not in response.text
    assert store._pairing is not None


@pytest.mark.parametrize(
    "headers",
    [
        {"Content-Type": "text/plain"},
        {"Content-Type": "application/x-www-form-urlencoded"},
        {"Content-Type": "application/json", "Content-Encoding": "gzip"},
    ],
)
def test_unsupported_media_never_consumes_code(demo, headers):
    _, store, _, client = demo
    _, csrf = bootstrap(client)
    issued = store.issue_pairing_code()
    denied(
        client.post(PAIR, content=b"{}", headers={**headers, "X-Ghost-CSRF": csrf}),
        415,
        "UNSUPPORTED_MEDIA_TYPE",
    )
    assert store._pairing is not None
    assert issued.get_secret_value() not in repr(store._pairing)


def test_header_and_query_limits_and_idempotency_header(demo):
    _, _, _, client = demo
    denied(client.get(SESSION, headers={"X-Large": "a" * 8192}), 413, "PAYLOAD_TOO_LARGE")
    denied(client.get(SESSION + "?owner=local-user"), 422, "INVALID_REQUEST")
    denied(
        client.get(SESSION, headers={"Idempotency-Key": "anything"}),
        400,
        "UNEXPECTED_IDEMPOTENCY_KEY",
    )
    denied(client.request("GET", SESSION, content=b"{}"), 422, "INVALID_REQUEST")


def test_csrf_tokens_are_bound_to_each_session_and_duplicate_headers_fail(demo):
    _, store, _, client = demo
    _, csrf = bootstrap(client)
    client.cookies.clear()
    _, other = bootstrap(client)
    assert csrf != other
    issued = store.issue_pairing_code()
    denied(pair(store, client, csrf, issued), 403, "CSRF_INVALID")
    response = client.post(
        PAIR,
        json={"pairing_code": issued.get_secret_value()},
        headers=[("X-Ghost-CSRF", other), ("X-Ghost-CSRF", other)],
    )
    denied(response, 403, "CSRF_INVALID")
    assert pair(store, client, other, issued).status_code == 200


def test_global_attempt_limit_bounds_peer_counters(demo):
    _, store, _, _ = demo
    for i in range(30):
        view, _, token = store.inspect(None)
        with pytest.raises(BrowserAuthError, match="LOGIN_FAILED"):
            store.pair(token, view.data.csrf_token, SecretStr("a" * 43), f"127.0.0.{i + 1}")
    view, _, token = store.inspect(None)
    with pytest.raises(BrowserAuthError, match="AUTH_RATE_LIMITED"):
        store.pair(token, view.data.csrf_token, SecretStr("a" * 43), "127.0.0.100")
    assert len(store._peers) == 30 and len(store._attempts) == 30


@pytest.mark.parametrize("reason", ["logout", "expiry", "restart"])
def test_response_lease_rechecked_before_private_bytes_leave(demo, reason):
    _, store, clock, _ = demo
    _, lease, token = store.inspect(None)
    messages = []

    async def inner(scope, receive, send):
        scope["browser_lease"] = (store, lease)
        if reason == "logout":
            view, _, _ = store.inspect(token)
            store.logout(token, view.data.csrf_token)
        elif reason == "expiry":
            clock.now += timedelta(seconds=120)
        else:
            store.invalidate_all()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"PRIVATE_RESPONSE_MARKER"})

    async def run():
        async def send(message):
            messages.append(message)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        await BrowserBoundary(inner)(
            {"type": "http", "path": SESSION, "method": "GET"}, receive, send
        )

    asyncio.run(run())
    assert messages[0]["status"] == 401
    assert b"PRIVATE_RESPONSE_MARKER" not in b"".join(m.get("body", b"") for m in messages)


def test_expiry_during_body_stream_cannot_pair(demo):
    app, store, clock, client = demo
    _, csrf = bootstrap(client)
    token = client.cookies.get("ghost_demo_session")
    code = store.issue_pairing_code()

    async def run():
        async def chunks():
            yield b'{"pairing_code":"'
            clock.now += timedelta(seconds=120)
            yield code.get_secret_value().encode() + b'"}'

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 50)), base_url=ORIGIN
        ) as browser:
            return await browser.post(
                PAIR,
                content=chunks(),
                headers={
                    "Origin": ORIGIN,
                    "Cookie": "ghost_demo_session=" + token,
                    "X-Ghost-CSRF": csrf,
                    "Content-Type": "application/json",
                },
            )

    denied(asyncio.run(run()), 401, "SESSION_EXPIRED")


def test_auth_does_not_create_users_operations_or_execute(client, monkeypatch):
    from app.main import app
    from app.models import GatewayOperation, User
    from app.services import controlled_execution, trusted_execution
    from sqlalchemy import func, select

    store = BrowserSessions(LocalDemoConfig(ORIGIN))
    monkeypatch.setattr(app.state, "browser_sessions", store, raising=False)
    blocked = Mock(side_effect=AssertionError("Protected execution forbidden"))
    for name in ("dispatch_simulated", "dispatch_document_read", "dispatch_email"):
        monkeypatch.setattr(trusted_execution, name, blocked)
    monkeypatch.setattr(controlled_execution.ControlledExecution, "resume", blocked)
    with TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 50)) as browser:
        browser.headers["Origin"] = ORIGIN
        _, csrf = bootstrap(browser)
        response = pair(store, browser, csrf)
        assert response.status_code == 200
        assert (
            browser.post(
                LOGOUT, headers={"X-Ghost-CSRF": response.json()["data"]["csrf_token"]}, json={}
            ).status_code
            == 204
        )
    from app.database import get_db

    with next(app.dependency_overrides[get_db]()) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 0
        assert db.scalar(select(func.count()).select_from(GatewayOperation)) == 0
    blocked.assert_not_called()
