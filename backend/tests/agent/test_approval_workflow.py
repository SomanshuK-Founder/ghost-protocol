"""Real A owner admission + isolated B SQLite checkpoints; no protected executors."""

import asyncio
import sqlite3

import pytest
from pydantic import SecretStr

from app.agent.approval_workflow import approval_workflow
from app.agent.execution_contracts import ActionBinding, ExecutionProvenance
from app.agent.gateway_protocol import ToolAction
from app.agent.http_gateway import InMemoryTaskCredential
from app.agent.integration_runtime import gateway_runtime
from app.agent.mock_model_provider import MockModelProvider
from app.agent.workflow_contracts import WorkflowError, resume_identity
from app.agent.workflow_transport import WorkflowControlClient
from tests.agent.test_fastapi_gateway_integration import backend as _backend

backend = _backend


async def pending(backend):
    task, token = backend.bootstrap(approval=True)
    model = MockModelProvider(
        output={
            "task_ref": task,
            "intent": "summarize_document",
            "proposed_actions": ["files.read"],
            "requires_external_action": True,
            "clarification_required": False,
        }
    )
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
            "PRIVATE_PROMPT_MARKER",
            (
                ActionBinding(
                    task_ref=task,
                    action=ToolAction.FILES_READ,
                    purpose="summarize_document",
                    arguments={"resource_id": "resource_http"},
                ),
            ),
        )
    return result, token


def control(backend):
    token = SecretStr(backend.command(command="owner").pop("token"))

    async def provider():
        return token

    return WorkflowControlClient(
        base_url="https://asgi.test", owner_credential_provider=provider, transport=backend
    ), token


def test_pause_restart_resume_safe_terminal_and_no_secrets(backend, tmp_path):
    async def run():
        client, owner = control(backend)
        result, agent = await pending(backend)
        path = tmp_path / "workflow.sqlite"
        async with approval_workflow(checkpoint_path=path, control=client) as workflow:
            binding = await workflow.pause(result)
            assert binding.phase == "PAUSED" and binding.checkpoint_id is not None
            assert await workflow.pause(result) == binding
        backend.command(
            command="owner_decide", approval_ref=binding.approval_ref, resolution="APPROVE"
        )
        async with approval_workflow(checkpoint_path=path, control=client) as restarted:
            resumed = await restarted.resume(binding.binding_ref)
            assert resumed.phase == "RESUMED"
            with pytest.raises(WorkflowError):
                await restarted.resume(binding.binding_ref)
        with sqlite3.connect(path) as db:
            raw = b"".join(
                bytes(v) if isinstance(v, bytes) else str(v).encode()
                for table in ("checkpoints", "writes")
                for row in db.execute(f"SELECT * FROM {table}")
                for v in row
            )
        for secret in (
            owner.get_secret_value(),
            agent.get_secret_value(),
            "PRIVATE_PROMPT_MARKER",
            "resource_http",
            "SMTP",
            "PRIVATE_BODY_MARKER",
        ):
            assert secret.encode() not in raw
        stats = backend.command(command="stats")
        assert stats["operations"] == len(stats["approvals"]) == 1 and stats["attempts"] == 0
        await client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("decision", ["REJECT", "REVOKE"])
def test_rejected_or_revoked_never_resumes(backend, tmp_path, decision):
    async def run():
        client, _ = control(backend)
        result, _ = await pending(backend)
        async with approval_workflow(
            checkpoint_path=tmp_path / "workflow.sqlite", control=client
        ) as workflow:
            binding = await workflow.pause(result)
            backend.command(
                command="owner_decide",
                approval_ref=binding.approval_ref,
                **({"revoke": True} if decision == "REVOKE" else {"resolution": "REJECT"}),
            )
            with pytest.raises(WorkflowError):
                await workflow.resume(binding.binding_ref)
        await client.aclose()

    asyncio.run(run())


def test_resume_with_no_approval_and_replayed_checkpoint(backend, tmp_path):
    async def run():
        client, _ = control(backend)
        result, _ = await pending(backend)
        async with approval_workflow(
            checkpoint_path=tmp_path / "workflow.sqlite", control=client
        ) as workflow:
            binding = await workflow.pause(result)
            with pytest.raises(WorkflowError):
                await workflow.resume(binding.binding_ref)
        # No local checkpoint is enough to fail before backend claim, even after owner approval.
        backend.command(
            command="owner_decide", approval_ref=binding.approval_ref, resolution="APPROVE"
        )
        async with approval_workflow(
            checkpoint_path=tmp_path / "empty.sqlite", control=client
        ) as workflow:
            with pytest.raises(WorkflowError):
                await workflow.resume(binding.binding_ref)
        await client.aclose()

    asyncio.run(run())


