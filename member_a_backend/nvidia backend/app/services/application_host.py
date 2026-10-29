"""Single bounded B process; private IPC exposes authorization and pause registration only."""

import asyncio
import json
import os
import secrets
import subprocess
from pathlib import Path
from threading import Lock
from uuid import uuid4

import httpx
from pydantic import Field

from app.agent_schemas import Action, IdentityModel
from app.application_contracts import (
    ApplicationError,
    AuthorizationDecision,
    AuthorizationReason,
    Intent,
    Outcome,
)
from app.gateway_contracts import OpaqueReference, ToolRequest
from app.routes.gateway import check_depth, finite_number, invalid_number, unique_object
from app.services.workflow_resume import workflow_checkpoint
from app.workflow_contracts import (
    WorkflowIdentity,
    WorkflowPause,
    WorkflowPrepare,
    WorkflowSnapshot,
)

RPC_BUDGET_SECONDS = 3.5


async def terminate(process):
    process.stdin.close()
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    await process.communicate()


def late_startup(task):
    """A slow OS spawn cannot become an unowned planning worker."""
    if task.cancelled() or task.exception() is not None:
        return
    process = task.result()
    process.stdin.close()
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    # The runtime stays quarantined; this callback only disposes a late OS handle.
    asyncio.create_task(process.communicate())


class ProposedPlan(IdentityModel):
    task_ref: OpaqueReference
    intent: Intent
    proposed_actions: tuple[Action, ...] = Field(max_length=10)
    requires_external_action: bool
    clarification_required: bool


class HostObservation(IdentityModel):
    task_ref: OpaqueReference
    outcome: Outcome
    plan: ProposedPlan | None
    request_id: OpaqueReference | None
    decision: AuthorizationDecision | None
    reason_code: AuthorizationReason | None
    approval_ref: OpaqueReference | None
    binding_ref: OpaqueReference | None
    error: str | None = Field(max_length=64)


class ApplicationRuntime:
    def __init__(self, *, workflow_directory=None, interpreter=None):
        root = Path(__file__).resolve().parents[4]
        self.interpreter = Path(interpreter) if interpreter else root / ".venv/Scripts/python.exe"
        self.worker = root / "backend/app/agent/application_host.py"
        self.workflow_directory = (
            Path(workflow_directory)
            if workflow_directory
            else Path.home() / ".ghost-protocol/workflows"
        )
        self.identity = f"runtime_{uuid4().hex}"
        self.cursor_key = secrets.token_bytes(32)
        self._lock = Lock()
        self._active = None
        self.quarantined = False

    def reserve(self, command_ref, task_ref):
        with self._lock:
            if self.quarantined:
                raise ApplicationError(409, "COMMAND_UNCERTAIN", uncertain=True)
            if self._active is not None:
                raise ApplicationError(
                    409 if self._active[1] == task_ref else 429,
                    "COMMAND_IN_PROGRESS" if self._active[1] == task_ref else "CAPACITY_EXCEEDED",
                )
            self._active = (command_ref, task_ref)

    def active(self, command_ref):
        with self._lock:
            return self._active is not None and self._active[0] == command_ref

    def release(self, *, uncertain=False):
        with self._lock:
            self.quarantined |= uncertain
            self._active = None

    async def run(
        self,
        *,
        task_ref,
        user_request,
        action,
        purpose,
        arguments,
        credential,
        callback,
        budget_seconds=18,
        binding_ref=None,
    ):
        if not self.interpreter.is_file() or not self.worker.is_file():
            raise ApplicationError(503, "HOST_UNAVAILABLE")
        try:
            self.workflow_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = self.workflow_directory / f"{task_ref}.sqlite"
            if binding_ref and not path.is_file():
                raise ApplicationError(409, "WORKFLOW_NOT_READY")
            if self.workflow_directory.is_symlink() or path.is_symlink():
                raise ValueError
        except (OSError, ValueError):
            raise ApplicationError(503, "HOST_UNAVAILABLE") from None
        env = {
            key: os.environ[key]
            for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP")
            if key in os.environ
        }
        env.update(
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONIOENCODING="utf-8",
            LANGSMITH_TRACING="false",
            LANGCHAIN_TRACING_V2="false",
        )
        process, startup = None, None
        try:
            async with asyncio.timeout(budget_seconds):
                startup = asyncio.create_task(
                    asyncio.create_subprocess_exec(
                        str(self.interpreter),
                        "-I",
                        "-B",
                        str(self.worker),
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                        env=env,
                        limit=262144,
                        cwd=str(self.workflow_directory),
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    )
                )
                process = await asyncio.shield(startup)

                async def write(value):
                    raw = json.dumps(value, ensure_ascii=True, allow_nan=False).encode() + b"\n"
                    if len(raw) > 262144:
                        raise ValueError
                    process.stdin.write(raw)
                    await process.stdin.drain()

                await write(
                    dict(
                        kind="CONTINUE",
                        task_ref=task_ref,
                        binding_ref=binding_ref,
                        checkpoint_path=str(path),
                    )
                    if binding_ref
                    else dict(
                        task_ref=task_ref,
                        user_request=user_request,
                        action=action,
                        purpose=purpose,
                        arguments=arguments,
                        credential=credential.get_secret_value(),
                        checkpoint_path=str(path),
                    )
                )
                expected = (
                    ["get", "admit", "claim", "complete"]
                    if binding_ref
                    else ["authorize", "prepare", "pause"]
                )
                count = 0
                while True:
                    raw = await process.stdout.readline()
                    if not raw.endswith(b"\n") or len(raw) > 262144:
                        raise ValueError
                    data = json.loads(
                        raw,
                        object_pairs_hook=unique_object,
                        parse_constant=invalid_number,
                        parse_float=finite_number,
                    )
                    check_depth(data)
                    if (
                        binding_ref
                        and data.get("kind") == "error"
                        and set(data) == {"kind", "code"}
                        and data["code"] in ("WORKFLOW_NOT_READY", "COMMAND_UNCERTAIN")
                    ):
                        code = data["code"] if count == 1 else "COMMAND_UNCERTAIN"
                        raise ApplicationError(409, code, uncertain=code == "COMMAND_UNCERTAIN")
                    if data.get("kind") == "result" and set(data) == {"kind", "body"}:
                        model = WorkflowSnapshot if binding_ref else HostObservation
                        result = model.model_validate_json(json.dumps(data["body"]), strict=True)
                        process.stdin.close()
                        await process.wait()
                        if process.returncode != 0:
                            raise ValueError
                        return result
                    kind = data.get("kind")
                    step = (
                        kind
                        if kind == "authorize"
                        else data.get("command")
                        if kind == "workflow"
                        else None
                    )
                    if binding_ref and count == 1 and step == "claim":
                        count += 1
                    if count >= len(expected) or step != expected[count]:
                        raise ValueError
                    count += 1
                    await write(
                        {"reply": await asyncio.wait_for(callback(data), RPC_BUDGET_SECONDS)}
                    )
        except ApplicationError:
            raise
        except TimeoutError:
            raise ApplicationError(504, "COMMAND_TIMEOUT", uncertain=True) from None
        except Exception:
            raise ApplicationError(503, "HOST_UNAVAILABLE", uncertain=True) from None
        finally:
            if startup is not None:
                try:
                    async with asyncio.timeout(2):
                        if process is None:
                            process = await asyncio.shield(startup)
                        await terminate(process)
                except (TimeoutError, OSError):
                    self.quarantined = True
                    if process is None:
                        startup.add_done_callback(late_startup)


