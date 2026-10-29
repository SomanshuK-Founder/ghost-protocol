"""Approved Step 39 local-service driver; invoked inside the isolated runner only."""

import asyncio
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from threading import Lock

BACKEND_ENV = dict(os.environ)
for key in (
    "MYSQL_PASSWORD",
    "DATABASE_URL",
    "API_BEARER_TOKEN",
    "NEBIUS_API_KEY",
    "OPENAI_API_KEY",
):
    os.environ.pop(key, None)
sys.path.insert(0, "/workspace/backend")

import httpx  # noqa: E402
from pydantic import SecretStr  # noqa: E402

from app.agent.approval_workflow import approval_workflow  # noqa: E402
from app.agent.controlled_execution import ControlledExecutionClient  # noqa: E402
from app.agent.execution_contracts import ActionBinding, ExecutionProvenance  # noqa: E402
from app.agent.gateway_protocol import ToolAction, ToolRequest  # noqa: E402
from app.agent.http_gateway import InMemoryTaskCredential  # noqa: E402
from app.agent.integration_runtime import gateway_runtime  # noqa: E402
from app.agent.mock_model_provider import MockModelProvider  # noqa: E402
from app.agent.orchestration import build_tool_request  # noqa: E402
from app.agent.workflow_contracts import WorkflowSnapshot  # noqa: E402
from app.agent.workflow_transport import WorkflowControlClient  # noqa: E402
from tests.agent.integrated_demo import SCENARIOS, checkpoint_clean, run_scenario  # noqa: E402

STORAGE = Path("/checkpoints")
WORKERS = []
FORBIDDEN = []


def denied(*args, **kwargs):
    FORBIDDEN.append(True)
    raise RuntimeError("No network transport in planning process")


socket.getaddrinfo = socket.create_connection = denied
socket.socket.connect = socket.socket.connect_ex = denied
httpx.HTTPTransport.handle_request = httpx.AsyncHTTPTransport.handle_async_request = denied


class Worker(httpx.AsyncBaseTransport):
    def __init__(self, directory):
        self.lock = Lock()
        self.context = {}
        self.directory = Path(directory)
        self.directory.mkdir(exist_ok=True)
        self.start()
        self.initial_captures = self.command(command="captures")["captures"]
        WORKERS.append(self)

    def start(self):
        self.log = (self.directory / ("application-" + os.urandom(5).hex() + ".log")).open("w")
        self.process = subprocess.Popen(
            [sys.executable, "/workspace/backend/tests/agent/demo_runtime_guard.py", "bridge"],
            cwd="/workspace/member_a_backend/nvidia backend",
            env=BACKEND_ENV,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log,
            text=True,
            encoding="utf-8",
        )
        while True:
            line = self.process.stdout.readline()
            assert line, "Runtime worker did not initialize"
            value = json.loads(line)
            if value.get("ready"):
                break

    def command(self, **payload):
        if payload["command"] in ("stats", "demo_inspect"):
            payload["task_ref"] = self.context["task"]
        with self.lock:
            self.process.stdin.write(json.dumps(payload) + "\n")
            self.process.stdin.flush()
            value = json.loads(self.process.stdout.readline())
        assert "worker_error" not in value, "Runtime worker rejected validation"
        if payload["command"] == "stats":
            value.update(
                captures_before=self.initial_captures,
                captures_after=self.command(command="captures")["captures"],
            )
            self.last_stats = value.copy()
        if payload["command"] == "demo_inspect":
            value["verified_messages"] = value["verified_messages_total"] - self.initial_captures
        return value

    def bootstrap(self, **options):
        value = self.command(command="bootstrap", **options)
        self.context.update(task=value["task_ref"], agent=SecretStr(value.pop("token")))
        self.before_stats = self.command(command="stats").copy()
        return self.context["task"], self.context["agent"]

    async def handle_async_request(self, request):
        body = json.loads(request.content) if request.content else None
        value = await asyncio.to_thread(
            self.command,
            command="http",
            method=request.method,
            path=request.url.path,
            headers=dict(request.headers),
            body=body,
        )
        if value["status"] == 200:
            if request.method == "GET" and "/operations/" in request.url.path:
                if value["body"].get("resume_ref"):
                    self.context["hint"] = value["body"]["resume_ref"]
            if request.url.path.endswith("/complete"):
                self.context["binding"] = WorkflowSnapshot.model_validate_json(
                    json.dumps(value["body"])
                )
        if request.url.path == "/api/gateway/v1/execute":
            self.context["original"] = ToolRequest.model_validate_json(json.dumps(body))
        return httpx.Response(value["status"], json=value["body"])

    def stop(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            tail = self.process.stdout.read()
            self.process.wait(timeout=10)
            assert (
                self.process.returncode == 0 and "Forbidden network/tool/SMTP attempts: 0" in tail
            )
        self.process.stdout.close()
        self.log.close()


async def replay(worker):
    context = worker.context
    async with ControlledExecutionClient(
        enabled=True,
        base_url="https://asgi.test",
        task_ref=context["task"],
        credential_provider=InMemoryTaskCredential(context["task"], context["agent"]),
        transport=worker,
    ) as client:
        value = await client.execute_completed(
            context["binding"],
            context["original"],
            resume_ref=context["hint"],
            expected_version="version_http",
        )
    assert value.replayed
    stats = worker.command(command="stats")
    assert stats["attempts"] == 1
    return {
        "task_ref": context["task"],
        "operation_ref": value.operation_ref,
        "attempt_ref": value.attempt_ref,
        "audit_event_ref": value.audit_event_ref,
        "status": value.execution_status,
        "replayed": value.replayed,
        "attempts": stats["attempts"],
        "captures": stats["captures_after"],
    }


async def paused_case():
    directory = STORAGE / "restart"
    worker = Worker(directory)
    task, agent = worker.bootstrap(approval=True)
    owner = SecretStr(worker.command(command="owner").pop("token"))

    async def provider():
        return owner

    control = WorkflowControlClient(
        base_url="https://asgi.test", owner_credential_provider=provider, transport=worker
    )
    binding = ActionBinding(
        task_ref=task,
        action=ToolAction.FILES_READ,
        purpose="summarize_document",
        arguments={"resource_id": "resource_http"},
    )
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
        credential_provider=InMemoryTaskCredential(task, agent),
        transport=worker,
    ) as orchestration:
        result = await orchestration.execute_task(task, "STEP38_PRIVATE_PROMPT", (binding,))
    async with approval_workflow(
        checkpoint_path=directory / "workflow.sqlite", control=control
    ) as wf:
        paused = await wf.pause(result)
    response = await control._client.post(
        "/api/control/v1/approvals/" + paused.approval_ref + "/resolve",
        json={"resolution": "APPROVE"},
        headers={"Authorization": "Bearer " + owner.get_secret_value()},
    )
    assert response.status_code == 200 and response.json()["state"] == "APPROVED"
    await control.aclose()
    worker.stop()
    return worker, paused, owner, build_tool_request(task, 0, ToolAction.FILES_READ, binding)


