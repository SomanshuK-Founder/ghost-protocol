"""v1.3 isolated ASGI composition plus strict hostile-transport tests."""

import asyncio
import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.agent.approval_workflow import approval_workflow
from app.agent.controlled_contracts import ControlledExecutionResult
from app.agent.controlled_execution import ControlledExecutionClient
from app.agent.execution_contracts import ActionBinding, ExecutionProvenance
from app.agent.gateway_protocol import ToolAction, ToolRequest
from app.agent.http_gateway import GatewayTransportError, InMemoryTaskCredential
from app.agent.integration_runtime import gateway_runtime
from app.agent.mock_model_provider import MockModelProvider
from app.agent.orchestration import build_tool_request
from app.agent.workflow_contracts import WorkflowSnapshot
from tests.agent.test_approval_workflow import control
from tests.agent.test_fastapi_gateway_integration import BackendProcess


@pytest.fixture
def worker(tmp_path):
    backend = BackendProcess(tmp_path)
    try:
        yield backend
        assert backend.command(command="stats")["forbidden"] == 0
    finally:
        backend.stop()


@pytest.mark.parametrize("action", ["files.read", "email.draft", "email.send"])
def test_actual_graph_pause_owner_resume_then_separate_execution(worker, tmp_path, action):
    async def run():
        worker.command(command="enable_controlled")
        task, agent = worker.bootstrap(
            approval=True, **({"email_action": action} if action.startswith("email.") else {})
        )
        arguments = (
            worker.command(command="email_profile")
            if action.startswith("email.")
            else {"resource_id": "resource_http"}
        )
        purpose = "prepare_email" if action.startswith("email.") else "summarize_document"
        binding = ActionBinding(
            task_ref=task, action=ToolAction(action), purpose=purpose, arguments=arguments
        )
        original = build_tool_request(task, 0, ToolAction(action), binding)
        model = MockModelProvider(
            output={
                "task_ref": task,
                "intent": purpose,
                "proposed_actions": [action],
                "requires_external_action": True,
                "clarification_required": False,
            }
        )
        client, owner = control(worker)
        path = tmp_path / "safe-workflow.sqlite"
        async with gateway_runtime(
            model,
            mode=ExecutionProvenance.TRUSTED_AUTHORIZATION_ONLY,
            base_url="https://asgi.test",
            task_ref=task,
            credential_provider=InMemoryTaskCredential(task, agent),
            transport=worker,
        ) as orchestrator:
            result = await orchestrator.execute_task(task, "PRIVATE_PROMPT_MARKER", (binding,))
        async with approval_workflow(checkpoint_path=path, control=client) as workflow:
            paused = await workflow.pause(result)
        worker.command(
            command="owner_decide", approval_ref=paused.approval_ref, resolution="APPROVE"
        )
        async with ControlledExecutionClient(
            enabled=True,
            base_url="https://asgi.test",
            task_ref=task,
            credential_provider=InMemoryTaskCredential(task, agent),
            transport=worker,
        ) as execution:
            observed = await execution.status(paused)
            assert observed.resume_ref is not None
            with pytest.raises(GatewayTransportError):
                await execution.execute_completed(
                    paused,
                    original,
                    resume_ref=observed.resume_ref,
                    expected_version="version_http",
                )
            assert worker.command(command="stats")["attempts"] == 0
            async with approval_workflow(checkpoint_path=path, control=client) as workflow:
                complete = await workflow.resume(paused.binding_ref)
            assert complete.phase == "RESUMED"
            assert worker.command(command="stats")["attempts"] == 0
            first = await execution.execute_completed(
                complete, original, resume_ref=observed.resume_ref, expected_version="version_http"
            )
            assert first.execution_status == "SUCCEEDED" and not first.replayed
            again = await execution.execute_completed(
                complete, original, resume_ref=observed.resume_ref, expected_version="version_http"
            )
            assert again == first.model_copy(update={"replayed": True})
        stats = worker.command(command="stats")
        assert stats["attempts"] == stats["operations"] == len(stats["approvals"]) == 1
        assert stats["fake_smtp_calls"] == (1 if action == "email.send" else 0)
        with sqlite3.connect(path) as db:
            raw = b"".join(
                str(v).encode() if not isinstance(v, bytes) else v
                for table in ("checkpoints", "writes")
                for row in db.execute("SELECT * FROM " + table)
                for v in row
            )
        for marker in (
            agent.get_secret_value(),
            owner.get_secret_value(),
            "PRIVATE_PROMPT_MARKER",
            "PRIVATE_DOCUMENT_MARKER",
            arguments.get("body", "PRIVATE_BODY_MARKER"),
        ):
            assert marker.encode() not in raw
        await client.aclose()

    asyncio.run(run())


