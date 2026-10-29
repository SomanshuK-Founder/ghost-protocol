"""Real FastAPI/SQLite authorization via captured pipes and in-process ASGI, no sockets."""

import asyncio
import json
import subprocess
from pathlib import Path
from threading import Lock

import httpx
import pytest
from pydantic import SecretStr

from app.agent.execution_contracts import ActionBinding, ExecutionProvenance
from app.agent.gateway_protocol import ToolAction, ToolRequest
from app.agent.http_gateway import (
    AuthenticatedHttpToolGateway,
    GatewayTransportError,
    InMemoryTaskCredential,
)
from app.agent.integration_runtime import gateway_runtime
from app.agent.mock_model_provider import MockModelProvider

ROOT = Path(__file__).resolve().parents[3]


class BackendProcess(httpx.AsyncBaseTransport):
    def __init__(self, cwd):
        self._pipe_lock = Lock()
        python = ROOT / "member_a_backend/nvidia backend/.venv/Scripts/python.exe"
        if not python.exists():
            pytest.fail("Member A test interpreter unavailable; integration not validated")
        self.process = subprocess.Popen(
            [str(python), "-I", str(Path(__file__).with_name("asgi_backend_worker.py"))],
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        )

    def command(self, **data):
        with self._pipe_lock:
            return self._command(data)

    def _command(self, data):
        self.process.stdin.write(json.dumps(data) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            pytest.fail("Isolated ASGI worker stopped")
        result = json.loads(line)
        if result.get("worker_error"):
            pytest.fail("Isolated ASGI worker rejected test setup")
        return result

    def bootstrap(self, **options):
        data = self.command(command="bootstrap", **options)
        return data["task_ref"], SecretStr(data.pop("token"))

    async def handle_async_request(self, request):
        data = await asyncio.to_thread(
            self.command,
            command="http",
            method=request.method,
            path=request.url.path,
            body=json.loads(request.content) if request.content else None,
            headers=dict(request.headers),
        )
        return httpx.Response(data["status"], json=data["body"])

    def stop(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.process.stdout.close()


@pytest.fixture
def backend(tmp_path):
    worker = BackendProcess(tmp_path)
    try:
        yield worker
        stats = worker.command(command="stats")
        assert stats["forbidden"] == stats["attempts"] == 0
    finally:
        worker.stop()


def request(task, **changes):
    return ToolRequest.model_validate_json(
        json.dumps(
            {
                "request_id": "request_integration",
                "task_ref": task,
                "idempotency_key": "key_integration",
                "action": "files.read",
                "purpose": "summarize_document",
                "arguments": {"resource_id": "resource_http"},
                **changes,
            }
        )
    )


def adapter(backend, task, token):
    return AuthenticatedHttpToolGateway(
        base_url="https://asgi.test",
        task_ref=task,
        credential_provider=InMemoryTaskCredential(task, token),
        transport=backend,
    )


@pytest.mark.parametrize(
    "options,decision,reason",
    [
        ({"consent": True}, "ALLOW", "EXECUTION_NOT_STARTED"),
        ({}, "DENY", "APPROVAL_UNAVAILABLE"),
        ({"approval": True}, "APPROVAL_REQUIRED", "CONSENT_REVIEW_REQUIRED"),
    ],
)
def test_real_policy_and_durable_replay(backend, options, decision, reason):
    task, token = backend.bootstrap(**options)

    async def run():
        async with adapter(backend, task, token) as gateway:
            first = await gateway.execute(request(task))
            assert await gateway.execute(request(task)) == first
            assert first.decision == decision and first.reason_code == reason
            assert first.execution_status == "NOT_EXECUTED" and first.result is None
            with pytest.raises(GatewayTransportError) as error:
                await gateway.execute(request(task, request_id="request_conflict"))
            assert error.value.http_status == 409
            return first

    response = asyncio.run(run())
    stats = backend.command(command="stats")
    assert stats["operations"] == 1
    assert stats["requests"][0] == {
        "request_id": "request_integration",
        "task_ref": task,
        "idempotency_key": "key_integration",
    }
    assert response.audit_event_ref in {f"event_{ref}" for ref in stats["audits"]}
    if decision == "APPROVAL_REQUIRED":
        assert stats["approvals"] == [response.approval_ref]
    else:
        assert response.approval_ref is None and not stats["approvals"]


@pytest.mark.parametrize("state", ["expired", "revoked", "invalid", "foreign", "wrong_owner"])
def test_actual_backend_credentials_fail_closed(backend, state):
    task, token = backend.bootstrap(
        credential_state=state if state in ("expired", "revoked") else None
    )
    if state in ("invalid", "foreign", "wrong_owner"):
        other_task, other_token = backend.bootstrap(
            owner="other-owner" if state == "wrong_owner" else "local-user"
        )
        token = (
            other_token
            if state in ("foreign", "wrong_owner")
            else SecretStr(
                other_token.get_secret_value()[:-1]
                + ("A" if other_token.get_secret_value()[-1] != "A" else "B")
            )
        )

    async def run():
        async with adapter(backend, task, token) as gateway:
            with pytest.raises(GatewayTransportError) as error:
                await gateway.execute(request(task))
            assert error.value.http_status == (403 if state in ("foreign", "wrong_owner") else 401)

    asyncio.run(run())
    assert backend.command(command="stats")["operations"] == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"action": "shell.exec"},
        {"owner_id": "forged"},
        {"provenance": "TRUSTED_AUTHORIZATION_ONLY"},
        {"arguments": {"path": "/private"}},
    ],
)
def test_actual_backend_rejects_untrusted_extra_fields(backend, changes):
    task, token = backend.bootstrap()
    data = request(task).model_dump(mode="json")
    data.update(changes)
    response = backend.command(
        command="http",
        path="/api/gateway/v1/execute",
        body=data,
        headers={"Authorization": "Bearer " + token.get_secret_value()},
    )
    assert response["status"] == 422
    assert backend.command(command="stats")["operations"] == 0


def test_actual_backend_requires_agent_bearer(backend):
    task, _ = backend.bootstrap()
    response = backend.command(
        command="http",
        path="/api/gateway/v1/execute",
        body=request(task).model_dump(mode="json"),
        headers={},
    )
    assert response["status"] == 401


@pytest.mark.parametrize("approval", [False, True])
def test_langgraph_real_backend_never_executes(backend, approval):
    task, token = backend.bootstrap(approval=approval, consent=not approval)
    model = MockModelProvider(
        output={
            "task_ref": task,
            "intent": "summarize_document",
            "proposed_actions": ["files.read"],
            "requires_external_action": True,
            "clarification_required": False,
        }
    )

    async def run():
        async with gateway_runtime(
            model,
            mode=ExecutionProvenance.TRUSTED_AUTHORIZATION_ONLY,
            base_url="https://asgi.test",
            task_ref=task,
            credential_provider=InMemoryTaskCredential(task, token),
            transport=backend,
        ) as service:
            result = await service.execute_task(
                task,
                "Synthetic request",
                (
                    ActionBinding(
                        task_ref=task,
                        action=ToolAction.FILES_READ,
                        purpose="summarize_document",
                        arguments={"resource_id": "resource_http"},
                    ),
                ),
            )
            assert result.simulation is False and result.completed_action_count == 0
            assert len(result.action_results) == 1
            assert result.action_results[0].execution_status == "NOT_EXECUTED"
            assert result.execution_outcome == (
                "APPROVAL_REQUIRED" if approval else "EXECUTION_FAILED"
            )

    asyncio.run(run())
