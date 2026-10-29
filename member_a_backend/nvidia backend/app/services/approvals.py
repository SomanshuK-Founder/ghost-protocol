"""Owner decisions and protected reference snapshots only; no resume or execution path."""

import json
import secrets
from datetime import datetime, timedelta
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import func, select

from app.agent_schemas import AuthenticatedAgentContext, OwnerContext, TaskScope
from app.gateway_contracts import ApprovalReview, Authorization, ToolRequest
from app.models import AgentCredential, AuditEvent, GatewayOperation, PendingApproval, ScopedConsent
from app.services.agent_identity import AgentIdentityError, _active, _owned_task, _transaction, _utc
from app.services.operation_ledger import (
    OperationError,
    _audit,
    _history,
    _isolation,
    request_digests,
)
from app.services.resource_catalog import EMPTY_CATALOG
from app.services.scoped_consent import evaluate_locked_authorization

TERMINAL_REASONS = {
    "REJECTED": "APPROVAL_REJECTED",
    "EXPIRED": "APPROVAL_EXPIRED",
    "REVOKED": "APPROVAL_REVOKED",
}
TRANSITIONS = {
    "PENDING": {"APPROVED", "REJECTED", "EXPIRED", "REVOKED"},
    "APPROVED": {"EXPIRED", "REVOKED"},
}


def audit_approval(db, task, approval, now, *, viewed=False, actor_role="SYSTEM"):
    event = AuditEvent(
        user_id=task.owner_id,
        event_type="gateway.approval.viewed" if viewed else "gateway.approval.transition",
        outcome=approval.status,
        created_at=now,
        detail={
            "approval_ref": approval.approval_ref,
            "operation_ref": approval.operation_ref,
            "task_ref": task.task_ref,
            "request_id": approval.request_id,
            "action": approval.action,
            "status": approval.status,
            "revision": approval.revision,
            "timestamp": now.isoformat(),
            "expires_at": approval.expires_at.isoformat(),
            "actor_role": "OWNER_CONTROL" if viewed else actor_role,
        },
    )
    db.add(event)
    db.flush()
    if not viewed:
        approval.audit_event_id = event.id


def load_approval(db, task, operation):
    approval = db.scalar(
        select(PendingApproval)
        .where(PendingApproval.operation_ref == operation.operation_ref)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if approval is None:
        raise OperationError(503, "GATEWAY_UNAVAILABLE", execution_uncertain=True)
    try:
        from app.services.email_profile import TEMPLATE_REF, arguments_for

        email = approval.action.startswith("email.")
        # No raw body store: the immutable synthetic template reconstructs exact reviewed bytes.
        arguments = (
            arguments_for(approval.recipient).model_dump(mode="json")
            if email
            else {"resource_id": approval.resource_versions[0]["resource_id"]}
            if approval.action == "files.read"
            else {}
        )
        request = ToolRequest.model_validate_json(
            json.dumps(
                {
                    "request_id": approval.request_id,
                    "task_ref": approval.task_ref,
                    "idempotency_key": approval.idempotency_key,
                    "action": approval.action,
                    "purpose": approval.purpose,
                    "arguments": arguments,
                }
            )
        )
        scope = TaskScope.model_validate_json(json.dumps(task.authorization_scope))
        wire, _ = request_digests(task.owner_id, request, scope)
        resources = (
            {request.arguments.resource_id}
            if request.action == "files.read"
            else set(scope.resource_ids)
            if request.action == "files.list_authorized"
            else set()
        )
        expected_pins = [
            pin.model_dump(mode="json")
            for pin in scope.resource_versions
            if pin.resource_id in resources
        ]
        if not (
            approval.owner_id == task.owner_id == operation.owner_id
            and approval.task_ref == task.task_ref == request.task_ref == operation.task_ref
            and approval.request_id == request.request_id == operation.request_id
            and approval.idempotency_key == request.idempotency_key == operation.idempotency_key
            and approval.action == request.action == operation.action
            and approval.purpose == request.purpose
            and approval.canonical_request_digest == wire == operation.canonical_request_digest
            and approval.binding_digest == operation.binding_digest
            and (approval.template_ref == TEMPLATE_REF if email else approval.template_ref is None)
            and (approval.recipient == scope.recipient if email else approval.recipient is None)
            and approval.expires_at <= task.expires_at
            and approval.expires_at <= approval.created_at + timedelta(minutes=10)
            and approval.resource_versions == expected_pins
        ):
            raise ValueError("Invalid immutable binding")
        events = list(
            db.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.event_type == "gateway.approval.transition",
                    AuditEvent.detail["approval_ref"].as_string() == approval.approval_ref,
                )
                .order_by(AuditEvent.id)
                .with_for_update()
            )
        )
        if len(events) != approval.revision + 1 or events[-1].id != approval.audit_event_id:
            raise ValueError("Incomplete approval history")
        previous, previous_time = None, approval.created_at
        for revision, event in enumerate(events):
            detail = event.detail
            if (
                event.user_id != task.owner_id
                or detail["operation_ref"] != operation.operation_ref
                or detail["task_ref"] != task.task_ref
                or detail["request_id"] != request.request_id
                or detail["action"] != request.action
                or detail["revision"] != revision
                or event.outcome != detail["status"]
                or datetime.fromisoformat(detail["expires_at"]) != approval.expires_at
                or datetime.fromisoformat(detail["timestamp"]) < previous_time
            ):
                raise ValueError("Invalid audit binding")
            if (previous is None and detail["status"] != "PENDING") or (
                previous is not None and detail["status"] not in TRANSITIONS.get(previous, set())
            ):
                raise ValueError("Invalid transition")
            previous = detail["status"]
            previous_time = datetime.fromisoformat(detail["timestamp"])
        if previous != approval.status:
            raise ValueError("Invalid approval snapshot")
        expected = {"PENDING": "PENDING_APPROVAL", "APPROVED": "READY"}.get(
            approval.status, "DENIED"
        )
        consumed = approval.consumed_at is not None
        if consumed and not (
            approval.status in ("APPROVED", "EXPIRED", "REVOKED")
            and approval.created_at <= approval.consumed_at < approval.expires_at
            and approval.resume_ref is None
            and operation.execution_started_at == approval.consumed_at
        ):
            raise ValueError("Invalid consumption")
        if operation.operation_status not in (
            ("DISPATCHING", "SUCCEEDED", "FAILED", "UNKNOWN") if consumed else (expected,)
        ):
            raise ValueError("Invalid ledger state")
    except (ValueError, TypeError, KeyError, IndexError, ValidationError):
        raise OperationError(503, "GATEWAY_UNAVAILABLE", execution_uncertain=True) from None
    return approval, request


