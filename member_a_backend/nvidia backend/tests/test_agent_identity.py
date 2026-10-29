import ast
import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import pytest
from app.agent_auth import get_authenticated_agent_context, get_authenticated_owner_context
from app.agent_schemas import AuthenticatedAgentContext, OwnerContext, TaskScope
from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.models import AgentCredential, GatewayTask
from app.services.agent_identity import (
    AgentIdentityError,
    create_trusted_task,
    issue_agent_credential,
    revoke_agent_credential,
    revoke_trusted_task,
    rotate_agent_credential,
    validate_agent_credential,
)
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)
OWNER = OwnerContext(owner_id="local-user")
OTHER = OwnerContext(owner_id="other-owner")
SCOPE = TaskScope(purpose="morning_brief", allowed_actions=("tasks.list",))


@pytest.fixture
def identity_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        hide_parameters=True,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


def make_task(factory, owner=OWNER, expiry=NOW + timedelta(hours=1)):
    with factory() as db:
        return create_trusted_task(db, owner=owner, scope=SCOPE, expires_at=expiry, now=NOW)


def issue(factory, task_ref, owner=OWNER, now=NOW):
    with factory() as db:
        return issue_agent_credential(db, owner=owner, task_ref=task_ref, now=now)


@pytest.fixture
def bound(identity_db):
    task = make_task(identity_db)
    return task, issue(identity_db, task.task_ref)


def validate(factory, issued, task_ref, now=NOW):
    with factory() as db:
        return validate_agent_credential(db, token=issued.token, task_ref=task_ref, now=now)


def assert_denied(factory, issued, task_ref, now=NOW, status=401):
    with pytest.raises(AgentIdentityError) as failure:
        validate(factory, issued, task_ref, now)
    assert failure.value.status_code == status
    return failure.value.code


@pytest.fixture
def probe(identity_db, monkeypatch):
    # Test-only routes exercise dependency composition; none are registered in app.main.
    test_app = FastAPI()
    monkeypatch.setenv("API_BEARER_TOKEN", "test-owner-token")
    get_settings.cache_clear()

    def db_override():
        with identity_db() as db:
            yield db

    test_app.dependency_overrides[get_db] = db_override

    @test_app.get("/identity/{task_ref}")
    def identity(
        context: Annotated[AuthenticatedAgentContext, Depends(get_authenticated_agent_context)],
    ):
        return context

    @test_app.get("/owner")
    def owner(context: Annotated[OwnerContext, Depends(get_authenticated_owner_context)]):
        return context

    with TestClient(test_app) as client:
        yield client
    get_settings.cache_clear()


def test_valid_credential_derives_only_persisted_identity(identity_db, bound):
    task, issued = bound
    context = validate(identity_db, issued, task.task_ref)
    assert context == AuthenticatedAgentContext(
        credential_ref=issued.credential_ref,
        task_ref=task.task_ref,
        owner_id=OWNER.owner_id,
        credential_expires_at=issued.expires_at,
        approved_scope=SCOPE,
    )
    assert task.task_ref.startswith("task_") and len(task.task_ref) == 37
    assert task.created_at == NOW and task.status == "OPEN"


