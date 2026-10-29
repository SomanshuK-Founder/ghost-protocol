"""Owner-managed synthetic metadata; no document reader, tool dispatch or HTTP API."""

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, Field, SecretStr, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent_schemas import IdentityModel, OwnerContext, Reference, ResourceVersion
from app.gateway_contracts import ToolRequest
from app.models import AuditEvent, DocumentResource, GatewayTask, User
from app.services.agent_identity import (
    AgentIdentityError,
    _require_owner,
    _transaction,
    _utc,
    authenticated_task,
)
from app.services.fixture_storage import FixtureError, FixtureStorage
from app.services.operation_ledger import (
    _approval_state,
    _candidates,
    _history,
    _isolation,
    _match,
    request_digests,
)
from app.services.resource_catalog import EMPTY_CATALOG, MANAGED_RESOURCE
from app.services.scoped_consent import evaluate_locked_authorization

FixtureName = Literal[
    "doc_tax_2026",
    "doc_bank_oct",
    "doc_personal_notes",
    "doc_project_report",
    "doc_meeting_oct",
    "doc_schedule",
]
DEFAULT_STORAGE = FixtureStorage()


class FixtureRegistration(IdentityModel):
    fixtures: tuple[FixtureName, ...] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.fixtures)) != len(self.fixtures):
            raise ValueError("Select each fixture once")
        return self


class ResourceMetadata(IdentityModel):
    resource_ref: Reference
    version_ref: Reference
    owner_ref: Reference
    resource_type: Literal["SYNTHETIC_TEXT"]
    display_name: str = Field(min_length=1, max_length=120)
    classification: Literal["PRIVATE_ORIGINAL", "SHAREABLE"]
    active: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @property
    def pin(self):
        return ResourceVersion(
            resource_id=self.resource_ref,
            version_ref=self.version_ref,
            classification=self.classification,
        )


class ListedResource(IdentityModel):
    resource_id: Reference
    version_ref: Reference


class AuthorizedMetadata(IdentityModel):
    resources: tuple[ListedResource, ...] = Field(max_length=100)


def _metadata(resource):
    return ResourceMetadata(
        **{name: getattr(resource, name) for name in ResourceMetadata.model_fields}
    )


def _audit(db, owner, resource, event_type, now):
    db.add(
        AuditEvent(
            user_id=owner.owner_id,
            event_type=event_type,
            outcome="RECORDED",
            created_at=now,
            detail={"resource_ref": resource.resource_ref, "timestamp": now.isoformat()},
        )
    )