async def main():
    all_events = []
    counts = []
    for scenario in SCENARIOS:
        events = await run_scenario(
            scenario, STORAGE / scenario, worker_factory=Worker, environment="LOCAL_MYSQL_MAILPIT"
        )
        all_events.extend(event.model_dump(mode="json", exclude_none=True) for event in events)
        worker = WORKERS[-1]
        counts.append(
            {
                "scenario": scenario,
                "task_ref": worker.context["task"],
                "before": worker.before_stats,
                "after": worker.last_stats,
            }
        )
    email = WORKERS[1]
    email.start()
    app_restart = await replay(email)
    assert app_restart["captures"] == 1
    email.stop()
    paused_worker, paused, owner, original = await paused_case()
    print(
        json.dumps(
            {
                "stage": "scenarios",
                "events": all_events,
                "scenario_counts": counts,
                "application_restart": app_restart,
                "paused_restart": {
                    "task_ref": paused.task_ref,
                    "operation_ref": paused.operation_ref,
                    "approval_ref": paused.approval_ref,
                    "workflow_ref": paused.binding_ref,
                    "checkpoint_id": paused.checkpoint_id,
                },
            }
        ),
        flush=True,
    )
    assert json.loads(await asyncio.to_thread(sys.stdin.readline)) == {"continue": True}
    email.start()
    database_restart = await replay(email)
    assert database_restart == app_restart
    email.stop()
    paused_worker.start()

    async def provider():
        return owner

    control = WorkflowControlClient(
        base_url="https://asgi.test", owner_credential_provider=provider, transport=paused_worker
    )
    async with approval_workflow(
        checkpoint_path=STORAGE / "restart/workflow.sqlite", control=control
    ) as wf:
        completed = await wf.resume(paused.binding_ref)
    assert completed.phase == "RESUMED" and completed.operation_ref == paused.operation_ref
    async with ControlledExecutionClient(
        enabled=True,
        base_url="https://asgi.test",
        task_ref=paused.task_ref,
        credential_provider=InMemoryTaskCredential(paused.task_ref, paused_worker.context["agent"]),
        transport=paused_worker,
    ) as client:
        observation = await client.status(completed)
        first = await client.execute_completed(
            completed, original, resume_ref=observation.resume_ref, expected_version="version_http"
        )
        assert first.execution_status == "SUCCEEDED"
        again = await client.execute_completed(
            completed, original, resume_ref=observation.resume_ref, expected_version="version_http"
        )
        assert again == first.model_copy(update={"replayed": True})
    checkpoint_clean(
        STORAGE / "restart/workflow.sqlite",
        [
            owner.get_secret_value(),
            paused_worker.context["agent"].get_secret_value(),
            "STEP38_PRIVATE_PROMPT",
        ],
    )
    paused_worker.stop()
    await control.aclose()
    unknown_events = await run_scenario(
        "email",
        STORAGE / "unknown",
        smtp_state="UNKNOWN",
        worker_factory=Worker,
        environment="LOCAL_MYSQL_MAILPIT",
    )
    uncertain = WORKERS[-1]
    uncertain.start()
    unknown_replay = await replay(uncertain)
    assert unknown_replay["status"] == "UNKNOWN" and unknown_replay["captures"] == 2
    uncertain.stop()
    assert not FORBIDDEN
    print(
        json.dumps(
            {
                "stage": "restart_unknown",
                "database_restart": database_restart,
                "paused_recovered": {
                    "operation_ref": completed.operation_ref,
                    "approval_ref": completed.approval_ref,
                    "phase": completed.phase,
                    "attempt_ref": first.attempt_ref,
                    "audit_event_ref": first.audit_event_ref,
                },
                "unknown_events": [
                    e.model_dump(mode="json", exclude_none=True) for e in unknown_events
                ],
                "unknown_replay": unknown_replay,
                "forbidden": len(FORBIDDEN),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        for worker in WORKERS:
            if worker.process.poll() is None:
                worker.stop()
