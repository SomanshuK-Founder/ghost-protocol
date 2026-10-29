"""Deterministic authorization and owner-only grants; no tool dispatcher exists here."""

import json
from datetime import datetime
from uuid import uuid4

from pydantic import SecretStr, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent_schemas import AuthenticatedAgentContext, OwnerContext, ResourceVersion, TaskScope
from app.gateway_contracts import Authorization, ConsentCreate, ToolRequest, ToolResponse
from app.models import AuditEvent, GatewayOperation, GatewayTask, PendingApproval, ScopedConsent
from app.services.agent_identity import (
    AgentIdentityError,
    _active,
    _owned_task,
    _transaction,
    _utc,
    authenticated_task,
)
from app.services.resource_catalog import EMPTY_CATALOG, ResourceCatalog

PINS = TypeAdapter(tuple[ResourceVersion, ...])


def deny(reason: str) -> Authorization:
    return Authorization(decision="DENY", reason_code=reason)


def evaluate_authorization(
    context: AuthenticatedAgentContext | None,
    request: ToolRequest,
    task: GatewayTask,
    consents: list[ScopedConsent],
    *,
    catalog: ResourceCatalog = EMPTY_CATALOG,
    now: datetime,
    operation: GatewayOperation | None = None,
    approval: PendingApproval | None = None,
) -> Authorization:
    """Pure snapshot evaluation. Callers must authenticate and serialize DB reads first."""
    now = _utc(now)
    if not isinstance(context, AuthenticatedAgentContext) or context.credential_expires_at <= now:
        return deny("AUTH_INVALID")
    if not isinstance(request, ToolRequest):
        return deny("ACTION_DISABLED")
    if (
        request.task_ref != context.task_ref
        or task.task_ref != context.task_ref
        or task.owner_id != context.owner_id
    ):
        return deny("TASK_SCOPE_MISMATCH")
    if not _active(task, now):
        return deny("TASK_NOT_ACTIVE")
    try:
        scope = TaskScope.model_validate_json(json.dumps(task.authorization_scope))
    except (ValidationError, TypeError, ValueError):
        return deny("TASK_NOT_ACTIVE")
    if scope != context.approved_scope:
        return deny("TASK_SCOPE_MISMATCH")
    if request.purpose != scope.purpose:
        return deny("PURPOSE_MISMATCH")
    if request.action not in scope.allowed_actions:
        return deny("ACTION_DISABLED")
    email = request.action.startswith("email.")
    if email:
        from app.services.email_profile import email_scope_reason

        reason = email_scope_reason(task.owner_id, scope, request)
        if reason:
            return deny(reason)
    if not catalog.validates(scope, task.owner_id):
        return deny("RESOURCE_VERSION_CHANGED")
    if request.action == "files.read":
        resource_ids = {request.arguments.resource_id}
        if not resource_ids <= set(scope.resource_ids):
            return deny("RESOURCE_NOT_AUTHORIZED")
    elif request.action == "files.list_authorized":
        resource_ids = set(scope.resource_ids)
    else:
        resource_ids = set()
    expected = {
        pin.resource_id: pin for pin in scope.resource_versions if pin.resource_id in resource_ids
    }
    matches = []
    for consent in consents:
        if consent.bound_operation_ref is not None:
            if operation is None or consent.bound_operation_ref != operation.operation_ref:
                continue
            if (
                approval is None
                or approval.status != "APPROVED"
                or approval.operation_ref != operation.operation_ref
                or approval.consent_ref != consent.consent_ref
                or approval.owner_id != task.owner_id
                or approval.task_ref != task.task_ref
                or approval.authorization_version != task.authorization_version
                or operation.authorization_version != task.authorization_version
                or approval.request_id != request.request_id
                or approval.idempotency_key != request.idempotency_key
                or approval.canonical_request_digest != operation.canonical_request_digest
            ):
                return deny("APPROVAL_REVOKED")
            if not approval.created_at <= now < approval.expires_at:
                return deny("APPROVAL_EXPIRED")
        if (consent.owner_id, consent.task_ref, consent.action, consent.purpose) != (
            task.owner_id,
            task.task_ref,
            request.action,
            request.purpose,
        ):
            continue
        try:
            pins = PINS.validate_json(json.dumps(consent.resource_versions))
        except (ValidationError, ValueError, TypeError):
            return deny("CONSENT_AMBIGUOUS")
        if len({pin.resource_id for pin in pins}) != len(pins):
            return deny("CONSENT_AMBIGUOUS")
        if {pin.resource_id for pin in pins} != resource_ids:
            continue
        if consent.recipient != (request.arguments.recipient if email else None):
            return deny("RECIPIENT_NOT_AUTHORIZED")
        if email and (
            operation is None
            or consent.bound_operation_ref != operation.operation_ref
            or consent.payload_digest != operation.canonical_request_digest
        ):
            return deny("EMAIL_CONTENT_NOT_AUTHORIZED")
        if {pin.resource_id: pin for pin in pins} != expected:
            return deny("RESOURCE_VERSION_CHANGED")
        matches.append(consent)
    if any(item.revoked_at is not None for item in matches):
        return deny("CONSENT_REVOKED")
    if any(not item.valid_from <= now < item.expires_at for item in matches):
        return deny("CONSENT_EXPIRED")
    if any(
        item.expires_at > task.expires_at or item.valid_from < item.created_at for item in matches
    ):
        return deny("CONSENT_AMBIGUOUS")
    if len(matches) > 1:
        return deny("CONSENT_AMBIGUOUS")
    if not matches:
        return deny("APPROVAL_UNAVAILABLE")
    return Authorization(decision="ALLOW", reason_code="EXECUTION_NOT_STARTED")