def create_pending(db, context, task, request, operation, now):
    if not context.approved_scope.approval_enabled:
        return
    count = db.scalar(
        select(func.count())
        .select_from(PendingApproval)
        .where(
            PendingApproval.task_ref == task.task_ref,
            PendingApproval.status.in_(("PENDING", "APPROVED")),
            PendingApproval.consumed_at.is_(None),
            PendingApproval.expires_at > now,
        )
    )
    if count >= 5:
        raise OperationError(429, "CAPACITY_EXCEEDED")
    resources = (
        {request.arguments.resource_id}
        if request.action == "files.read"
        else set(context.approved_scope.resource_ids)
        if request.action == "files.list_authorized"
        else set()
    )
    approval = PendingApproval(
        approval_ref=f"approval_{uuid4().hex}",
        operation_ref=operation.operation_ref,
        task_ref=task.task_ref,
        owner_id=task.owner_id,
        request_id=request.request_id,
        idempotency_key=request.idempotency_key,
        action=request.action,
        purpose=request.purpose,
        canonical_request_digest=operation.canonical_request_digest,
        binding_digest=operation.binding_digest,
        resource_versions=[
            pin.model_dump(mode="json")
            for pin in context.approved_scope.resource_versions
            if pin.resource_id in resources
        ],
        recipient=request.arguments.recipient if request.action.startswith("email.") else None,
        template_ref="synthetic_mail_v1" if request.action.startswith("email.") else None,
        status="PENDING",
        created_at=now,
        expires_at=min(now + timedelta(minutes=10), task.expires_at),
        authorization_version=task.authorization_version,
        revision=0,
    )
    operation.operation_status, operation.decision = "PENDING_APPROVAL", "APPROVAL_REQUIRED"
    operation.reason_code = "CONSENT_REVIEW_REQUIRED"
    audit_approval(db, task, approval, now, actor_role="AGENT_EXECUTOR")
    db.add(approval)