def register_synthetic_resources(
    db: Session,
    *,
    owner: OwnerContext,
    selection: FixtureRegistration,
    storage=DEFAULT_STORAGE,
    now=None,
):
    _require_owner(owner)
    try:
        selection = FixtureRegistration.model_validate_json(
            selection.model_dump_json(warnings=False)
        )
    except (ValidationError, AttributeError, ValueError, TypeError):
        raise AgentIdentityError(422, "INVALID_REQUEST") from None
    # Opt-in integrity hashing is outside the DB transaction and never returns document bytes.
    try:
        verified = [storage.validate(name) for name in selection.fixtures]
    except FixtureError as exc:
        raise AgentIdentityError(422, exc.code) from None
    timestamp = _utc(now)
    with _transaction(db):
        _isolation(db)
        user = db.scalar(select(User).where(User.id == owner.owner_id).with_for_update())
        if user is None:
            db.add(User(id=owner.owner_id))
            db.flush()
        results = []
        for reference, digest, display, classification in verified:
            resource = db.scalar(
                select(DocumentResource)
                .where(
                    DocumentResource.owner_ref == owner.owner_id,
                    DocumentResource.storage_reference == reference,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if resource is not None:
                if resource.owner_ref != owner.owner_id:
                    raise AgentIdentityError(404, "NOT_FOUND")
                if not resource.active:
                    raise AgentIdentityError(409, "RESOURCE_INACTIVE")
                if (
                    resource.content_digest,
                    resource.classification,
                    resource.display_name,
                    resource.resource_type,
                ) != (digest, classification, display, "SYNTHETIC_TEXT"):
                    raise AgentIdentityError(409, "RESOURCE_CONFLICT")
            else:
                resource = DocumentResource(
                    resource_ref=f"resource_{uuid4().hex}",
                    version_ref=f"version_{uuid4().hex}",
                    owner_ref=owner.owner_id,
                    resource_type="SYNTHETIC_TEXT",
                    display_name=display,
                    classification=classification,
                    storage_reference=reference,
                    content_digest=digest,
                    active=True,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                db.add(resource)
                _audit(db, owner, resource, "catalog.resource_registered", timestamp)
                db.flush()
            results.append(_metadata(resource))
    return tuple(results)


def _owned_resource(db, owner, reference):
    _require_owner(owner)
    if not isinstance(reference, str) or not MANAGED_RESOURCE.fullmatch(reference):
        raise AgentIdentityError(404, "NOT_FOUND")
    resource = db.scalar(
        select(DocumentResource)
        .where(
            DocumentResource.resource_ref == reference, DocumentResource.owner_ref == owner.owner_id
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if resource is None or resource.owner_ref != owner.owner_id:
        raise AgentIdentityError(404, "NOT_FOUND")
    return resource


def lookup_resource(db: Session, *, owner: OwnerContext, resource_ref: str):
    _require_owner(owner)
    with _transaction(db):
        _isolation(db)
        resource = _owned_resource(db, owner, resource_ref)
        if not resource.active:
            raise AgentIdentityError(404, "NOT_FOUND")
        result = _metadata(resource)
    return result


def deactivate_resource(db: Session, *, owner: OwnerContext, resource_ref: str, now=None):
    _require_owner(owner)
    with _transaction(db):
        _isolation(db)
        # User lock serializes task creation with this owner-wide task discovery.
        db.scalar(select(User).where(User.id == owner.owner_id).with_for_update())
        tasks = list(
            db.scalars(
                select(GatewayTask)
                .where(GatewayTask.owner_id == owner.owner_id)
                .order_by(GatewayTask.task_ref)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        resource = _owned_resource(db, owner, resource_ref)
        if resource.active:
            timestamp = _utc(now)
            if timestamp < resource.created_at:
                raise AgentIdentityError(422, "INVALID_REQUEST")
            resource.active, resource.updated_at = False, timestamp
            from app.services.approvals import invalidate_approvals

            for task in tasks:
                if task.owner_id == owner.owner_id and resource_ref in task.authorization_scope.get(
                    "resource_ids", []
                ):
                    task.authorization_version += 1
                    invalidate_approvals(db, task, timestamp)
            _audit(db, owner, resource, "catalog.resource_deactivated", timestamp)
        result = _metadata(resource)
    return result


def list_authorized_metadata(
    db: Session, *, token: SecretStr, request: ToolRequest, now: datetime | None = None
):
    """Internal preview of already-admitted direct-consent listing; not a tool outcome."""
    try:
        request = ToolRequest.model_validate_json(request.model_dump_json(warnings=False))
    except (ValidationError, AttributeError, ValueError, TypeError):
        raise AgentIdentityError(422, "INVALID_REQUEST") from None
    if not isinstance(token, SecretStr):
        raise AgentIdentityError(401, "AUTH_INVALID")
    with authenticated_task(db, token=token, task_ref=request.task_ref, now=now) as (context, task):
        _isolation(db)
        if request.action != "files.list_authorized":
            raise AgentIdentityError(403, "ACTION_DISABLED")
        wire, binding = request_digests(context.owner_id, request, context.approved_scope)
        operation = _match(_candidates(db, task, request, wire), task, request, wire)
        if operation is None:
            raise AgentIdentityError(404, "NOT_FOUND")
        _history(db, operation)
        if operation.binding_digest != binding:
            raise AgentIdentityError(403, "RESOURCE_VERSION_CHANGED")
        _approval_state(db, task, operation, EMPTY_CATALOG, now)
        if operation.operation_status == "READY":
            raise AgentIdentityError(409, "RESUME_REQUIRED")
        if operation.operation_status != "ADMITTED":
            raise AgentIdentityError(403, "RESOURCE_NOT_AUTHORIZED")
        timestamp = _utc(now)
        checked = evaluate_locked_authorization(
            db, context, request, task, EMPTY_CATALOG, timestamp, operation
        )
        if checked.decision != "ALLOW":
            raise AgentIdentityError(403, checked.reason_code)
        if operation.authorization_version != task.authorization_version:
            raise AgentIdentityError(409, "NOT_RESUMABLE")
        catalog = EMPTY_CATALOG.resolve(db, context.approved_scope, task.owner_id)
        result = AuthorizedMetadata(
            resources=tuple(
                ListedResource(resource_id=pin.resource_id, version_ref=pin.version_ref)
                for pin in sorted(catalog.resources, key=lambda p: p.resource_id)
            )
        )
        db.add(
            AuditEvent(
                user_id=task.owner_id,
                event_type="catalog.metadata_listed",
                outcome="DISCLOSED",
                created_at=timestamp,
                detail={
                    "request_id": request.request_id,
                    "task_ref": task.task_ref,
                    "operation_ref": operation.operation_ref,
                    "action": request.action,
                    "timestamp": timestamp.isoformat(),
                },
            )
        )
    return result