def test_restart_after_claim_does_not_reinvoke_node(backend, tmp_path):
    async def run():
        client, _ = control(backend)
        result, _ = await pending(backend)
        path = tmp_path / "workflow.sqlite"
        async with approval_workflow(checkpoint_path=path, control=client) as workflow:
            binding = await workflow.pause(result)
        backend.command(
            command="owner_decide", approval_ref=binding.approval_ref, resolution="APPROVE"
        )
        current = await client.call("get", binding_ref=binding.binding_ref)
        identity = resume_identity(current)
        await client.call("admit", identity, binding.binding_ref)
        await client.call("claim", identity, binding.binding_ref)
        async with approval_workflow(checkpoint_path=path, control=client) as workflow:
            with pytest.raises(WorkflowError, match="safely"):
                await workflow.resume(binding.binding_ref)
        assert (await client.call("get", binding_ref=binding.binding_ref)).phase == "RESUMING"
        await client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "channel,value",
    [
        ("__start__", {"private_prompt": "MARKER"}),
        ("binding", {"agent_credential": "MARKER"}),
        ("__resume__", {"id": {"body": "MARKER"}}),
        ("__error__", RuntimeError("PRIVATE_EXCEPTION_MARKER")),
        ("unknown", "MARKER"),
    ],
)
def test_saver_rejects_private_pending_writes(tmp_path, channel, value):
    async def run():
        async with approval_workflow(
            checkpoint_path=tmp_path / "workflow.sqlite", control=None
        ) as workflow:
            with pytest.raises(WorkflowError):
                await workflow._saver.aput_writes(
                    {
                        "configurable": {
                            "thread_id": "thread_test",
                            "checkpoint_ns": "",
                            "checkpoint_id": "checkpoint_test",
                        }
                    },
                    [(channel, value)],
                    "task_test",
                )

    asyncio.run(run())


def test_checkpoint_database_failure_does_not_register_pause(backend, tmp_path):
    async def run():
        client, _ = control(backend)
        result, _ = await pending(backend)
        async with approval_workflow(
            checkpoint_path=tmp_path / "workflow.sqlite", control=client
        ) as workflow:
            await workflow._saver.conn.execute("PRAGMA query_only=ON")
            with pytest.raises(sqlite3.OperationalError):
                await workflow.pause(result)
        stats = backend.command(command="stats")
        assert stats["operations"] == 1 and stats["attempts"] == 0
        await client.aclose()

    asyncio.run(run())


def test_concurrent_resume_one_claim(backend, tmp_path):
    async def run():
        client, _ = control(backend)
        result, _ = await pending(backend)
        async with approval_workflow(
            checkpoint_path=tmp_path / "workflow.sqlite", control=client
        ) as workflow:
            binding = await workflow.pause(result)
            backend.command(
                command="owner_decide", approval_ref=binding.approval_ref, resolution="APPROVE"
            )
            results = await asyncio.gather(
                *(workflow.resume(binding.binding_ref) for _ in range(8)), return_exceptions=True
            )
            assert sum(getattr(row, "phase", None) == "RESUMED" for row in results) == 1
            assert all(
                isinstance(row, WorkflowError) or getattr(row, "phase", None) == "RESUMED"
                for row in results
            )
        assert backend.command(command="stats")["operations"] == 1
        await client.aclose()

    asyncio.run(run())


def test_agent_credentials_cannot_select_owner_transport(backend):
    async def run():
        _, agent = await pending(backend)

        async def credential():
            return agent

        client = WorkflowControlClient(
            base_url="https://asgi.test", owner_credential_provider=credential, transport=backend
        )
        before = len(backend.command(command="stats")["requests"])
        with pytest.raises(WorkflowError):
            await client.call("prepare", {})
        assert len(backend.command(command="stats")["requests"]) == before
        await client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "field", ["api_key", "agent_credential", "owner_credential", "body", "content", "result"]
)
def test_checkpoint_start_schema_rejects_sensitive_fields(tmp_path, field):
    async def run():
        async with approval_workflow(
            checkpoint_path=tmp_path / "workflow.sqlite", control=None
        ) as workflow:
            with pytest.raises(WorkflowError):
                await workflow._saver.aput_writes(
                    {
                        "configurable": {
                            "thread_id": "thread_test",
                            "checkpoint_ns": "",
                            "checkpoint_id": "checkpoint_test",
                        }
                    },
                    [("__start__", {"binding": {}, "phase": "PAUSED", field: "PRIVATE_MARKER"})],
                    "task_test",
                )

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["checkpoint_after_claim", "completion_ack"])
def test_uncertain_resume_restart_never_replays(backend, tmp_path, failure):
    async def run():
        client, _ = control(backend)
        result, _ = await pending(backend)
        path = tmp_path / "workflow.sqlite"
        async with approval_workflow(checkpoint_path=path, control=client) as workflow:
            binding = await workflow.pause(result)
            backend.command(
                command="owner_decide", approval_ref=binding.approval_ref, resolution="APPROVE"
            )
            if failure == "checkpoint_after_claim":
                await workflow._saver.conn.execute("PRAGMA query_only=ON")
                expected = sqlite3.OperationalError
            else:
                original = client.call

                async def fail_complete(command, *args, **kwargs):
                    if command == "complete":
                        raise WorkflowError("WORKFLOW_UNAVAILABLE")
                    return await original(command, *args, **kwargs)

                client.call = fail_complete
                expected = WorkflowError
            with pytest.raises(expected):
                await workflow.resume(binding.binding_ref)
        async with approval_workflow(checkpoint_path=path, control=client) as restarted:
            with pytest.raises(WorkflowError):
                await restarted.resume(binding.binding_ref)
        assert (await client.call("get", binding_ref=binding.binding_ref)).phase == "RESUMING"
        assert backend.command(command="stats")["attempts"] == 0
        await client.aclose()

    asyncio.run(run())