def test_dependency_returns_context_and_ignores_spoofed_identity(probe, identity_db):
    # Use real time here because the actual dependency owns its clock.
    now = datetime.now(UTC)
    with identity_db() as db:
        task = create_trusted_task(
            db,
            owner=OWNER,
            scope=SCOPE,
            expires_at=now + timedelta(minutes=10),
            now=now,
        )
    issued = issue(identity_db, task.task_ref, now=now)
    response = probe.get(
        f"/identity/{task.task_ref}?user_id=other-owner&role=OWNER_CONTROL",
        headers={
            "Authorization": f"Bearer {issued.token.get_secret_value()}",
            "X-User-Id": "other-owner",
        },
    )
    assert response.status_code == 200
    assert response.json()["owner_id"] == "local-user"
    assert response.json()["approved_scope"]["allowed_actions"] == ["tasks.list"]
    assert issued.token.get_secret_value() not in response.text


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "",
        "Basic ignored",
        "Bearer",
        "Bearer ",
        "Bearer bad",
        "Bearer test-owner-token",
        "Bearer \N{SNOWMAN}",
    ],
)
def test_dependency_missing_invalid_and_owner_credentials_fail_closed(probe, authorization):
    headers = {} if authorization is None else {"Authorization": authorization}
    if authorization and not authorization.isascii():
        headers = [(b"authorization", authorization.encode())]
    response = probe.get("/identity/task_unknown", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("token", ["", "unknown", "gpa_cred_" + "0" * 32 + "." + "a" * 43])
def test_invalid_credential(identity_db, bound, token):
    task, _ = bound
    with identity_db() as db, pytest.raises(AgentIdentityError, match="AUTH_INVALID"):
        validate_agent_credential(db, token=SecretStr(token), task_ref=task.task_ref, now=NOW)


def test_modified_secret_and_case_do_not_authenticate(identity_db, bound):
    task, issued = bound
    raw = issued.token.get_secret_value()
    for token in (raw[:-1] + ("a" if raw[-1] != "a" else "b"), raw.upper()):
        with identity_db() as db, pytest.raises(AgentIdentityError, match="AUTH_INVALID"):
            validate_agent_credential(db, token=SecretStr(token), task_ref=task.task_ref, now=NOW)


def test_credential_expiration_is_half_open(identity_db, bound):
    task, issued = bound
    assert validate(
        identity_db, issued, task.task_ref, issued.expires_at - timedelta(microseconds=1)
    )
    assert_denied(identity_db, issued, task.task_ref, issued.expires_at)
    assert_denied(identity_db, issued, task.task_ref, NOW - timedelta(microseconds=1))


def test_explicit_revocation_is_idempotent(identity_db, bound):
    task, issued = bound
    for _ in range(2):
        with identity_db() as db:
            revoke_agent_credential(
                db,
                owner=OWNER,
                task_ref=task.task_ref,
                credential_ref=issued.credential_ref,
                now=NOW,
            )
    assert_denied(identity_db, issued, task.task_ref)


@pytest.mark.parametrize("foreign_owner", [OWNER, OTHER])
def test_wrong_task_and_cross_owner_reference(identity_db, bound, foreign_owner):
    _, issued = bound
    other_task = make_task(identity_db, owner=foreign_owner)
    assert (
        assert_denied(identity_db, issued, other_task.task_ref, status=403) == "TASK_SCOPE_MISMATCH"
    )


def test_unknown_task_reference(identity_db, bound):
    _, issued = bound
    assert assert_denied(identity_db, issued, "task_unknown", status=403) == "TASK_SCOPE_MISMATCH"


def test_task_expiration_caps_credential_and_cannot_be_extended(identity_db):
    task = make_task(identity_db, expiry=NOW + timedelta(minutes=2))
    issued = issue(identity_db, task.task_ref)
    assert issued.expires_at == task.expires_at
    assert_denied(identity_db, issued, task.task_ref, task.expires_at)
    with identity_db() as db, pytest.raises(AgentIdentityError, match="TASK_NOT_ACTIVE"):
        issue_agent_credential(db, owner=OWNER, task_ref=task.task_ref, now=task.expires_at)


def test_task_revocation_invalidates_credentials_and_issuance(identity_db, bound):
    task, issued = bound
    for _ in range(2):
        with identity_db() as db:
            revoke_trusted_task(db, owner=OWNER, task_ref=task.task_ref, now=NOW)
    assert_denied(identity_db, issued, task.task_ref)
    with identity_db() as db, pytest.raises(AgentIdentityError, match="TASK_NOT_ACTIVE"):
        rotate_agent_credential(db, owner=OWNER, task_ref=task.task_ref, now=NOW)


@pytest.mark.parametrize("status", ["COMPLETED", "CANCELLED", "EXPIRED"])
def test_inactive_task_default_deny(identity_db, bound, status):
    task, issued = bound
    with identity_db.begin() as db:
        db.get(GatewayTask, task.task_ref).status = status
    assert_denied(identity_db, issued, task.task_ref)


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/api/consents", {"scope": "tools:execute", "granted": True}),
        ("/api/consents", {"scope": "tools:execute", "granted": False}),
        ("/api/tool-permissions", {"tool_name": "echo", "allowed": True}),
        ("/api/tool-permissions", {"tool_name": "echo", "allowed": False}),
        ("/api/tools/execute", {"tool_name": "echo", "arguments": {"message": "safe"}}),
    ],
)
def test_agent_cannot_manage_consent_permissions_or_legacy_tools(client, bound, path, payload):
    _, issued = bound
    response = client.post(
        path, headers={"Authorization": f"Bearer {issued.token.get_secret_value()}"}, json=payload
    )
    assert response.status_code == 401
    assert (
        client.get("/api/audit-events", headers={"Authorization": "Bearer test-token"}).json() == []
    )


@pytest.mark.parametrize(
    "path",
    [
        "/api/control/v1/tasks/task_unknown/agent-credentials",
        "/api/control/v1/approvals/approval_unknown/resolve",
        "/api/control/v1/tasks",
    ],
)
def test_agent_cannot_access_issuance_or_owner_approval_routes(client, bound, path):
    _, issued = bound
    response = client.post(
        path, headers={"Authorization": f"Bearer {issued.token.get_secret_value()}"}, json={}
    )
    assert response.status_code == (401 if "/approvals/" in path else 404)
    assert path not in app.openapi()["paths"]


