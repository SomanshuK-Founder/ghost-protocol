"""Offline acceptance harness, not a production runtime or live Mailpit client."""

import argparse
import asyncio
import json
import smtplib
import socket
import sqlite3
from contextlib import ExitStack, closing, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from unittest.mock import patch

import httpx
from pydantic import SecretStr, model_validator

from app.agent.approval_workflow import approval_workflow
from app.agent.controlled_execution import ControlledExecutionClient
from app.agent.execution_contracts import ActionBinding, ExecutionProvenance
from app.agent.gateway_protocol import ContractModel, OpaqueReference, ToolAction
from app.agent.http_gateway import (
    AuthenticatedHttpToolGateway,
    GatewayTransportError,
    InMemoryTaskCredential,
)
from app.agent.integration_runtime import gateway_runtime
from app.agent.mock_model_provider import MockModelProvider
from app.agent.orchestration import build_tool_request
from app.agent.workflow_contracts import WorkflowError
from app.agent.workflow_transport import WorkflowControlClient
from tests.agent.test_fastapi_gateway_integration import BackendProcess

SCENARIOS = (
    "document",
    "email",
    "missing_consent",
    "invalid_approval",
    "wrong_task",
    "unauthorized_recipient",
    "replay",
)


class DemoFailure(Exception):
    """Fail closed without rendering credentials, payloads or exception details."""


def require(condition):
    if not condition:
        raise DemoFailure("Offline demonstration verification failed")


class DemoEvent(ContractModel):
    display_only: Literal[True] = True
    environment: Literal["OFFLINE_ASGI_FAKE_SMTP", "LOCAL_MYSQL_MAILPIT"] = "OFFLINE_ASGI_FAKE_SMTP"
    scenario: Literal[
        "document",
        "email",
        "missing_consent",
        "invalid_approval",
        "wrong_task",
        "unauthorized_recipient",
        "replay",
    ]
    event: Literal[
        "TASK_CREATED",
        "PLAN_VALIDATED",
        "AUTHORIZATION_CHECKED",
        "APPROVAL_REQUIRED",
        "WORKFLOW_PAUSED",
        "OWNER_APPROVED",
        "WORKFLOW_RESUMED",
        "SAFE_STOPPED",
        "EXECUTION_ADMITTED",
        "EXECUTION_SUCCEEDED",
        "EXECUTION_FAILED",
        "EXECUTION_UNKNOWN",
        "EXECUTION_DENIED",
        "REPLAY_BLOCKED",
        "VERIFICATION_PASSED",
    ]
    task_ref: OpaqueReference
    operation_ref: OpaqueReference | None = None
    approval_ref: OpaqueReference | None = None
    workflow_ref: OpaqueReference | None = None
    attempt_ref: OpaqueReference | None = None
    audit_event_ref: OpaqueReference | None = None
    decision: Literal["ALLOW", "DENY", "APPROVAL_REQUIRED"] | None = None
    execution_status: Literal["NOT_EXECUTED", "SUCCEEDED", "FAILED", "UNKNOWN"] | None = None
    reason_code: OpaqueReference | None = None
    effect: Literal["SIMULATED", "FAKE_SMTP_ONLY", "LOCAL_MAILPIT_CAPTURE_VERIFIED"] | None = None
    replayed: bool | None = None
    attempts: int | None = None
    fake_smtp_submissions: int | None = None
    mailpit_captures_before: int | None = None
    mailpit_captures_after: int | None = None

    @model_validator(mode="after")
    def consistent_display(self):
        if self.environment == "OFFLINE_ASGI_FAKE_SMTP":
            valid = (
                self.effect != "LOCAL_MAILPIT_CAPTURE_VERIFIED"
                and self.mailpit_captures_before is self.mailpit_captures_after is None
            )
        else:
            valid = self.effect != "FAKE_SMTP_ONLY" and self.fake_smtp_submissions is None
            if self.mailpit_captures_before is not None or self.mailpit_captures_after is not None:
                valid = valid and (
                    self.mailpit_captures_before is not None
                    and self.mailpit_captures_after is not None
                    and 0 <= self.mailpit_captures_before <= self.mailpit_captures_after
                )
        if not valid:
            raise ValueError("Invalid demo display provenance")
        return self


