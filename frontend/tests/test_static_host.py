import asyncio
import importlib.util
from pathlib import Path

import httpx
import pytest
from starlette.responses import PlainTextResponse

spec = importlib.util.spec_from_file_location(
    "static_host", Path(__file__).resolve().parents[1] / "scripts/serve.py"
)
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


@pytest.fixture
def application(tmp_path):
    (tmp_path / "index.html").write_text(
        "<html><script>self.synthetic = true;</script><body>Local UI</body></html>",
        encoding="utf-8",
    )
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks/index.html").write_text("Tasks", encoding="utf-8")
    (tmp_path / "tasks/__next.tasks").mkdir()
    (tmp_path / "tasks/__next.tasks/__PAGE__.txt").write_text("segment", encoding="utf-8")

    async def public(scope, receive, send):
        assert scope["server"] == ("127.0.0.1", 3000)
        await PlainTextResponse("backend", status_code=418)(scope, receive, send)

    return host.StaticApplication(public, tmp_path)


def call(application, method="GET", path="/", headers=None):
    async def request():
        transport = httpx.ASGITransport(app=application, client=("127.0.0.1", 12345))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:3000"
        ) as client:
            return await client.request(method, path, headers=headers)

    return asyncio.run(request())


def test_static_html_has_script_hashes_and_security_headers(application):
    response = call(application)
    assert response.status_code == 200
    assert "Local UI" in response.text
    csp = response.headers["content-security-policy"]
    assert "script-src 'self' 'sha256-" in csp
    assert "script-src 'self' 'unsafe-inline'" not in csp
    assert "connect-src 'self'" in csp
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


@pytest.mark.parametrize(
    "path",
    [
        "/api/app/v1/session",
        "/api/gateway/v1/execute",
        "/api",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/health",
    ],
)
def test_application_and_private_routes_are_delegated_unchanged(application, path):
    assert call(application, path=path).status_code == 418


def test_static_route_navigation(application):
    assert call(application, path="/tasks/").text == "Tasks"
    assert call(application, method="HEAD").content == b""
    assert call(application, path="/missing/").status_code == 404
    assert call(application, method="POST").status_code == 405
    assert call(application, path="/tasks/__next.tasks.__PAGE__.txt").text == "segment"


def test_wrong_host_is_rejected(application):
    assert call(application, headers={"Host": "foreign.test"}).status_code == 403


@pytest.mark.parametrize("path", ["/%2e%2e/AGENTS.md", "/%2e%2e%5cAGENTS.md"])
def test_traversal_cannot_read_repository_files(application, path):
    assert call(application, path=path).status_code == 403