def test_agent_cannot_read_owner_audit(client, bound):
    _, issued = bound
    assert (
        client.get(
            "/api/audit-events",
            headers={"Authorization": f"Bearer {issued.token.get_secret_value()}"},
        ).status_code
        == 401
    )


def test_plaintext_is_never_persisted_or_serialized(identity_db, bound):
    task, issued = bound
    raw = issued.token.get_secret_value()
    with identity_db() as db:
        row = db.get(AgentCredential, issued.credential_ref)
        assert row.token_digest == hashlib.sha256(raw.encode("ascii")).hexdigest()
        for table in ("agent_credentials", "gateway_tasks", "audit_events"):
            rows = db.execute(text(f"SELECT * FROM {table}")).all()
            assert raw not in repr(rows) and raw.split(".")[1] not in repr(rows)
    assert raw not in repr(issued) and raw not in issued.model_dump_json()
    assert "token" not in issued.model_dump()
    assert task.task_ref == issued.task_ref


def test_rotation_invalidates_all_previous_credentials(identity_db, bound):
    task, old = bound
    with identity_db() as db:
        new = rotate_agent_credential(db, owner=OWNER, task_ref=task.task_ref, now=NOW)
    assert new.token != old.token and new.credential_ref != old.credential_ref
    assert_denied(identity_db, old, task.task_ref)
    assert validate(identity_db, new, task.task_ref)
    with identity_db() as db:
        rows = db.scalars(select(AgentCredential)).all()
        assert sum(row.revoked_at is None for row in rows) == 1
        assert db.get(GatewayTask, task.task_ref).credential_epoch == 2


def test_rotation_failure_rolls_back_revocation_and_epoch(identity_db, bound, monkeypatch):
    task, old = bound
    with identity_db() as db:

        def fail_flush(*args, **kwargs):
            raise OperationalError("private sql", {"marker": "private"}, Exception("private"))

        monkeypatch.setattr(db, "flush", fail_flush)
        with pytest.raises(AgentIdentityError, match="GATEWAY_UNAVAILABLE"):
            rotate_agent_credential(db, owner=OWNER, task_ref=task.task_ref, now=NOW)
    assert validate(identity_db, old, task.task_ref)
    with identity_db() as db:
        assert db.get(GatewayTask, task.task_ref).credential_epoch == 1


@pytest.mark.parametrize("operation", ["issue", "revoke", "task_revoke"])
def test_owner_mismatch_cannot_mutate(identity_db, bound, operation):
    task, issued = bound
    with identity_db() as db, pytest.raises(AgentIdentityError, match="NOT_FOUND"):
        if operation == "issue":
            issue_agent_credential(db, owner=OTHER, task_ref=task.task_ref, now=NOW)
        elif operation == "revoke":
            revoke_agent_credential(
                db,
                owner=OTHER,
                task_ref=task.task_ref,
                credential_ref=issued.credential_ref,
                now=NOW,
            )
        else:
            revoke_trusted_task(db, owner=OTHER, task_ref=task.task_ref, now=NOW)
    assert validate(identity_db, issued, task.task_ref)


def test_agent_context_cannot_be_used_for_issuance_or_task_creation(identity_db, bound):
    task, issued = bound
    agent = validate(identity_db, issued, task.task_ref)
    with identity_db() as db, pytest.raises(AgentIdentityError, match="ROLE_FORBIDDEN"):
        issue_agent_credential(db, owner=agent, task_ref=task.task_ref, now=NOW)
    with identity_db() as db, pytest.raises(AgentIdentityError, match="ROLE_FORBIDDEN"):
        create_trusted_task(db, owner=agent, scope=SCOPE, expires_at=task.expires_at, now=NOW)


def test_database_failure_fails_closed_and_logs_no_secrets(identity_db, bound, caplog, monkeypatch):
    task, issued = bound
    raw = issued.token.get_secret_value()
    caplog.set_level(logging.DEBUG)
    with identity_db() as db:

        def unavailable(*args, **kwargs):
            raise OperationalError("secret SQL", {"token": raw}, Exception(raw))

        monkeypatch.setattr(db, "get", unavailable)
        with pytest.raises(AgentIdentityError) as failure:
            validate_agent_credential(db, token=issued.token, task_ref=task.task_ref, now=NOW)
    assert failure.value.status_code == 503
    assert failure.value.__suppress_context__ is True
    assert raw not in str(failure.value) and raw not in caplog.text