def fixture_values():
    request = ToolRequest(
        request_id="request_one",
        task_ref="task_one",
        idempotency_key="key_one",
        action=ToolAction.FILES_READ,
        purpose="summarize_document",
        arguments={"resource_id": "resource_one"},
    )
    wire = dict(
        version="gw-wire-v1",
        owner_id="owner_one",
        task_ref=request.task_ref,
        action="files.read",
        purpose=request.purpose,
        arguments=request.arguments.model_dump(mode="json"),
    )
    digest = hashlib.sha256(
        json.dumps(wire, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    snapshot = WorkflowSnapshot(
        binding_ref="wf_one",
        owner_ref="owner_one",
        task_ref=request.task_ref,
        operation_ref="op_one",
        approval_ref="approval_one",
        request_id=request.request_id,
        idempotency_key=request.idempotency_key,
        canonical_request_digest=digest,
        thread_id="wfthread_" + "a" * 32,
        checkpoint_id=str(uuid4()),
        workflow_version="approval-workflow-v1",
        registration_authorization_version=0,
        authorization_version=1,
        admitted_authorization_version=1,
        phase="RESUMED",
        expires_at=datetime.now(UTC) + timedelta(seconds=30),
        audit_event_ref="event_one",
    )
    result = dict(
        contract_version="gw-execution-v1.3",
        task_ref=request.task_ref,
        operation_ref=snapshot.operation_ref,
        attempt_ref="attempt_one",
        workflow_ref=snapshot.binding_ref,
        request_id=request.request_id,
        idempotency_key=request.idempotency_key,
        audit_event_ref="event_two",
        decision="ALLOW",
        admission="ADMITTED",
        execution_status="SUCCEEDED",
        mode="SIMULATED",
        effect="SIMULATED",
        result={
            "resource_id": "resource_one",
            "version_ref": "version_one",
            "content_type": "text/plain",
            "text": "SIMULATED: no document was read.",
        },
        sanitized_error_code=None,
        replayed=False,
    )
    return request, snapshot, result


def client_for(handler, **changes):
    provider = InMemoryTaskCredential(
        "task_one", SecretStr("gpa_cred_" + "a" * 32 + "." + "b" * 43)
    )
    return ControlledExecutionClient(
        enabled=True,
        base_url="https://backend.test",
        task_ref="task_one",
        credential_provider=provider,
        transport=httpx.MockTransport(handler),
        **changes,
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("contract_version", "v2"),
        ("request_id", "foreign"),
        ("idempotency_key", "foreign"),
        ("task_ref", "foreign"),
        ("operation_ref", "foreign"),
        ("workflow_ref", "foreign"),
        ("decision", "DENY"),
        ("admission", "REJECTED"),
        ("execution_status", "NOT_EXECUTED"),
        ("mode", "SYNTHETIC_READ"),
        ("mode", "MAILPIT_SEND"),
        ("effect", "REAL_EMAIL"),
        ("replayed", "true"),
        ("sanitized_error_code", "PRIVATE_MARKER"),
        ("audit_event_ref", None),
        ("extra", "model_provenance"),
    ],
)
def test_invalid_envelope_and_identity_fail_closed(field, value):
    request, snapshot, result = fixture_values()
    result[field] = value
    calls = []

    def handler(http):
        calls.append(http)
        return httpx.Response(200, json=result)

    async def run():
        async with client_for(handler) as client:
            with pytest.raises(GatewayTransportError):
                await client.execute_completed(
                    snapshot, request, resume_ref="resume_one", expected_version="version_one"
                )

    asyncio.run(run())
    assert len(calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        "raw_text",
        "wrong_resource",
        "wrong_version",
        "extra_result",
        "missing_result",
        "wrong_result_type",
    ],
)
def test_result_category_confidentiality(change):
    request, snapshot, result = fixture_values()
    if change == "raw_text":
        result["result"]["text"] = "PRIVATE_DOCUMENT_MARKER"
    elif change == "wrong_resource":
        result["result"]["resource_id"] = "foreign"
    elif change == "wrong_version":
        result["result"]["version_ref"] = "foreign"
    elif change == "extra_result":
        result["result"]["credential"] = "PRIVATE_MARKER"
    elif change == "missing_result":
        result["result"] = None
    else:
        result["result"] = {"receipt_ref": "receipt_one", "submission_state": "ACCEPTED"}

    async def run():
        async with client_for(lambda _: httpx.Response(200, json=result)) as client:
            with pytest.raises(GatewayTransportError, match="could not be completed"):
                await client.execute_completed(
                    snapshot, request, resume_ref="resume_one", expected_version="version_one"
                )

    asyncio.run(run())