@contextmanager
def offline_only():
    """Only Windows asyncio loopback plumbing is permitted; HTTP is ASGI/IPC only."""
    attempts = []

    def blocked(*args, **kwargs):
        attempts.append(True)
        raise DemoFailure("External transport forbidden")

    connect, connect_ex = socket.socket.connect, socket.socket.connect_ex

    def local(original):
        def guarded(sock, address):
            if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
                return original(sock, address)
            return blocked()

        return guarded

    with ExitStack() as guards:
        for target, name, replacement in (
            (socket, "getaddrinfo", blocked),
            (socket, "create_connection", blocked),
            (socket.socket, "connect", local(connect)),
            (socket.socket, "connect_ex", local(connect_ex)),
            (httpx.HTTPTransport, "handle_request", blocked),
            (httpx.AsyncHTTPTransport, "handle_async_request", blocked),
            (smtplib, "SMTP", blocked),
            (smtplib, "SMTP_SSL", blocked),
        ):
            guards.enter_context(patch.object(target, name, replacement))
        yield
        require(not attempts)


def checkpoint_clean(path, markers):
    with closing(sqlite3.connect(path)) as db:
        raw = b"".join(
            value if isinstance(value, bytes) else str(value).encode()
            for table in ("checkpoints", "writes")
            for row in db.execute("SELECT * FROM " + table)
            for value in row
        )
    require(all(marker.encode() not in raw for marker in markers))


