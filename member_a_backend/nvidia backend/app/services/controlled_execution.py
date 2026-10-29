"""Explicit trusted composition for v1.3; no document-content mode or SMTP fallback."""

import hashlib
import json
import secrets
from dataclasses import dataclass

from sqlalchemy import select

from app.controlled_contracts import ControlledExecutionResult
from app.models import AuditEvent, ExecutionAttempt, GatewayOperation, WorkflowCheckpoint
from app.services.agent_identity import authenticated_task
from app.services.approvals import load_approval
from app.services.mailpit_email import MailpitTransport
from app.services.operation_ledger import OperationError, _history, _isolation
from app.services.resource_catalog import EMPTY_CATALOG
from app.services.synthetic_executor import Executor, SyntheticExecutor


def check_workflow_execution(db, task, operation, approval, hint, now):
    """Called only within existing dispatcher transaction A, after task/operation/approval locks."""
    binding = db.scalar(
        select(WorkflowCheckpoint)
        .where(WorkflowCheckpoint.operation_ref == operation.operation_ref)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        approval is None
        or binding is None
        or not (
            binding.phase == "RESUMED"
            and binding.owner_id == task.owner_id == operation.owner_id
            and binding.task_ref == task.task_ref
            and binding.approval_ref == approval.approval_ref
            and binding.request_id == operation.request_id
            and binding.idempotency_key == operation.idempotency_key
            and binding.canonical_request_digest == operation.canonical_request_digest
            and binding.checkpoint_id is not None
            and binding.workflow_version == "approval-workflow-v1"
            and binding.admitted_authorization_version == task.authorization_version
        )
    ):
        raise OperationError(409, "NOT_RESUMABLE")
    event = db.get(AuditEvent, binding.audit_event_id)
    if (
        event is None
        or event.event_type != "gateway.workflow.transition"
        or event.outcome != "RESUMED"
        or event.user_id != task.owner_id
        or any(
            event.detail.get(key) != value
            for key, value in {
                "binding_ref": binding.binding_ref,
                "task_ref": task.task_ref,
                "operation_ref": operation.operation_ref,
                "approval_ref": approval.approval_ref,
                "phase": "RESUMED",
                "authorization_version": task.authorization_version,
            }.items()
        )
    ):
        raise OperationError(409, "NOT_RESUMABLE")
    digest = hashlib.sha256(hint.encode("ascii")).hexdigest()
    attempt = db.scalar(
        select(ExecutionAttempt)
        .where(ExecutionAttempt.operation_ref == operation.operation_ref)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if attempt is not None:
        if attempt.workflow_binding_ref != binding.binding_ref or not secrets.compare_digest(
            attempt.resume_hint_digest or "", digest
        ):
            raise OperationError(409, "NOT_RESUMABLE")
    elif not (
        operation.operation_status == "READY"
        and approval.status == "APPROVED"
        and approval.consumed_at is None
        and approval.resume_ref is not None
        and secrets.compare_digest(approval.resume_ref, hint)
        and binding.expires_at is not None
        and now < binding.expires_at
    ):
        raise OperationError(409, "NOT_RESUMABLE")
    return binding.binding_ref, digest, binding.expires_at


@dataclass(frozen=True)
class ControlledExecution:
    """Trusted backend dependency only; absent injection keeps the HTTP capability disabled."""

    simulator: Executor | None = None
    email_transport: MailpitTransport | None = None
    timeout_seconds: float = 1.0

    def resume(self, db, *, token, request_id, hint, catalog=EMPTY_CATALOG, now=None):
        from app.services.mailpit_email import SyntheticEmailExecutor
        from app.services.trusted_execution import _dispatch

        # Discover and reconstruct, then dispatch rechecks everything in its own transaction.
        with authenticated_task(db, token=token, task_ref=None, now=now) as (_, task):
            _isolation(db)
            operation = db.scalar(
                select(GatewayOperation)
                .where(
                    GatewayOperation.task_ref == task.task_ref,
                    GatewayOperation.owner_id == task.owner_id,
                    GatewayOperation.request_id == request_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if operation is None:
                raise OperationError(404, "NOT_FOUND")
            _history(db, operation)
            _, request = load_approval(db, task, operation)
        if request.action == "files.read":
            mode, executor = "SIMULATED", self.simulator or SyntheticExecutor()
        elif request.action in ("email.draft", "email.send") and self.email_transport is not None:
            mode = "EMAIL_DRAFT" if request.action == "email.draft" else "MAILPIT_SEND"
            executor = SyntheticEmailExecutor(self.email_transport)
        else:
            raise OperationError(403, "ACTION_DISABLED")
        report = _dispatch(
            db,
            token=token,
            request=request,
            catalog=catalog,
            executor=executor,
            now=now,
            mode=mode,
            controlled_hint=hint,
            timeout_seconds=self.timeout_seconds,
        )
        # Read only committed fenced metadata; no new admission or execution.
        with authenticated_task(db, token=token, task_ref=request.task_ref, now=now):
            attempt = db.get(ExecutionAttempt, report.attempt_ref, populate_existing=True)
            data = dict(
                contract_version="gw-execution-v1.3",
                task_ref=request.task_ref,
                operation_ref=report.operation_ref,
                attempt_ref=report.attempt_ref,
                workflow_ref=attempt.workflow_binding_ref,
                request_id=request.request_id,
                idempotency_key=request.idempotency_key,
                audit_event_ref=report.response.audit_event_ref,
                decision="ALLOW",
                admission="ADMITTED",
                execution_status=report.response.execution_status,
                mode=mode,
                effect={
                    "SIMULATED": "SIMULATED",
                    "EMAIL_DRAFT": "NO_MESSAGE_SUBMISSION",
                    "MAILPIT_SEND": "MAILPIT_TEST_ONLY",
                }[mode],
                result=report.response.result.model_dump(mode="json")
                if report.response.result
                else None,
                sanitized_error_code=report.sanitized_error_code,
                replayed=report.controlled_replay,
            )
        return ControlledExecutionResult.model_validate_json(json.dumps(data), strict=True)


def get_controlled_execution() -> ControlledExecution | None:
    return None