@pytest.mark.parametrize("status", [301, 302, 307, 308, 401, 403, 409, 410, 429, 500, 503])
def test_http_errors_never_retry(status):
    request, snapshot, _ = fixture_values()
    calls = []

    def handler(http):
        calls.append(http)
        return httpx.Response(
            status,
            headers={"Location": "https://external.invalid"},
            json={
                "error_code": {
                    401: "AUTH_INVALID",
                    403: "ACTION_DISABLED",
                    409: "OPERATION_IN_PROGRESS",
                    410: "RESULT_EXPIRED",
                    429: "CAPACITY_EXCEEDED",
                    500: "INTERNAL_ERROR",
                    503: "GATEWAY_UNAVAILABLE",
                }.get(status, "redirect"),
                "execution_uncertain": True,
                "message": "PRIVATE_ERROR_MARKER",
                "correlation_ref": "http_one",
                "request_id": request.request_id,
                "audit_event_ref": None,
            },
        )

    async def run():
        async with client_for(handler) as client:
            with pytest.raises(GatewayTransportError) as exc:
                await client.execute_completed(
                    snapshot, request, resume_ref="resume_one", expected_version="version_one"
                )
            assert "PRIVATE_ERROR_MARKER" not in str(exc.value)
            if status >= 400:
                assert exc.value.http_status == status

    asyncio.run(run())
    assert len(calls) == 1


@pytest.mark.parametrize(
    "failure", ["timeout", "disconnect", "invalid_json", "duplicate_fields", "oversize"]
)
def test_transport_failure_sanitized_no_retry(failure):
    request, snapshot, _ = fixture_values()
    calls = []

    def handler(http):
        calls.append(http)
        if failure == "timeout":
            raise httpx.ReadTimeout("PRIVATE_MARKER")
        if failure == "disconnect":
            raise httpx.ConnectError("PRIVATE_MARKER")
        return httpx.Response(
            200,
            content={
                "invalid_json": b"{",
                "duplicate_fields": b'{"x":1,"x":2}',
                "oversize": b"x" * 262145,
            }[failure],
            headers={"content-type": "application/json"},
        )

    async def run():
        async with client_for(handler) as client:
            with pytest.raises(GatewayTransportError) as exc:
                await client.execute_completed(
                    snapshot, request, resume_ref="resume_one", expected_version="version_one"
                )
            assert exc.value.execution_uncertain and "PRIVATE_MARKER" not in str(exc.value)

    asyncio.run(run())
    assert len(calls) == 1


@pytest.mark.parametrize(
    "change", ["task", "purpose", "payload", "key", "request", "phase", "hint", "version"]
)
def test_local_identity_cannot_change_approved_proposal(change):
    request, snapshot, _ = fixture_values()
    calls = []
    hint = "resume_one"
    version = "version_one"
    if change == "task":
        snapshot = snapshot.model_copy(update={"task_ref": "foreign"})
    elif change == "purpose":
        request = request.model_copy(update={"purpose": "answer_question"})
    elif change == "payload":
        request = request.model_copy(
            update={"arguments": request.arguments.model_copy(update={"resource_id": "foreign"})}
        )
    elif change == "key":
        request = request.model_copy(update={"idempotency_key": "foreign"})
    elif change == "request":
        request = request.model_copy(update={"request_id": "foreign"})
    elif change == "phase":
        snapshot = snapshot.model_copy(update={"phase": "PAUSED"})
    elif change == "hint":
        hint = "../../escape"
    else:
        version = None

    async def run():
        async with client_for(lambda http: calls.append(http)) as client:
            with pytest.raises(GatewayTransportError):
                await client.execute_completed(
                    snapshot, request, resume_ref=hint, expected_version=version
                )

    asyncio.run(run())
    assert not calls


def test_unknown_envelope_is_not_success_and_never_automatically_retried():
    request, snapshot, result = fixture_values()
    calls = []
    result.update(execution_status="UNKNOWN", result=None, sanitized_error_code="SIMULATED_UNKNOWN")

    def handler(http):
        calls.append(http)
        return httpx.Response(200, json=result)

    async def run():
        async with client_for(handler) as client:
            observed = await client.execute_completed(
                snapshot, request, resume_ref="resume_one", expected_version="version_one"
            )
            assert observed.execution_status == "UNKNOWN" and observed.result is None

    asyncio.run(run())
    assert len(calls) == 1