async def run_scenario(
    scenario,
    directory,
    *,
    smtp_state="ACCEPTED",
    worker_factory=None,
    environment="OFFLINE_ASGI_FAKE_SMTP",
):
    """Trusted fixture configuration only; no model/CLI supplied hosts or credentials."""
    require(scenario in SCENARIOS and smtp_state in ("ACCEPTED", "REJECTED", "UNKNOWN"))
    require(environment in ("OFFLINE_ASGI_FAKE_SMTP", "LOCAL_MYSQL_MAILPIT"))
    worker = (worker_factory or BackendProcess)(directory)
    events = []
    owner_client = control = None
    try:
        worker.command(command="enable_controlled", smtp_state=smtp_state)
        email = scenario in ("email", "unauthorized_recipient")
        action = ToolAction.EMAIL_SEND if email else ToolAction.FILES_READ
        task, agent = worker.bootstrap(
            approval=scenario != "missing_consent",
            **({"email_action": action.value} if email else {}),
        )

        def emit(event, **metadata):
            events.append(
                DemoEvent(
                    scenario=scenario,
                    event=event,
                    task_ref=task,
                    environment=environment,
                    **metadata,
                )
            )

        emit("TASK_CREATED")
        owner = SecretStr(worker.command(command="owner").pop("token"))
        owner_client = httpx.AsyncClient(
            base_url="https://asgi.test",
            transport=worker,
            trust_env=False,
            follow_redirects=False,
            timeout=4,
            headers={"Authorization": "Bearer " + owner.get_secret_value()},
        )
        arguments = (
            worker.command(command="email_profile") if email else {"resource_id": "resource_http"}
        )
        body_marker = arguments.get("body", "STEP38_PRIVATE_DOCUMENT")
        if scenario == "unauthorized_recipient":
            arguments["recipient"] = "unapproved@example.test"
        purpose = "prepare_email" if email else "summarize_document"
        binding = ActionBinding(task_ref=task, action=action, purpose=purpose, arguments=arguments)
        original = build_tool_request(task, 0, action, binding)
        credentials = InMemoryTaskCredential(task, agent)
        if scenario == "wrong_task":
            # Deliberately reach A with a genuine credential bound to a different task.
            wrong = original.model_copy(update={"task_ref": "task_wrong_demo"})
            async with AuthenticatedHttpToolGateway(
                base_url="https://asgi.test",
                task_ref=wrong.task_ref,
                credential_provider=InMemoryTaskCredential(wrong.task_ref, agent),
                transport=worker,
            ) as gateway:
                try:
                    await gateway.execute(wrong)
                except GatewayTransportError as exc:
                    require(
                        exc.http_status == 403 and exc.server_error_code == "TASK_SCOPE_MISMATCH"
                    )
                    emit("EXECUTION_DENIED", reason_code=exc.server_error_code)
                else:
                    raise DemoFailure()
        else:
            model = MockModelProvider(
                output={
                    "task_ref": task,
                    "intent": purpose,
                    "proposed_actions": [action.value],
                    "requires_external_action": True,
                    "clarification_required": False,
                }
            )
            async with gateway_runtime(
                model,
                mode=ExecutionProvenance.TRUSTED_AUTHORIZATION_ONLY,
                base_url="https://asgi.test",
                task_ref=task,
                credential_provider=credentials,
                transport=worker,
            ) as orchestrator:
                result = await orchestrator.execute_task(task, "STEP38_PRIVATE_PROMPT", (binding,))
            require(result.planning_result.outcome == "PLAN_READY" and len(model.requests) == 1)
            emit("PLAN_VALIDATED")
            row = result.action_results[-1]
            require(row.execution_status == "NOT_EXECUTED" and row.audit_event_ref is not None)
            emit(
                "AUTHORIZATION_CHECKED",
                decision=row.decision,
                execution_status=row.execution_status,
                audit_event_ref=row.audit_event_ref,
            )
            if scenario in ("missing_consent", "unauthorized_recipient"):
                expected = (
                    "APPROVAL_UNAVAILABLE"
                    if scenario == "missing_consent"
                    else "RECIPIENT_NOT_AUTHORIZED"
                )
                require(row.decision == "DENY" and row.reason_code == expected)
                emit(
                    "EXECUTION_DENIED",
                    reason_code=row.reason_code,
                    audit_event_ref=row.audit_event_ref,
                )
            else:
                require(row.decision == "APPROVAL_REQUIRED" and row.approval_ref is not None)
                emit(
                    "APPROVAL_REQUIRED",
                    approval_ref=row.approval_ref,
                    audit_event_ref=row.audit_event_ref,
                )

                async def owner_provider():
                    return owner

                control = WorkflowControlClient(
                    base_url="https://asgi.test",
                    owner_credential_provider=owner_provider,
                    transport=worker,
                )
                path = Path(directory) / "workflow.sqlite"
                async with approval_workflow(checkpoint_path=path, control=control) as workflow:
                    paused = await workflow.pause(result)
                require(paused.phase == "PAUSED" and paused.approval_ref == row.approval_ref)
                emit(
                    "WORKFLOW_PAUSED",
                    operation_ref=paused.operation_ref,
                    workflow_ref=paused.binding_ref,
                )
                resolution = "REJECT" if scenario == "invalid_approval" else "APPROVE"
                response = await owner_client.post(
                    f"/api/control/v1/approvals/{paused.approval_ref}/resolve",
                    json={"resolution": resolution},
                )
                require(response.status_code == 200)
                decision = response.json()
                require(decision["approval_ref"] == paused.approval_ref)
                if scenario == "invalid_approval":
                    require(decision["state"] == "REJECTED")
                    async with approval_workflow(checkpoint_path=path, control=control) as workflow:
                        try:
                            await workflow.resume(paused.binding_ref)
                        except WorkflowError as exc:
                            require(exc.code == "WORKFLOW_DENIED")
                            emit(
                                "EXECUTION_DENIED",
                                reason_code=exc.code,
                                audit_event_ref=decision["audit_event_ref"],
                            )
                        else:
                            raise DemoFailure()
                else:
                    require(decision["state"] == "APPROVED")
                    emit(
                        "OWNER_APPROVED",
                        approval_ref=paused.approval_ref,
                        audit_event_ref=decision["audit_event_ref"],
                    )
                    async with approval_workflow(checkpoint_path=path, control=control) as workflow:
                        complete = await workflow.resume(paused.binding_ref)
                    require(
                        complete.phase == "RESUMED"
                        and complete.operation_ref == paused.operation_ref
                    )
                    emit(
                        "WORKFLOW_RESUMED",
                        workflow_ref=complete.binding_ref,
                        audit_event_ref=complete.audit_event_ref,
                    )
                    emit("SAFE_STOPPED", workflow_ref=complete.binding_ref)
                    before = worker.command(command="demo_inspect")
                    require(before["consent_bound"] and not before["approval_consumed"])
                    require(worker.command(command="stats")["attempts"] == 0)
                    async with ControlledExecutionClient(
                        enabled=True,
                        base_url="https://asgi.test",
                        task_ref=task,
                        credential_provider=credentials,
                        transport=worker,
                    ) as execution:
                        status = await execution.status(complete)
                        require(status.resume_ref is not None)
                        first = await execution.execute_completed(
                            complete,
                            original,
                            resume_ref=status.resume_ref,
                            expected_version="version_http",
                        )
                        emit(
                            "EXECUTION_ADMITTED",
                            operation_ref=first.operation_ref,
                            attempt_ref=first.attempt_ref,
                            audit_event_ref=first.audit_event_ref,
                            decision=first.decision,
                        )
                        emit(
                            "EXECUTION_" + first.execution_status,
                            operation_ref=first.operation_ref,
                            audit_event_ref=first.audit_event_ref,
                            execution_status=first.execution_status,
                            effect=(
                                "FAKE_SMTP_ONLY"
                                if environment == "OFFLINE_ASGI_FAKE_SMTP"
                                else "LOCAL_MAILPIT_CAPTURE_VERIFIED"
                            )
                            if email
                            else "SIMULATED",
                            replayed=first.replayed,
                        )
                        if scenario == "replay":
                            again = await execution.execute_completed(
                                complete,
                                original,
                                resume_ref=status.resume_ref,
                                expected_version="version_http",
                            )
                            require(again == first.model_copy(update={"replayed": True}))
                            emit(
                                "REPLAY_BLOCKED",
                                operation_ref=again.operation_ref,
                                attempt_ref=again.attempt_ref,
                                audit_event_ref=again.audit_event_ref,
                                execution_status=again.execution_status,
                                replayed=again.replayed,
                            )
                    after = worker.command(command="demo_inspect")
                    require(
                        after["approval_consumed"]
                        and after["operation_states"] == [first.execution_status]
                    )
                checkpoint_clean(
                    path,
                    [
                        agent.get_secret_value(),
                        owner.get_secret_value(),
                        body_marker,
                        "STEP38_PRIVATE_PROMPT",
                        "STEP38_PRIVATE_DOCUMENT",
                    ],
                )
        stats = worker.command(command="stats")
        inspection = worker.command(command="demo_inspect")
        executed = scenario in ("document", "email", "replay")
        require(stats["forbidden"] == 0 and inspection["private_rows_clean"])
        require(stats["attempts"] == int(executed))
        submitted = (
            stats["fake_smtp_calls"]
            if environment == "OFFLINE_ASGI_FAKE_SMTP"
            else (stats["captures_after"] - stats["captures_before"])
        )
        require(submitted == int(scenario == "email"))
        require(inspection["verified_messages"] == submitted)
        require(
            all(
                event.audit_event_ref is None
                or event.audit_event_ref in {f"event_{ref}" for ref in stats["audits"]}
                for event in events
            )
        )
        emit(
            "VERIFICATION_PASSED",
            attempts=stats["attempts"],
            **(
                {"fake_smtp_submissions": submitted}
                if environment == "OFFLINE_ASGI_FAKE_SMTP"
                else {
                    "mailpit_captures_before": stats["captures_before"],
                    "mailpit_captures_after": stats["captures_after"],
                }
            ),
        )
        output = "\n".join(event.model_dump_json(exclude_none=True) for event in events)
        require(
            all(
                secret not in output
                for secret in (
                    agent.get_secret_value(),
                    owner.get_secret_value(),
                    body_marker,
                    "STEP38_PRIVATE_PROMPT",
                )
            )
        )
        return events
    finally:
        if control is not None:
            await control.aclose()
        if owner_client is not None:
            await owner_client.aclose()
        worker.stop()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("all", *SCENARIOS), default="all")
    args = parser.parse_args(argv)
    try:
        completed = []
        with offline_only(), TemporaryDirectory(prefix="ghost-step38-") as temporary:
            for name in SCENARIOS if args.scenario == "all" else (args.scenario,):
                directory = Path(temporary) / name
                directory.mkdir()
                events = asyncio.run(run_scenario(name, directory))
                completed.extend(events)
        for event in completed:
            print(event.model_dump_json(exclude_none=True))
        return 0
    except Exception:
        print(
            json.dumps(
                {
                    "display_only": True,
                    "event": "DEMO_FAILED",
                    "error_code": "DEMO_VERIFICATION_FAILED",
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
