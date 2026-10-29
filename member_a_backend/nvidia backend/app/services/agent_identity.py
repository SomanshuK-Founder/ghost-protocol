"""Trusted backend-only lifecycle. Each call owns a fresh Session transaction."""

import hashlib
import hmac
import json
import re
import secrets
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pydantic import SecretStr, ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent_schemas import (
    AuthenticatedAgentContext,
    IssuedAgentCredential,
    OwnerContext,
    TaskScope,
)
from app.models import AgentCredential, GatewayTask, User
from app.services.resource_catalog import EMPTY_CATALOG, ResourceCatalog

TOKEN_PATTERN = re.compile(r"gpa_(cred_[0-9a-f]{32})\.[A-Za-z0-9_-]{43}", re.ASCII)
TASK_LIFETIME = timedelta(minutes=60)
CREDENTIAL_LIFETIME = timedelta(minutes=15)


class AgentIdentityError(Exception):
    def __init__(self, status_code: int, code: str):
        self.status_code = status_code
        self.code = code
        super().__init__(code)


@contextmanager
def _transaction(db: Session):
    try:
        with db.begin():
            connection = db.connection()
            if (
                connection.dialect.name == "sqlite"
                and not connection.connection.driver_connection.in_transaction
            ):
                # Legacy sqlite3 SELECT/SAVEPOINT do not reliably start an outer transaction.
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            yield
    except SQLAlchemyError:
        # Never chain SQL/parameters or connection details into public errors/logs.
        raise AgentIdentityError(503, "GATEWAY_UNAVAILABLE") from None


def _utc(now: datetime | None) -> datetime:
    value = now if now is not None else datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("An aware timestamp is required")
    return value.astimezone(UTC)


