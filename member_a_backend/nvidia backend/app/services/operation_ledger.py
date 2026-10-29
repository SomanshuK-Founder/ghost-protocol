"""Durable admission and history. HTTP callers never dispatch an executor."""

import hashlib
import json
from datetime import datetime
from uuid import uuid4

from pydantic import SecretStr, ValidationError
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent_schemas import AuthenticatedAgentContext, TaskScope
from app.gateway_contracts import Authorization, OperationStatus, ToolRequest, ToolResponse
from app.models import AuditEvent, GatewayOperation, GatewayTask, PendingApproval, ScopedConsent
from app.services.agent_identity import AgentIdentityError, _utc, authenticated_task
from app.services.resource_catalog import EMPTY_CATALOG, ResourceCatalog
from app.services.scoped_consent import (
    evaluate_authorization,
    evaluate_locked_authorization,
    record_decision,
)


class OperationError(AgentIdentityError):
    def __init__(self, status_code: int, code: str, *, execution_uncertain: bool = False):
        super().__init__(status_code, code)
        self.execution_uncertain = execution_uncertain


def _hash(value: dict) -> str:
    canonical = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def request_digests(owner_id: str, request: ToolRequest, scope: TaskScope) -> tuple[str, str]:
    wire = _hash(
        {
            "version": "gw-wire-v1",
            "owner_id": owner_id,
            "task_ref": request.task_ref,
            "action": request.action,
            "purpose": request.purpose,
            "arguments": request.arguments.model_dump(mode="json"),
        }
    )
    pins = scope.model_dump(mode="json")
    pins["resource_ids"] = sorted(pins["resource_ids"])
    pins["resource_versions"] = sorted(
        pins["resource_versions"], key=lambda item: item["resource_id"]
    )
    return wire, _hash({"version": "gw-binding-v1", "wire_digest": wire, "task_scope": pins})


def validate_transition(
    current: str,
    target: str,
    *,
    authorization: Authorization | None = None,
    versions_match: bool = False,
) -> str:
    """Pure future-state guard; never writes a row or dispatches a handler."""
    if (current, target) not in {
        ("ADMITTED", "DENIED"),
        ("ADMITTED", "DISPATCHING"),
        ("DISPATCHING", "UNKNOWN"),
        ("DISPATCHING", "SUCCEEDED"),
        ("DISPATCHING", "FAILED"),
        ("PENDING_APPROVAL", "READY"),
        ("PENDING_APPROVAL", "DENIED"),
        ("READY", "DENIED"),
        ("READY", "DISPATCHING"),
    }:
        raise OperationError(409, "NOT_RESUMABLE")
    if target == "DISPATCHING" and (
        authorization is None or authorization.decision != "ALLOW" or not versions_match
    ):
        raise OperationError(409, "NOT_RESUMABLE")
    return target


def validate_future_dispatch(
    context: AuthenticatedAgentContext,
    request: ToolRequest,
    task: GatewayTask,
    consents: list[ScopedConsent],
    operation: GatewayOperation,
    *,
    catalog: ResourceCatalog = EMPTY_CATALOG,
    now: datetime,
    approval=None,
) -> Authorization:
    """Specification guard only: future caller must authenticate/load/lock all state again."""
    result = evaluate_authorization(
        context,
        request,
        task,
        consents,
        catalog=catalog,
        now=now,
        operation=operation,
        approval=approval,
    )
    if result.decision == "DENY":
        return result
    if approval is not None and approval.consumed_at is not None:
        raise OperationError(409, "NOT_RESUMABLE")
    wire, binding = request_digests(context.owner_id, request, context.approved_scope)
    if (
        operation.owner_id != context.owner_id
        or operation.task_ref != context.task_ref
        or operation.request_id != request.request_id
        or operation.idempotency_key != request.idempotency_key
        or operation.canonical_request_digest != wire
        or operation.binding_digest != binding
    ):
        raise OperationError(409, "NOT_RESUMABLE")
    validate_transition(
        operation.operation_status,
        "DISPATCHING",
        authorization=result,
        versions_match=operation.authorization_version == task.authorization_version,
    )
    return result


def _isolation(db: Session) -> None:
    connection = db.connection()
    if connection.dialect.name == "mysql" and connection.get_isolation_level() != "READ COMMITTED":
        raise OperationError(503, "GATEWAY_UNAVAILABLE", execution_uncertain=True)