def test_dependency_maps_database_outage_to_503(probe, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OperationalError("private", {}, Exception("private"))

    monkeypatch.setattr(Session, "get", unavailable)
    response = probe.get(
        "/identity/task_unknown",
        headers={"Authorization": "Bearer gpa_cred_" + "0" * 32 + "." + "a" * 43},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "GATEWAY_UNAVAILABLE"}


def test_no_credentials_in_success_failure_or_lifecycle_logs(identity_db, bound, caplog):
    task, issued = bound
    caplog.set_level(logging.DEBUG)
    validate(identity_db, issued, task.task_ref)
    assert_denied(identity_db, issued, "task_foreign", status=403)
    with identity_db() as db:
        new = rotate_agent_credential(db, owner=OWNER, task_ref=task.task_ref, now=NOW)
    assert_denied(identity_db, issued, task.task_ref)
    for credential in (issued, new):
        assert credential.token.get_secret_value() not in caplog.text
        assert credential.token.get_secret_value().split(".")[1] not in caplog.text


def test_database_enforces_task_owner_pair(identity_db, bound):
    task, issued = bound
    make_task(identity_db, owner=OTHER)
    with identity_db() as db, pytest.raises(IntegrityError):
        with db.begin():
            db.get(AgentCredential, issued.credential_ref).owner_id = OTHER.owner_id
    assert validate(identity_db, issued, task.task_ref)


def test_corrupt_owner_binding_is_denied_even_without_foreign_keys(identity_db, bound):
    task, issued = bound
    with identity_db() as db, db.get_bind().connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.execute(text("UPDATE agent_credentials SET owner_id='foreign'"))
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    assert_denied(identity_db, issued, task.task_ref)


@pytest.mark.parametrize(
    "field,value",
    [
        ("credential_epoch", 999),
        ("authorization_scope", {}),
        ("authorization_scope", {"purpose": "morning_brief", "allowed_actions": ["shell.exec"]}),
    ],
)
def test_corrupt_task_state_is_default_deny(identity_db, bound, field, value):
    task, issued = bound
    with identity_db.begin() as db:
        setattr(db.get(GatewayTask, task.task_ref), field, value)
    assert_denied(identity_db, issued, task.task_ref)


@pytest.mark.parametrize(
    "delta", [timedelta(0), timedelta(seconds=-1), timedelta(hours=1, microseconds=1)]
)
def test_task_lifetime_limits(identity_db, delta):
    with pytest.raises(ValueError, match="Task lifetime"):
        make_task(identity_db, expiry=NOW + delta)


def test_naive_time_rejected(identity_db):
    with pytest.raises(ValueError, match="aware"):
        make_task(identity_db, expiry=NOW.replace(tzinfo=None))


@pytest.mark.parametrize(
    "changes",
    [
        {"allowed_actions": ()},
        {"allowed_actions": ("tasks.list", "tasks.list")},
        {"allowed_actions": ("shell.exec",)},
        {"user_id": "forged"},
        {"resource_ids": ("unverified_resource",)},
        {"recipient": "safe@example.test"},
        {"approval_enabled": "true"},
        {"allowed_actions": ["tasks.list"]},
    ],
)
def test_scope_has_no_default_allow_or_unverified_resources(changes):
    data = {"purpose": "morning_brief", "allowed_actions": ("tasks.list",)} | changes
    with pytest.raises(ValidationError):
        TaskScope(**data)


def test_owner_dependency_remains_separate_and_reserves_agent_prefix(probe, monkeypatch):
    assert probe.get("/owner", headers={"Authorization": "Bearer test-owner-token"}).json() == {
        "owner_id": "local-user"
    }
    monkeypatch.setenv("API_BEARER_TOKEN", "gpa_misconfigured_owner")
    get_settings.cache_clear()
    assert (
        probe.get("/owner", headers={"Authorization": "Bearer gpa_misconfigured_owner"}).status_code
        == 401
    )


def test_mysql_schema_compiles_without_connecting_and_migration_is_additive():
    for model in (GatewayTask, AgentCredential):
        ddl = str(CreateTable(model.__table__).compile(dialect=mysql.dialect()))
        assert "DATETIME(6)" in ddl and "ascii_bin" in ddl and "InnoDB" in ddl
    migration = Path(__file__).parents[1] / "migrations/versions/0002_agent_identity.py"
    tree = ast.parse(migration.read_text(encoding="utf-8"))
    revisions = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
    }
    assert revisions["down_revision"] == "0001_initial"
    assert revisions["revision"] == "0002_agent_identity"
    assert "token" not in AgentCredential.__table__.columns
    assert json.loads(SCOPE.model_dump_json())["resource_ids"] == []