async def host_callback(
    data, *, request, owner, task_ref, credential, factory, action, purpose, arguments
):
    """No arbitrary HTTP forwarding, execution, approval resolution or browser identity."""
    if data.get("kind") == "authorize" and set(data) == {"kind", "body"}:
        payload = ToolRequest.model_validate_json(json.dumps(data["body"]))
        if (
            payload.task_ref,
            payload.action,
            payload.purpose,
            payload.arguments.model_dump(mode="json"),
        ) != (task_ref, action, purpose, arguments):
            raise ValueError("Original trusted binding required")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=request.app), base_url="https://private-ipc.test"
        ) as client:
            response = await client.post(
                "/api/gateway/v1/execute",
                json=payload.model_dump(mode="json"),
                headers={"Authorization": "Bearer " + credential.get_secret_value()},
            )
        return {"status": response.status_code, "body": response.json()}
    if data.get("kind") == "workflow" and set(data) == {
        "kind",
        "command",
        "payload",
        "binding_ref",
    }:
        command = data["command"]
        model = {"prepare": WorkflowPrepare, "pause": WorkflowPause}.get(command)
        if model is None:
            raise ValueError("Only metadata pause registration is available")
        payload = model.model_validate_json(json.dumps(data["payload"]))
        if command == "prepare" and payload.task_ref != task_ref:
            raise ValueError("Wrong pause task")

        def register():
            with factory() as db:
                # The trusted parent, not the child or browser, supplies the authenticated owner.
                if command == "pause":
                    from app.models import WorkflowCheckpoint

                    existing = db.get(WorkflowCheckpoint, data["binding_ref"])
                    if (
                        existing is None
                        or existing.task_ref != task_ref
                        or existing.owner_id != owner.owner_id
                    ):
                        raise ValueError("Wrong workflow binding")
                    db.rollback()
                result = workflow_checkpoint(
                    db,
                    owner=owner,
                    command=command,
                    payload=payload,
                    binding_ref=data["binding_ref"],
                )
                return result.model_dump(mode="json")

        return await asyncio.to_thread(register)
    raise ValueError("Unsupported host operation")


async def continuation_callback(data, *, owner, task_ref, binding_ref, factory):
    if (
        set(data) != {"kind", "command", "payload", "binding_ref"}
        or data["kind"] != "workflow"
        or data["binding_ref"] != binding_ref
    ):
        raise ValueError("Exact continuation binding required")
    command = data["command"]
    if command not in ("get", "admit", "claim", "complete"):
        raise ValueError("Only metadata continuation is available")
    if command == "get":
        if data["payload"] is not None:
            raise ValueError("No get payload")
        payload = None
    else:
        payload = WorkflowIdentity.model_validate_json(json.dumps(data["payload"]))
        if payload.task_ref != task_ref:
            raise ValueError("Wrong workflow task")

    def call():
        from app.models import WorkflowCheckpoint
        from app.services.agent_identity import AgentIdentityError

        with factory() as db:
            row = db.get(WorkflowCheckpoint, binding_ref)
            if row is None or (row.owner_id, row.task_ref) != (owner.owner_id, task_ref):
                raise ValueError("Wrong workflow owner")
            db.rollback()
            try:
                return workflow_checkpoint(
                    db, owner=owner, command=command, payload=payload, binding_ref=binding_ref
                ).model_dump(mode="json")
            except AgentIdentityError as exc:
                if exc.status_code == 409:
                    raise ApplicationError(409, "WORKFLOW_DENIED") from None
                raise

    return await asyncio.to_thread(call)