def test_explicit_mode_and_fixed_origin_required():
    for enabled in (False, None, "true", 1):
        with pytest.raises(ValueError):
            ControlledExecutionClient(enabled=enabled)
    for origin in (
        "http://remote.test",
        "https://user:password@host.test",
        "https://host.test/path",
    ):
        with pytest.raises(ValueError):
            ControlledExecutionClient(
                enabled=True,
                base_url=origin,
                task_ref="task_one",
                credential_provider=InMemoryTaskCredential("task_one", None),
            )


@pytest.mark.parametrize(
    "field", ["result", "text", "body", "agent_credential", "owner_credential"]
)
def test_execution_envelope_does_not_expand_checkpoint_schema(field):
    _, snapshot, _ = fixture_values()
    with pytest.raises(ValidationError):
        WorkflowSnapshot.model_validate({**snapshot.model_dump(), field: "PRIVATE_MARKER"})


def test_public_contract_schema_unchanged_and_result_separate():
    from app.agent.gateway_protocol import ToolResponse

    assert set(ToolRequest.model_fields) == {
        "request_id",
        "task_ref",
        "action",
        "purpose",
        "arguments",
        "idempotency_key",
    }
    assert set(ToolResponse.model_fields) == {
        "request_id",
        "decision",
        "execution_status",
        "reason_code",
        "approval_ref",
        "result",
        "audit_event_ref",
    }
    _, _, result = fixture_values()
    assert ControlledExecutionResult.model_validate(result).mode == "SIMULATED"


def test_real_backend_process_restart_preserves_attempt_without_resend(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOST_TEST_DURABLE_WORKER", "1")
    backend = BackendProcess(tmp_path)

    async def run():
        nonlocal backend
        backend.command(command="enable_controlled")
        task, token = backend.bootstrap(approval=True, email_action="email.send")
        arguments = backend.command(command="email_profile")
        proposed = ActionBinding(
            task_ref=task,
            action=ToolAction.EMAIL_SEND,
            purpose="prepare_email",
            arguments=arguments,
        )
        request = build_tool_request(task, 0, ToolAction.EMAIL_SEND, proposed)
        model = MockModelProvider(
            output={
                "task_ref": task,
                "intent": "prepare_email",
                "proposed_actions": ["email.send"],
                "requires_external_action": True,
                "clarification_required": False,
            }
        )
        owner, _ = control(backend)
        async with gateway_runtime(
            model,
            mode=ExecutionProvenance.TRUSTED_AUTHORIZATION_ONLY,
            base_url="https://asgi.test",
            task_ref=task,
            credential_provider=InMemoryTaskCredential(task, token),
            transport=backend,
        ) as planning:
            result = await planning.execute_task(task, "PRIVATE_PROMPT_MARKER", (proposed,))
        async with approval_workflow(
            checkpoint_path=tmp_path / "workflow.sqlite", control=owner
        ) as workflow:
            binding = await workflow.pause(result)
            backend.command(
                command="owner_decide", approval_ref=binding.approval_ref, resolution="APPROVE"
            )
            binding = await workflow.resume(binding.binding_ref)
        async with ControlledExecutionClient(
            enabled=True,
            base_url="https://asgi.test",
            task_ref=task,
            credential_provider=InMemoryTaskCredential(task, token),
            transport=backend,
        ) as execution:
            hint = (await execution.status(binding)).resume_ref
            original = await execution.execute_completed(binding, request, resume_ref=hint)
        assert backend.command(command="stats")["fake_smtp_calls"] == 1
        await owner.aclose()
        backend.stop()
        backend = BackendProcess(tmp_path)
        before = backend.command(command="stats")
        assert before["attempts"] == 1 and before["fake_smtp_calls"] == 0
        backend.command(command="enable_controlled")
        async with ControlledExecutionClient(
            enabled=True,
            base_url="https://asgi.test",
            task_ref=task,
            credential_provider=InMemoryTaskCredential(task, token),
            transport=backend,
        ) as execution:
            replay = await execution.execute_completed(binding, request, resume_ref=hint)
        assert replay == original.model_copy(update={"replayed": True})
        assert backend.command(command="stats")["fake_smtp_calls"] == 0

    try:
        asyncio.run(run())
    finally:
        if backend.process.poll() is None:
            backend.stop()