def record_decision(
    db: Session,
    task: GatewayTask,
    request: ToolRequest,
    result: Authorization,
    now: datetime,
    operation: GatewayOperation | None = None,
) -> str:
    event = AuditEvent(
        user_id=task.owner_id,
        event_type="gateway.authorization",
        outcome=result.decision,
        created_at=now,
        detail={
            "request_id": request.request_id,
            "task_ref": task.task_ref,
            "action": request.action,
            "decision": result.decision,
            "reason_code": result.reason_code,
            "timestamp": now.isoformat(),
        },
    )
    if operation is not None:
        event.detail = {
            **event.detail,
            "operation_ref": operation.operation_ref,
            "operation_state": operation.operation_status,
            "revision": operation.revision,
            "authorization_version": operation.authorization_version,
        }
    db.add(event)
    db.flush()
    return f"event_{event.id}"


def evaluate_locked_authorization(
    db, context, request, task, catalog, now, operation=None
) -> Authorization:
    catalog = catalog.resolve(db, context.approved_scope, task.owner_id)
    consents = list(
        db.scalars(
            select(ScopedConsent)
            .where(ScopedConsent.task_ref == task.task_ref, ScopedConsent.owner_id == task.owner_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    approval = (
        None
        if operation is None
        else db.scalar(
            select(PendingApproval)
            .where(PendingApproval.operation_ref == operation.operation_ref)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    return evaluate_authorization(
        context,
        request,
        task,
        consents,
        catalog=catalog,
        now=now,
        operation=operation,
        approval=approval,
    )


def authorize_request(
    db: Session,
    *,
    token: SecretStr,
    request: ToolRequest,
    catalog: ResourceCatalog = EMPTY_CATALOG,
    now: datetime | None = None,
) -> ToolResponse:
    with authenticated_task(db, token=token, task_ref=request.task_ref, now=now) as (context, task):
        timestamp = _utc(now)
        result = evaluate_locked_authorization(db, context, request, task, catalog, timestamp)
        audit_ref = record_decision(db, task, request, result, timestamp)
        response = ToolResponse(
            **result.model_dump(), request_id=request.request_id, audit_event_ref=audit_ref
        )
    return response


def create_scoped_consent(
    db: Session,
    *,
    owner: OwnerContext,
    task_ref: str,
    payload: ConsentCreate,
    catalog: ResourceCatalog = EMPTY_CATALOG,
    now: datetime | None = None,
) -> ScopedConsent:
    with _transaction(db):
        task = _owned_task(db, owner, task_ref)
        timestamp = _utc(now)
        try:
            scope = TaskScope.model_validate_json(json.dumps(task.authorization_scope))
            payload = ConsentCreate.model_validate_json(payload.model_dump_json())
        except (ValidationError, TypeError, ValueError):
            raise AgentIdentityError(422, "INVALID_REQUEST") from None
        if not _active(task, timestamp):
            raise AgentIdentityError(403, "TASK_NOT_ACTIVE")
        catalog = catalog.resolve(db, scope, task.owner_id)
        if (
            payload.purpose != scope.purpose
            or payload.action not in scope.allowed_actions
            or not set(payload.resource_ids) <= set(scope.resource_ids)
            or (
                payload.action == "files.list_authorized"
                and set(payload.resource_ids) != set(scope.resource_ids)
            )
            or not catalog.validates(scope, task.owner_id)
            or not timestamp < payload.expires_at <= task.expires_at
        ):
            raise AgentIdentityError(422, "INVALID_REQUEST")
        consent = ScopedConsent(
            consent_ref=f"consent_{uuid4().hex}",
            task_ref=task.task_ref,
            owner_id=task.owner_id,
            action=payload.action,
            purpose=payload.purpose,
            resource_versions=[
                pin.model_dump(mode="json")
                for pin in scope.resource_versions
                if pin.resource_id in payload.resource_ids
            ],
            recipient=None,
            created_at=timestamp,
            valid_from=timestamp,
            expires_at=payload.expires_at,
            version=1,
        )
        db.add(consent)
        task.authorization_version += 1
    return consent


def revoke_scoped_consent(
    db: Session,
    *,
    owner: OwnerContext,
    task_ref: str,
    consent_ref: str,
    now: datetime | None = None,
) -> bool:
    with _transaction(db):
        task = _owned_task(db, owner, task_ref)
        consent = db.get(ScopedConsent, consent_ref, populate_existing=True)
        if (
            consent is None
            or consent.task_ref != task.task_ref
            or consent.owner_id != owner.owner_id
        ):
            raise AgentIdentityError(404, "NOT_FOUND")
        if consent.revoked_at is None:
            consent.revoked_at = _utc(now)
            consent.version += 1
            task.authorization_version += 1
            from app.services.approvals import invalidate_approvals

            invalidate_approvals(db, task, _utc(now))
        in_flight = (
            db.scalar(
                select(GatewayOperation.operation_ref).where(
                    GatewayOperation.task_ref == task.task_ref,
                    GatewayOperation.operation_status.in_(("DISPATCHING", "UNKNOWN")),
                )
            )
            is not None
        )
    return in_flight
