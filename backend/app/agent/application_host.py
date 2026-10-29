"""Private one-command planning process. Stdout is bounded IPC, never user output."""

import asyncio
import json
import socket
import sys
from pathlib import Path

# A and B deliberately have different app packages/interpreters.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from typing import Literal  # noqa: E402

import httpx  # noqa: E402
from pydantic import Field, SecretStr  # noqa: E402

from app.agent.approval_workflow import approval_workflow  # noqa: E402
from app.agent.execution_contracts import ActionBinding, ExecutionOptions, ExecutionProvenance  # noqa: E402
from app.agent.gateway_protocol import ContractModel, OpaqueReference, ToolAction  # noqa: E402
from app.agent.http_gateway import InMemoryTaskCredential, _json  # noqa: E402
from app.agent.integration_runtime import gateway_runtime  # noqa: E402
from app.agent.mock_model_provider import MockModelProvider  # noqa: E402
from app.agent.planning_contracts import PlanningOptions, UserRequest  # noqa: E402
from app.agent.workflow_contracts import WorkflowError, WorkflowSnapshot  # noqa: E402


class PlanCommand(ContractModel):
    task_ref: OpaqueReference
    user_request: UserRequest = Field(repr=False)
    action: ToolAction
    purpose: str
    arguments: dict = Field(repr=False)
    credential: SecretStr = Field(repr=False)
    checkpoint_path: str = Field(repr=False)


class ContinueCommand(ContractModel):
    kind: Literal["CONTINUE"]
    task_ref: OpaqueReference
    binding_ref: OpaqueReference
    checkpoint_path: str = Field(repr=False)


def read_frame():
    raw = sys.stdin.buffer.readline(262146)
    if not raw.endswith(b"\n") or len(raw) > 262144:
        raise ValueError("Invalid host message")
    return _json(raw)


def frame(value):
    raw = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    if len(raw) > 262143:
        raise ValueError("Host message limit")
    sys.stdout.write(raw + "\n")
    sys.stdout.flush()


def rpc(kind, **value):
    frame({"kind": kind, **value})
    reply = read_frame()
    if set(reply) != {"reply"}:
        raise ValueError("Invalid host reply")
    return reply["reply"]


class GatewayPipe(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request):
        if request.method != "POST" or request.url.path != "/api/gateway/v1/execute":
            raise ValueError("Only authorization admission is available")
        data = rpc("authorize", body=json.loads(request.content))
        if set(data) != {"status", "body"}:
            raise ValueError("Invalid authorization observation")
        return httpx.Response(data["status"], json=data["body"])


class ControlPipe:
    def __init__(self, *, continuing=False):
        self.allowed = ("get", "admit", "claim", "complete") if continuing else ("prepare", "pause")

    async def call(self, command, payload=None, binding_ref=None):
        if command not in self.allowed:
            raise ValueError("Only pause registration is available")
        return WorkflowSnapshot.model_validate_json(
            json.dumps(rpc("workflow", command=command, payload=payload, binding_ref=binding_ref)),
            strict=True,
        )


async def plan(command, provider=None):
    """Existing graph, existing strict adapter and existing metadata-only checkpointer."""
    provider = provider or MockModelProvider(
        output={
            "task_ref": command.task_ref,
            "intent": command.purpose,
            "proposed_actions": [command.action.value],
            "requires_external_action": True,
            "clarification_required": False,
        }
    )
    binding = ActionBinding(
        task_ref=command.task_ref,
        action=command.action,
        purpose=command.purpose,
        arguments=command.arguments,
    )
    async with gateway_runtime(
        provider,
        mode=ExecutionProvenance.TRUSTED_AUTHORIZATION_ONLY,
        base_url="https://private-ipc.test",
        task_ref=command.task_ref,
        credential_provider=InMemoryTaskCredential(command.task_ref, command.credential),
        transport=GatewayPipe(),
        deadline_seconds=3.5,
        execution_options=ExecutionOptions(max_plan_actions=1, gateway_timeout_seconds=4),
        planning_options=PlanningOptions(inference_timeout_seconds=10),
    ) as orchestrator:
        result = await orchestrator.execute_task(command.task_ref, command.user_request, (binding,))
    binding_ref = None
    if result.execution_outcome == "APPROVAL_REQUIRED":
        async with approval_workflow(
            checkpoint_path=command.checkpoint_path, control=ControlPipe()
        ) as workflow:
            paused = await workflow.pause(result)
            binding_ref = paused.binding_ref
    action = result.action_results[-1] if result.action_results else None
    out_of_scope = (
        result.error_code
        in (
            "INVALID_TOOL_REQUEST",
            "DUPLICATE_ACTION",
            "ACTION_LIMIT_EXCEEDED",
        )
        and action is None
    )
    return {
        "task_ref": command.task_ref,
        "outcome": "FAILED" if out_of_scope else result.planning_result.outcome.value,
        "plan": result.planning_result.structured_plan.model_dump(mode="json")
        if result.planning_result.structured_plan and not out_of_scope
        else None,
        "request_id": action.request_ref if action else None,
        "decision": action.decision.value if action and action.decision else None,
        "reason_code": action.reason_code if action else None,
        "approval_ref": action.approval_ref if action else None,
        "binding_ref": binding_ref,
        "error": "PLAN_OUT_OF_SCOPE"
        if out_of_scope
        else result.error_code.value
        if result.error_code
        else None,
    }


async def continue_workflow(command):
    async with approval_workflow(
        checkpoint_path=command.checkpoint_path, control=ControlPipe(continuing=True)
    ) as workflow:
        return (await workflow.resume(command.binding_ref)).model_dump(mode="json")


def main():
    # IPC is the only carrier. Disable actual egress and credential/provider discovery.
    def denied(*args, **kwargs):
        raise RuntimeError("Planning host networking is disabled")

    socket.getaddrinfo = socket.create_connection = denied
    original = socket.socket.connect
    original_ex = socket.socket.connect_ex

    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return original(sock, address)  # Windows asyncio self-pipe only.
        return denied()

    socket.socket.connect = local_connect

    def local_connect_ex(sock, address):
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return original_ex(sock, address)
        return denied()

    socket.socket.connect_ex = local_connect_ex

    async def denied_async(*args, **kwargs):
        return denied()

    httpx.HTTPTransport.handle_request = denied
    httpx.AsyncHTTPTransport.handle_async_request = denied_async
    try:
        value = read_frame()
        if value.get("kind") == "CONTINUE":
            command = ContinueCommand.model_validate_json(json.dumps(value), strict=True)
            result = asyncio.run(continue_workflow(command))
        else:
            command = PlanCommand.model_validate_json(json.dumps(value), strict=True)
            result = asyncio.run(plan(command))
        frame({"kind": "result", "body": result})
    except WorkflowError as exc:
        if exc.code in ("CHECKPOINT_IDENTITY_MISMATCH", "RESUME_NOT_ADMISSIBLE"):
            frame({"kind": "error", "code": "WORKFLOW_NOT_READY"})
        else:
            frame({"kind": "error", "code": "COMMAND_UNCERTAIN"})
    except Exception:
        frame({"kind": "failed"})
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