def transition(db, task, operation, approval, request, target, now, *, owner=None):
    if target not in TRANSITIONS.get(approval.status, set()):
        raise OperationError(409, "APPROVAL_ALREADY_RESOLVED")
    approval.status, approval.revision = target, approval.revision + 1
    approval.decided_at = approval.decided_at or now
    approval.resolved_by = owner.owner_id if owner else approval.resolved_by
    consumed = approval.consumed_at is not None
    if not consumed:
        operation.operation_status = "READY" if target == "APPROVED" else "DENIED"
    if target == "APPROVED":
        result = Authorization(decision="APPROVAL_REQUIRED", reason_code="CONSENT_REVIEW_REQUIRED")
    else:
        approval.resume_ref = None
        if approval.consent_ref:
            # Do not flush a partially updated operation/approval pair during lookup.
            with db.no_autoflush:
                consent = db.get(ScopedConsent, approval.consent_ref, populate_existing=True)
            if consent is None or consent.bound_operation_ref != operation.operation_ref:
                raise OperationError(503, "GATEWAY_UNAVAILABLE")
            if consent.revoked_at is None:
                consent.revoked_at, consent.version = now, consent.version + 1
        result = Authorization(decision="DENY", reason_code=TERMINAL_REASONS[target])
    if not consumed:
        operation.decision, operation.reason_code = result.decision, result.reason_code
        operation.revision += 1
        operation.updated_at = now
        operation.authorization_version = task.authorization_version
    approval.authorization_version = task.authorization_version
    audit_approval(db, task, approval, now, actor_role="OWNER_CONTROL" if owner else "SYSTEM")
    if not consumed:
        _audit(db, task, request, result, operation, now)


def reconcile(db, task, operation, approval, request, catalog, now):
    if approval.status not in ("PENDING", "APPROVED"):
        return
    scope = TaskScope.model_validate_json(json.dumps(task.authorization_scope))
    _, binding = request_digests(task.owner_id, request, scope)
    catalog = catalog.resolve(db, scope, task.owner_id)
    if now >= approval.expires_at:
        transition(db, task, operation, approval, request, "EXPIRED", now)
    elif (
        not _active(task, now)
        or approval.authorization_version != task.authorization_version
        or not catalog.validates(scope, task.owner_id)
        or binding != approval.binding_digest
    ):
        transition(db, task, operation, approval, request, "REVOKED", now)
    elif approval.status == "APPROVED":
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
            transition(db, task, operation, approval, request, "REVOKED", now)
        else:
            context = AuthenticatedAgentContext(
                credential_ref=credential.credential_ref,
                owner_id=task.owner_id,
                task_ref=task.task_ref,
                credential_expires_at=credential.expires_at,
                approved_scope=scope,
            )
            checked = evaluate_locked_authorization(
                db, context, request, task, catalog, now, operation
            )
            if checked.decision != "ALLOW":
                transition(db, task, operation, approval, request, "REVOKED", now)