def _candidates(db: Session, task: GatewayTask, request: ToolRequest, digest: str):
    return list(
        db.scalars(
            select(GatewayOperation)
            .where(
                or_(
                    and_(
                        GatewayOperation.owner_id == task.owner_id,
                        GatewayOperation.request_id == request.request_id,
                    ),
                    and_(
                        GatewayOperation.owner_id == task.owner_id,
                        GatewayOperation.task_ref == task.task_ref,
                        GatewayOperation.idempotency_key == request.idempotency_key,
                    ),
                    and_(
                        GatewayOperation.task_ref == task.task_ref,
                        GatewayOperation.canonical_request_digest == digest,
                    ),
                )
            )
            .order_by(GatewayOperation.operation_ref)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )


def _match(rows, task, request, digest):
    if not rows:
        return None
    uncertain = any(row.operation_status in ("UNKNOWN", "DISPATCHING") for row in rows)
    for row in rows:
        if (
            row.owner_id == task.owner_id
            and row.task_ref == task.task_ref
            and (
                row.request_id == request.request_id
                and row.idempotency_key == request.idempotency_key
                and row.canonical_request_digest == digest
                and row.action == request.action
            )
        ):
            if len(rows) != 1:
                raise OperationError(503, "GATEWAY_UNAVAILABLE", execution_uncertain=True)
            return row
    conflict = (
        "IDEMPOTENCY_CONFLICT"
        if any(
            (row.owner_id == task.owner_id and row.request_id == request.request_id)
            or (row.task_ref == task.task_ref and row.idempotency_key == request.idempotency_key)
            for row in rows
        )
        else "LOGICAL_OPERATION_EXISTS"
    )
    raise OperationError(409, conflict, execution_uncertain=uncertain)


def _history(db: Session, operation: GatewayOperation) -> None:
    rows = list(
        db.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.event_type == "gateway.authorization",
                AuditEvent.detail["operation_ref"].as_string() == operation.operation_ref,
            )
            .order_by(AuditEvent.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    try:
        if not rows or len(rows) != operation.revision + 1:
            raise ValueError("Incomplete history")
        previous_state, previous_version, previous_time = None, -1, operation.created_at
        dispatch_time = None
        for revision, row in enumerate(rows):
            detail = row.detail
            state, version = detail["operation_state"], detail["authorization_version"]
            timestamp = datetime.fromisoformat(detail["timestamp"])
            checked = Authorization(decision=detail["decision"], reason_code=detail["reason_code"])
            if not (
                row.user_id == operation.owner_id
                and row.event_type == "gateway.authorization"
                and detail["task_ref"] == operation.task_ref
                and detail["request_id"] == operation.request_id
                and detail["action"] == operation.action
                and detail["revision"] == revision
                and version >= 0
                and row.outcome == checked.decision
                and timestamp >= previous_time
            ):
                raise ValueError("Invalid audit binding")
            if state in ("UNKNOWN", "DISPATCHING"):
                valid = (
                    checked.decision == "ALLOW" and checked.reason_code == "EXECUTION_UNCONFIRMED"
                )
            elif state in ("SUCCEEDED", "FAILED"):
                valid = checked.decision == "ALLOW" and checked.reason_code == (
                    "EXECUTION_SUCCEEDED" if state == "SUCCEEDED" else "TOOL_FAILED_NO_EFFECT"
                )
            elif state == "ADMITTED":
                valid = (
                    checked.decision == "ALLOW" and checked.reason_code == "EXECUTION_NOT_STARTED"
                )
            elif state == "DENIED":
                valid = checked.decision == "DENY" and checked.reason_code not in (
                    "EXECUTION_NOT_STARTED",
                    "EXECUTION_UNCONFIRMED",
                )
            elif state in ("PENDING_APPROVAL", "READY"):
                valid = (
                    checked.decision == "APPROVAL_REQUIRED"
                    and checked.reason_code == "CONSENT_REVIEW_REQUIRED"
                )
            else:
                valid = False
            if not valid or version < previous_version:
                raise ValueError("Invalid state")
            if previous_state is None:
                if (
                    state not in ("ADMITTED", "DENIED", "PENDING_APPROVAL")
                    or timestamp != operation.created_at
                ):
                    raise ValueError("Missing admission")
            elif previous_state == state == "ADMITTED":
                if version <= previous_version:
                    raise ValueError("Invalid authorization refresh")
            else:
                validate_transition(
                    previous_state,
                    state,
                    authorization=checked,
                    versions_match=version == previous_version,
                )
            if state == "DISPATCHING":
                dispatch_time = timestamp
            previous_state, previous_version, previous_time = state, version, timestamp
        last = rows[-1]
        if not (
            last.id == operation.audit_event_id
            and previous_state == operation.operation_status
            and last.detail["decision"] == operation.decision
            and last.detail["reason_code"] == operation.reason_code
            and previous_version == operation.authorization_version
            and previous_time == operation.updated_at
        ):
            raise ValueError("Invalid operation snapshot")
        if operation.operation_status in ("UNKNOWN", "DISPATCHING"):
            if (
                dispatch_time is None
                or operation.execution_started_at != dispatch_time
                or operation.execution_finished_at is not None
            ):
                raise ValueError("Invalid uncertain history")
        elif operation.operation_status in ("SUCCEEDED", "FAILED"):
            if (
                dispatch_time is None
                or operation.execution_started_at != dispatch_time
                or operation.execution_finished_at != previous_time
            ):
                raise ValueError("Invalid completion history")
        elif (
            operation.execution_started_at is not None
            or operation.execution_finished_at is not None
        ):
            raise ValueError("Admission has execution timestamps")
        if (
            operation.operation_status in ("SUCCEEDED", "FAILED")
            or last.detail.get("mode") == "SIMULATED"
        ):
            from app.services.trusted_execution import _attempt

            _attempt(db, operation)
    except (KeyError, ValueError, TypeError, IndexError, AgentIdentityError):
        raise OperationError(503, "GATEWAY_UNAVAILABLE", execution_uncertain=True) from None


def _audit(db, task, request, result, operation, timestamp):
    ref = record_decision(db, task, request, result, timestamp, operation=operation)
    operation.audit_event_id = int(ref.removeprefix("event_"))
    # A populate_existing read must see the complete snapshot with autoflush disabled.
    db.flush()


def _response(operation, approval=None) -> ToolResponse:
    if operation.operation_status == "READY":
        raise OperationError(409, "RESUME_REQUIRED")
    if operation.operation_status == "DISPATCHING":
        raise OperationError(409, "OPERATION_IN_PROGRESS", execution_uncertain=True)
    if operation.operation_status in ("SUCCEEDED", "FAILED"):
        # Full terminal results require current authorization and cache-retention checks.
        raise OperationError(503, "GATEWAY_UNAVAILABLE", execution_uncertain=True)
    return ToolResponse(
        request_id=operation.request_id,
        decision=operation.decision,
        reason_code=operation.reason_code,
        execution_status="UNKNOWN" if operation.operation_status == "UNKNOWN" else "NOT_EXECUTED",
        audit_event_ref=operation.audit_event_ref,
        approval_ref=approval.approval_ref
        if operation.operation_status == "PENDING_APPROVAL" and approval is not None
        else None,
    )


def _refresh_admitted(db, context, task, request, operation, binding, catalog, now):
    if operation.operation_status != "ADMITTED":
        return
    timestamp = _utc(now)
    result = evaluate_locked_authorization(db, context, request, task, catalog, timestamp)
    if operation.binding_digest != binding:
        result = Authorization(decision="DENY", reason_code="RESOURCE_VERSION_CHANGED")
    if result.decision == "DENY" or operation.authorization_version != task.authorization_version:
        operation.revision += 1
        operation.updated_at = timestamp
        operation.authorization_version = task.authorization_version
        operation.operation_status = "DENIED" if result.decision == "DENY" else "ADMITTED"
        operation.decision, operation.reason_code = result.decision, result.reason_code
        _audit(db, task, request, result, operation, timestamp)


def _approval_state(db, task, operation, catalog, now):
    from app.services.approvals import load_approval, reconcile

    exists = db.scalar(
        select(PendingApproval.approval_ref).where(
            PendingApproval.operation_ref == operation.operation_ref
        )
    )
    if exists is None and operation.operation_status not in ("PENDING_APPROVAL", "READY"):
        return None
    approval, request = load_approval(db, task, operation)
    reconcile(db, task, operation, approval, request, catalog, _utc(now))
    return approval


def admit_operation(
    db: Session,
    *,
    token: SecretStr,
    request: ToolRequest,
    catalog: ResourceCatalog = EMPTY_CATALOG,
    now: datetime | None = None,
) -> ToolResponse:
    try:
        request = ToolRequest.model_validate_json(request.model_dump_json(warnings=False))
    except (AttributeError, ValidationError, ValueError, TypeError):
        raise OperationError(422, "INVALID_REQUEST") from None
    with authenticated_task(db, token=token, task_ref=request.task_ref, now=now) as (context, task):
        _isolation(db)
        wire, binding = request_digests(context.owner_id, request, context.approved_scope)
        operation = _match(_candidates(db, task, request, wire), task, request, wire)
        if operation is not None:
            _history(db, operation)
        if operation is None:
            timestamp = _utc(now)
            result = evaluate_locked_authorization(db, context, request, task, catalog, timestamp)
            email_slot = (
                request.action == "email.send"
                and result.reason_code == "APPROVAL_UNAVAILABLE"
                and context.approved_scope.approval_enabled
            )
            if email_slot:
                from app.services.email_profile import send_guard

                reason = send_guard(db, task)
                if reason is None and db.scalar(
                    select(GatewayOperation.operation_ref).where(
                        GatewayOperation.send_slot_task_ref == task.task_ref
                    )
                ):
                    reason = "SEND_SLOT_CLAIMED"
                if reason:
                    denied = Authorization(decision="DENY", reason_code=reason)
                    return ToolResponse(
                        **denied.model_dump(),
                        request_id=request.request_id,
                        audit_event_ref=record_decision(db, task, request, denied, timestamp),
                    )
            count = db.scalar(
                select(func.count())
                .select_from(GatewayOperation)
                .where(GatewayOperation.task_ref == task.task_ref)
            )
            if count >= 20:
                raise OperationError(429, "CAPACITY_EXCEEDED")
            operation = GatewayOperation(
                operation_ref=f"op_{uuid4().hex}",
                task_ref=task.task_ref,
                owner_id=task.owner_id,
                request_id=request.request_id,
                idempotency_key=request.idempotency_key,
                action=request.action,
                send_slot_task_ref=task.task_ref if email_slot else None,
                canonical_request_digest=wire,
                binding_digest=binding,
                authorization_version=task.authorization_version,
                revision=0,
                operation_status="ADMITTED" if result.decision == "ALLOW" else "DENIED",
                decision=result.decision,
                reason_code=result.reason_code,
                created_at=timestamp,
                updated_at=timestamp,
            )
            try:
                with db.begin_nested():
                    db.add(operation)
                    db.flush()
            except IntegrityError:
                # Reload once after rollback; never regenerate an ID or attempt another insert.
                operation = _match(_candidates(db, task, request, wire), task, request, wire)
                if operation is None:
                    raise OperationError(
                        503, "GATEWAY_UNAVAILABLE", execution_uncertain=True
                    ) from None
                _history(db, operation)
                _refresh_admitted(db, context, task, request, operation, binding, catalog, now)
                return _response(operation, _approval_state(db, task, operation, catalog, now))
            if (
                result.reason_code == "APPROVAL_UNAVAILABLE"
                and context.approved_scope.approval_enabled
            ):
                from app.services.approvals import create_pending

                create_pending(db, context, task, request, operation, timestamp)
                result = Authorization(
                    decision=operation.decision, reason_code=operation.reason_code
                )
            _audit(db, task, request, result, operation, timestamp)
        elif operation.operation_status == "ADMITTED":
            _refresh_admitted(db, context, task, request, operation, binding, catalog, now)
        approval = _approval_state(db, task, operation, catalog, now)
        if operation.operation_status in ("SUCCEEDED", "FAILED"):
            from app.services.trusted_execution import recorded_response

            response = recorded_response(db, context, task, request, operation, catalog, _utc(now))
        else:
            response = _response(operation, approval)
    return response


def get_operation_status(
    db: Session, *, token: SecretStr, request_id: str, now=None, catalog=EMPTY_CATALOG
) -> OperationStatus:
    with authenticated_task(db, token=token, task_ref=None, now=now) as (context, task):
        _isolation(db)
        operation = db.scalar(
            select(GatewayOperation)
            .where(
                GatewayOperation.owner_id == context.owner_id,
                GatewayOperation.task_ref == task.task_ref,
                GatewayOperation.request_id == request_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            operation is None
            or operation.owner_id != context.owner_id
            or operation.task_ref != task.task_ref
        ):
            raise OperationError(404, "NOT_FOUND")
        _history(db, operation)
        approval = _approval_state(db, task, operation, catalog, now)
        result = OperationStatus(
            operation_ref=operation.operation_ref,
            request_id=operation.request_id,
            task_ref=operation.task_ref,
            operation_state=operation.operation_status,
            decision=operation.decision,
            reason_code=operation.reason_code,
            execution_status="UNKNOWN"
            if operation.operation_status in ("UNKNOWN", "DISPATCHING")
            else operation.operation_status
            if operation.operation_status in ("SUCCEEDED", "FAILED")
            else "NOT_EXECUTED",
            audit_event_ref=operation.audit_event_ref,
            revision=operation.revision,
            approval_ref=approval.approval_ref if approval else None,
            approval_state=approval.status if approval else None,
            resume_ref=approval.resume_ref if approval and approval.status == "APPROVED" else None,
        )
    return result