def _task(db: Session, task_ref: str) -> GatewayTask | None:
    return db.scalar(
        select(GatewayTask)
        .where(GatewayTask.task_ref == task_ref)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _owned_task(db: Session, owner: OwnerContext, task_ref: str) -> GatewayTask:
    _require_owner(owner)
    task = _task(db, task_ref)
    if task is None or task.task_ref != task_ref or task.owner_id != owner.owner_id:
        raise AgentIdentityError(404, "NOT_FOUND")
    return task


def _require_owner(owner: OwnerContext) -> None:
    if not isinstance(owner, OwnerContext):
        raise AgentIdentityError(403, "ROLE_FORBIDDEN")


def _active(task: GatewayTask, now: datetime) -> bool:
    return (
        task.status == "OPEN"
        and task.revoked_at is None
        and task.created_at <= now < task.expires_at
    )


def _task_creation_input(owner, scope, expires_at, now):
    _require_owner(owner)
    timestamp, expiry = _utc(now), _utc(expires_at)
    if not timestamp < expiry <= timestamp + TASK_LIFETIME:
        raise ValueError("Task lifetime must be positive and at most 60 minutes")
    scope = TaskScope.model_validate_json(scope.model_dump_json())
    if scope.recipient is not None:
        from app.services.email_profile import recipient_allowed

        if not recipient_allowed(owner.owner_id, scope.recipient) or scope.resource_ids:
            raise ValueError("Only configured synthetic email scope is supported")
    return timestamp, expiry, scope


def _insert_task_locked(db, *, owner, scope, timestamp, expiry, catalog):
    user = db.scalar(select(User).where(User.id == owner.owner_id).with_for_update())
    if user is None:
        db.add(User(id=owner.owner_id))
        db.flush()
    if not catalog.resolve(db, scope, owner.owner_id).validates(scope, owner.owner_id):
        raise ValueError("Task resources must match the trusted owner catalog")
    task = GatewayTask(
        task_ref=f"task_{uuid4().hex}",
        owner_id=owner.owner_id,
        created_at=timestamp,
        expires_at=expiry,
        status="OPEN",
        authorization_scope=scope.model_dump(mode="json"),
        credential_epoch=0,
    )
    db.add(task)
    return task


def _create_task_locked(db, *, owner, scope, expires_at, now=None, catalog=EMPTY_CATALOG):
    """Shared validated write unit; caller owns the transaction."""
    timestamp, expiry, scope = _task_creation_input(owner, scope, expires_at, now)
    return _insert_task_locked(
        db, owner=owner, scope=scope, timestamp=timestamp, expiry=expiry, catalog=catalog
    )


def create_trusted_task(
    db: Session,
    *,
    owner: OwnerContext,
    scope: TaskScope,
    expires_at: datetime,
    now: datetime | None = None,
    catalog: ResourceCatalog = EMPTY_CATALOG,
) -> GatewayTask:
    """Owner must come from authenticated backend composition, never agent JSON."""
    timestamp, expiry, scope = _task_creation_input(owner, scope, expires_at, now)
    with _transaction(db):
        return _insert_task_locked(
            db, owner=owner, scope=scope, timestamp=timestamp, expiry=expiry, catalog=catalog
        )


def issue_agent_credential(
    db: Session,
    *,
    owner: OwnerContext,
    task_ref: str,
    now: datetime | None = None,
) -> IssuedAgentCredential:
    """Issuance also rotates: task lock + epoch + old-token revocation, one commit."""
    with _transaction(db):
        task = _owned_task(db, owner, task_ref)
        timestamp = _utc(now)
        if not _active(task, timestamp):
            raise AgentIdentityError(403, "TASK_NOT_ACTIVE")
        task.credential_epoch += 1
        db.execute(
            update(AgentCredential)
            .where(
                AgentCredential.task_ref == task.task_ref,
                AgentCredential.revoked_at.is_(None),
            )
            .values(revoked_at=timestamp)
        )
        credential_ref = f"cred_{uuid4().hex}"
        token = f"gpa_{credential_ref}.{secrets.token_urlsafe(32)}"
        expiry = min(timestamp + CREDENTIAL_LIFETIME, task.expires_at)
        db.add(
            AgentCredential(
                credential_ref=credential_ref,
                token_digest=hashlib.sha256(token.encode("ascii")).hexdigest(),
                task_ref=task.task_ref,
                owner_id=task.owner_id,
                credential_epoch=task.credential_epoch,
                issued_at=timestamp,
                expires_at=expiry,
            )
        )
        result = IssuedAgentCredential(
            credential_ref=credential_ref,
            task_ref=task.task_ref,
            expires_at=expiry,
            token=SecretStr(token),
        )
    return result


def rotate_agent_credential(
    db: Session,
    *,
    owner: OwnerContext,
    task_ref: str,
    now: datetime | None = None,
) -> IssuedAgentCredential:
    return issue_agent_credential(db, owner=owner, task_ref=task_ref, now=now)


def revoke_agent_credential(
    db: Session,
    *,
    owner: OwnerContext,
    task_ref: str,
    credential_ref: str,
    now: datetime | None = None,
) -> None:
    timestamp = _utc(now)
    with _transaction(db):
        task = _owned_task(db, owner, task_ref)
        credential = db.get(AgentCredential, credential_ref, populate_existing=True)
        if credential is None or credential.task_ref != task.task_ref:
            raise AgentIdentityError(404, "NOT_FOUND")
        if credential.revoked_at is None:
            credential.revoked_at = timestamp
            task.authorization_version += 1
            from app.services.approvals import invalidate_approvals

            invalidate_approvals(db, task, timestamp)


def _revoke_task_locked(db, *, owner, task_ref, timestamp):
    task = _owned_task(db, owner, task_ref)
    if task.revoked_at is None:
        task.revoked_at, task.status = timestamp, "CANCELLED"
        task.credential_epoch += 1
        task.authorization_version += 1
        db.execute(
            update(AgentCredential)
            .where(
                AgentCredential.task_ref == task_ref,
                AgentCredential.revoked_at.is_(None),
            )
            .values(revoked_at=timestamp)
        )
        from app.services.approvals import invalidate_approvals

        invalidate_approvals(db, task, timestamp)


def revoke_trusted_task(
    db: Session,
    *,
    owner: OwnerContext,
    task_ref: str,
    now: datetime | None = None,
) -> None:
    timestamp = _utc(now)
    with _transaction(db):
        _revoke_task_locked(db, owner=owner, task_ref=task_ref, timestamp=timestamp)


def validate_agent_credential(
    db: Session,
    *,
    token: SecretStr,
    task_ref: str,
    now: datetime | None = None,
) -> AuthenticatedAgentContext:
    with authenticated_task(db, token=token, task_ref=task_ref, now=now) as (context, _):
        return context


@contextmanager
def authenticated_task(
    db: Session,
    *,
    token: SecretStr,
    task_ref: str | None,
    now: datetime | None = None,
):
    """Hold the authentication/task lock through policy evaluation and audit commit."""
    raw_token = token.get_secret_value()
    match = TOKEN_PATTERN.fullmatch(raw_token)
    if match is None:
        raise AgentIdentityError(401, "AUTH_INVALID")
    digest = hashlib.sha256(raw_token.encode("ascii")).hexdigest()
    with _transaction(db):
        credential = db.get(AgentCredential, match[1], populate_existing=True)
        if credential is None or not hmac.compare_digest(
            credential.token_digest.encode(), digest.encode()
        ):
            raise AgentIdentityError(401, "AUTH_INVALID")
        # Lock task first, then refresh credential, matching every authority mutation.
        task = _task(db, credential.task_ref)
        credential = db.scalar(
            select(AgentCredential)
            .where(AgentCredential.credential_ref == match[1])
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        timestamp = _utc(now)
        if (
            task is None
            or credential is None
            or not hmac.compare_digest(credential.token_digest.encode(), digest.encode())
            or credential.owner_id != task.owner_id
            or credential.revoked_at is not None
            or credential.credential_epoch != task.credential_epoch
            or not credential.issued_at <= timestamp < credential.expires_at
            or credential.expires_at > task.expires_at
            or not _active(task, timestamp)
        ):
            raise AgentIdentityError(401, "AUTH_INVALID")
        if task_ref is not None and task.task_ref != task_ref:
            raise AgentIdentityError(403, "TASK_SCOPE_MISMATCH")
        try:
            scope = TaskScope.model_validate_json(json.dumps(task.authorization_scope))
        except (ValidationError, TypeError, ValueError):
            raise AgentIdentityError(401, "AUTH_INVALID") from None
        result = AuthenticatedAgentContext(
            credential_ref=credential.credential_ref,
            task_ref=task.task_ref,
            owner_id=task.owner_id,
            credential_expires_at=credential.expires_at,
            approved_scope=scope,
        )
        yield result, task