def invalidate_approvals(db, task, now):
    """Called while the existing authority mutation holds the trusted task lock."""
    operations = list(
        db.scalars(
            select(GatewayOperation)
            .where(
                GatewayOperation.task_ref == task.task_ref,
                GatewayOperation.operation_status.in_(("PENDING_APPROVAL", "READY")),
            )
            .order_by(GatewayOperation.operation_ref)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    for operation in operations:
        _history(db, operation)
        approval, request = load_approval(db, task, operation)
        transition(
            db,
            task,
            operation,
            approval,
            request,
            "EXPIRED" if now >= approval.expires_at else "REVOKED",
            now,
        )


def _owner_operation(db, owner, approval_ref):
    if not isinstance(owner, OwnerContext):
        raise AgentIdentityError(403, "ROLE_FORBIDDEN")
    # Discovery conveys no authority; re-read everything after acquiring the task lock.
    task_ref = db.scalar(
        select(PendingApproval.task_ref).where(
            PendingApproval.approval_ref == approval_ref, PendingApproval.owner_id == owner.owner_id
        )
    )
    if task_ref is None:
        raise AgentIdentityError(404, "NOT_FOUND")
    task = _owned_task(db, owner, task_ref)
    operation = db.scalar(
        select(GatewayOperation)
        .join(PendingApproval, PendingApproval.operation_ref == GatewayOperation.operation_ref)
        .where(
            PendingApproval.approval_ref == approval_ref,
            GatewayOperation.owner_id == owner.owner_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if operation is None:
        raise OperationError(503, "GATEWAY_UNAVAILABLE")
    _history(db, operation)
    approval, request = load_approval(db, task, operation)
    return task, operation, approval, request


def _owner_approval_locked(
    db, *, owner, approval_ref, resolution=None, revoke=False, catalog=EMPTY_CATALOG, now=None
):
    error = None
    _isolation(db)
    task, operation, approval, request = _owner_operation(db, owner, approval_ref)
    timestamp = _utc(now)
    reconcile(db, task, operation, approval, request, catalog, timestamp)
    if resolution is None and not revoke:
        audit_approval(db, task, approval, timestamp, viewed=True)
    else:
        target = (
            "REVOKED" if revoke else {"APPROVE": "APPROVED", "REJECT": "REJECTED"}.get(resolution)
        )
        if target is None:
            raise OperationError(422, "INVALID_REQUEST")
        if approval.status == target:
            pass  # Identical owner decisions are idempotent.
        elif target not in TRANSITIONS.get(approval.status, set()):
            error = OperationError(409, "APPROVAL_ALREADY_RESOLVED")
        else:
            if target == "APPROVED":
                credential = db.scalar(
                    select(AgentCredential)
                    .where(
                        AgentCredential.task_ref == task.task_ref,
                        AgentCredential.owner_id == task.owner_id,
                        AgentCredential.credential_epoch == task.credential_epoch,
                        AgentCredential.revoked_at.is_(None),
                        AgentCredential.issued_at <= timestamp,
                        AgentCredential.expires_at > timestamp,
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if credential is None:
                    transition(db, task, operation, approval, request, "REVOKED", timestamp)
                    error = OperationError(409, "APPROVAL_ALREADY_RESOLVED")
                else:
                    context = AuthenticatedAgentContext(
                        credential_ref=credential.credential_ref,
                        task_ref=task.task_ref,
                        owner_id=task.owner_id,
                        credential_expires_at=credential.expires_at,
                        approved_scope=TaskScope.model_validate_json(
                            json.dumps(task.authorization_scope)
                        ),
                    )
                    checked = evaluate_locked_authorization(
                        db, context, request, task, catalog, timestamp
                    )
                    from app.services.email_profile import send_guard

                    blocked = (
                        send_guard(db, task, operation.operation_ref)
                        if request.action == "email.send"
                        else None
                    )
                    if checked.reason_code != "APPROVAL_UNAVAILABLE" or blocked:
                        transition(db, task, operation, approval, request, "REVOKED", timestamp)
                        error = OperationError(409, "APPROVAL_ALREADY_RESOLVED")
                    else:
                        consent = ScopedConsent(
                            consent_ref=f"consent_{uuid4().hex}",
                            task_ref=task.task_ref,
                            owner_id=task.owner_id,
                            action=request.action,
                            purpose=request.purpose,
                            resource_versions=approval.resource_versions,
                            recipient=approval.recipient,
                            payload_digest=operation.canonical_request_digest
                            if request.action.startswith("email.")
                            else None,
                            created_at=timestamp,
                            valid_from=timestamp,
                            expires_at=approval.expires_at,
                            version=1,
                            bound_operation_ref=operation.operation_ref,
                        )
                        db.add(consent)
                        db.flush()
                        approval.consent_ref = consent.consent_ref
                        approval.resume_ref = f"resume_{secrets.token_urlsafe(32)}"
                        task.authorization_version += 1
            if error is None:
                if target == "REVOKED":
                    task.authorization_version += 1
                transition(db, task, operation, approval, request, target, timestamp, owner=owner)
    if resolution is None and not revoke:
        result = ApprovalReview(
            approval_ref=approval.approval_ref,
            operation_ref=operation.operation_ref,
            request_id=request.request_id,
            task_ref=task.task_ref,
            action=request.action,
            purpose=request.purpose,
            arguments=request.arguments,
            resource_versions=tuple(approval.resource_versions),
            binding_digest=approval.binding_digest,
            state=approval.status,
            expires_at=approval.expires_at,
        )
    else:
        result = {
            "approval_ref": approval.approval_ref,
            "state": approval.status,
            "expires_at": approval.expires_at,
            "audit_event_ref": f"event_{approval.audit_event_id}",
        }
        if revoke:
            result["in_flight"] = operation.operation_status in ("DISPATCHING", "UNKNOWN")
    return result, error


def owner_approval(
    db, *, owner, approval_ref, resolution=None, revoke=False, catalog=EMPTY_CATALOG, now=None
):
    with _transaction(db):
        result, error = _owner_approval_locked(
            db,
            owner=owner,
            approval_ref=approval_ref,
            resolution=resolution,
            revoke=revoke,
            catalog=catalog,
            now=now,
        )
    if error:
        raise error
    return result


def list_pending(db, *, owner, task_ref, catalog=EMPTY_CATALOG, now=None):
    with _transaction(db):
        _isolation(db)
        task = _owned_task(db, owner, task_ref)
        timestamp = _utc(now)
        operations = list(
            db.scalars(
                select(GatewayOperation)
                .where(
                    GatewayOperation.task_ref == task.task_ref,
                    GatewayOperation.operation_status.in_(("PENDING_APPROVAL", "READY")),
                )
                .order_by(GatewayOperation.operation_ref)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        result = []
        for operation in operations:
            _history(db, operation)
            approval, request = load_approval(db, task, operation)
            reconcile(db, task, operation, approval, request, catalog, timestamp)
            if approval.status == "PENDING":
                audit_approval(db, task, approval, timestamp, viewed=True)
                result.append(
                    {
                        "approval_ref": approval.approval_ref,
                        "operation_ref": operation.operation_ref,
                        "request_id": request.request_id,
                        "state": approval.status,
                        "expires_at": approval.expires_at,
                    }
                )
    return {"approvals": result}
