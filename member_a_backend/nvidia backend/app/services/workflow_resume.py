"""Owner-authenticated workflow admission; no executor imports or approval consumption."""

import json
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from app.agent_schemas import AuthenticatedAgentContext, OwnerContext, TaskScope
from app.models import AgentCredential, AuditEvent, WorkflowCheckpoint
from app.services.agent_identity import _active, _transaction, _utc
from app.services.approvals import _owner_operation, reconcile
from app.services.operation_ledger import OperationError, _isolation
from app.services.resource_catalog import EMPTY_CATALOG
from app.services.scoped_consent import evaluate_locked_authorization
from app.workflow_contracts import (
    WorkflowIdentity,
    WorkflowPause,
    WorkflowPrepare,
    WorkflowSnapshot,
)


def _audit(db, task, row, now):
    event = AuditEvent(
        user_id=task.owner_id,
        event_type="gateway.workflow.transition",
        outcome=row.phase,
        created_at=now,
        detail={
            "binding_ref": row.binding_ref,
            "task_ref": task.task_ref,
            "operation_ref": row.operation_ref,
            "approval_ref": row.approval_ref,
            "phase": row.phase,
            "authorization_version": task.authorization_version,
            "timestamp": now.isoformat(),
        },
    )
    db.add(event)
    db.flush()
    row.audit_event_id, row.updated_at = event.id, now
    db.add(row)


def _snapshot(row, task):
    return WorkflowSnapshot(
        **{
            key: getattr(row, key)
            for key in WorkflowSnapshot.model_fields
            if key not in {"owner_ref", "authorization_version", "audit_event_ref"}
        },
        owner_ref=row.owner_id,
        authorization_version=task.authorization_version,
        audit_event_ref=f"event_{row.audit_event_id}",
    )


def _current(db, task, operation, approval, request, catalog, now):
    reconcile(db, task, operation, approval, request, catalog, now)
    if approval.status == "PENDING":
        return "WORKFLOW_NOT_APPROVED", None
    if approval.status != "APPROVED" or approval.consumed_at is not None or not _active(task, now):
        return "WORKFLOW_DENIED", None
    credential = db.scalar(
        select(AgentCredential)
        .where(
            AgentCredential.task_ref == task.task_ref,
            AgentCredential.owner_id == task.owner_id,
            AgentCredential.credential_epoch == task.credential_epoch,
            AgentCredential.revoked_at.is_(None),
            AgentCredential.issued_at <= now,
            AgentCredential.expires_at > now,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if credential is None:
        return "WORKFLOW_DENIED", None
    context = AuthenticatedAgentContext(
        credential_ref=credential.credential_ref,
        task_ref=task.task_ref,
        owner_id=task.owner_id,
        credential_expires_at=credential.expires_at,
        approved_scope=TaskScope.model_validate_json(json.dumps(task.authorization_scope)),
    )
    checked = evaluate_locked_authorization(db, context, request, task, catalog, now, operation)
    if checked.decision != "ALLOW" or operation.authorization_version != task.authorization_version:
        return "WORKFLOW_DENIED", None
    return None, min(approval.expires_at, task.expires_at, credential.expires_at)


def workflow_checkpoint(
    db, *, owner, command, payload=None, binding_ref=None, catalog=EMPTY_CATALOG, now=None
):
    """Fresh transaction per call; task lock serializes all authority changes."""
    if not isinstance(owner, OwnerContext):
        raise OperationError(403, "ROLE_FORBIDDEN")
    models = {
        "prepare": WorkflowPrepare,
        "pause": WorkflowPause,
        "admit": WorkflowIdentity,
        "claim": WorkflowIdentity,
        "complete": WorkflowIdentity,
    }
    if command not in {*models, "get"}:
        raise OperationError(422, "INVALID_REQUEST")
    if command != "get":
        payload = models[command].model_validate_json(payload.model_dump_json())
    error = None
    with _transaction(db):
        _isolation(db)
        timestamp = _utc(now)
        if command == "prepare":
            approval_ref = payload.approval_ref
        else:
            existing = db.scalar(
                select(WorkflowCheckpoint).where(
                    WorkflowCheckpoint.binding_ref == binding_ref,
                    WorkflowCheckpoint.owner_id == owner.owner_id,
                )
            )
            if existing is None:
                raise OperationError(404, "NOT_FOUND")
            approval_ref = existing.approval_ref
        task, operation, approval, request = _owner_operation(db, owner, approval_ref)
        row = db.scalar(
            select(WorkflowCheckpoint)
            .where(
                WorkflowCheckpoint.operation_ref == operation.operation_ref,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if command == "prepare":
            if (payload.task_ref, payload.request_id, payload.idempotency_key) != (
                task.task_ref,
                request.request_id,
                request.idempotency_key,
            ):
                raise OperationError(409, "WORKFLOW_CONFLICT")
            if not _active(task, timestamp) or approval.status not in ("PENDING", "APPROVED"):
                raise OperationError(409, "WORKFLOW_DENIED")
            if row is None:
                row = WorkflowCheckpoint(
                    binding_ref=f"wf_{uuid4().hex}",
                    thread_id=f"wfthread_{uuid4().hex}",
                    owner_id=task.owner_id,
                    task_ref=task.task_ref,
                    operation_ref=operation.operation_ref,
                    approval_ref=approval.approval_ref,
                    request_id=request.request_id,
                    idempotency_key=request.idempotency_key,
                    canonical_request_digest=operation.canonical_request_digest,
                    workflow_version=payload.workflow_version,
                    registration_authorization_version=task.authorization_version,
                    phase="PREPARING",
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                _audit(db, task, row, timestamp)
        else:
            if row is None or row.binding_ref != binding_ref or row.owner_id != task.owner_id:
                raise OperationError(404, "NOT_FOUND")
            if (row.request_id, row.idempotency_key, row.canonical_request_digest) != (
                request.request_id,
                request.idempotency_key,
                operation.canonical_request_digest,
            ):
                raise OperationError(503, "GATEWAY_UNAVAILABLE")
            if command == "pause":
                if row.phase == "PAUSED" and row.checkpoint_id == payload.checkpoint_id:
                    pass
                elif row.phase != "PREPARING":
                    raise OperationError(409, "WORKFLOW_CONFLICT")
                else:
                    row.checkpoint_id, row.phase = payload.checkpoint_id, "PAUSED"
                    _audit(db, task, row, timestamp)
            elif command != "get":
                for key in WorkflowIdentity.model_fields:
                    if key != "expected_authorization_version" and getattr(row, key) != getattr(
                        payload, key
                    ):
                        raise OperationError(409, "WORKFLOW_CONFLICT")
                reason, expiry = _current(
                    db, task, operation, approval, request, catalog, timestamp
                )
                if reason:
                    error = OperationError(409, reason)
                    if reason != "WORKFLOW_NOT_APPROVED" and row.phase != "RESUMED":
                        row.phase = "DENIED"
                        _audit(db, task, row, timestamp)
                elif payload.expected_authorization_version != task.authorization_version:
                    error = OperationError(409, "WORKFLOW_AUTHORIZATION_CHANGED")
                elif (
                    command != "admit"
                    and row.admitted_authorization_version != task.authorization_version
                ):
                    error = OperationError(409, "WORKFLOW_AUTHORIZATION_CHANGED")
                elif command != "admit" and (row.expires_at is None or timestamp >= row.expires_at):
                    error = OperationError(409, "WORKFLOW_EXPIRED")
                elif command == "admit":
                    if row.phase != "PAUSED":
                        error = OperationError(409, "WORKFLOW_ALREADY_ADMITTED")
                    else:
                        row.phase = "ADMITTED"
                        row.admitted_authorization_version = task.authorization_version
                        row.expires_at = min(timestamp + timedelta(seconds=60), expiry)
                        _audit(db, task, row, timestamp)
                elif command == "claim":
                    if row.phase != "ADMITTED":
                        error = OperationError(409, "WORKFLOW_ALREADY_CLAIMED")
                    else:
                        row.phase = "RESUMING"
                        _audit(db, task, row, timestamp)
                elif row.phase not in ("RESUMING", "RESUMED"):
                    error = OperationError(409, "WORKFLOW_NOT_PAUSED")
                elif row.phase == "RESUMING":
                    row.phase = "RESUMED"
                    _audit(db, task, row, timestamp)
        result = _snapshot(row, task)
    if error:
        raise error
    return result
