"""Real MySQL tests. Only the separately verified disposable Step 10 runner opts in."""

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import UTC, datetime, timedelta
from threading import Event, current_thread
from uuid import uuid4

import pytest
from app.agent_schemas import OwnerContext, ResourceVersion, TaskScope
from app.database import Base
from app.gateway_contracts import ConsentCreate, ToolRequest
from app.models import AgentCredential, AuditEvent, GatewayTask, ScopedConsent
from app.services.agent_identity import (
    AgentIdentityError,
    create_trusted_task,
    issue_agent_credential,
    revoke_agent_credential,
    validate_agent_credential,
)
from app.services.resource_catalog import CatalogResource, ResourceCatalog
from app.services.scoped_consent import (
    authorize_request,
    create_scoped_consent,
    revoke_scoped_consent,
)
from sqlalchemy import CheckConstraint, event, insert, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 24, 12, 0, 0, 678901, tzinfo=UTC)
PIN = ResourceVersion(
    resource_id="synthetic_report", version_ref="version_one", classification="SHAREABLE"
)
SCOPE = TaskScope(
    purpose="summarize_document",
    allowed_actions=("files.read", "tasks.list", "email.send"),
    resource_ids=(PIN.resource_id,),
    resource_versions=(PIN,),
)


@pytest.fixture(scope="session", autouse=True)
def require_disposable_runner():
    # Same-scope autouse runs before mysql_engine; refuse unapproved connections first.
    if os.getenv("MYSQL_VALIDATION_PROJECT") not in (
        "ghost-mysql-validation",
        "ghost-ledger-validation",
        "ghost-approval-validation",
        "ghost-execution-validation",
        "ghost-catalog-validation",
        "ghost-document-validation",
        "ghost-mailpit-validation",
    ):
        pytest.skip("Requires a verified disposable Compose environment")


@pytest.fixture
def db_factory(mysql_engine):
    return sessionmaker(mysql_engine, autoflush=False, expire_on_commit=False)


def new_task(factory, owner=None):
    owner = owner or OwnerContext(owner_id=f"mysql_{uuid4().hex}")
    catalog = ResourceCatalog(
        resources=(CatalogResource(**PIN.model_dump(), owner_id=owner.owner_id),)
    )
    with factory() as db:
        task = create_trusted_task(
            db,
            owner=owner,
            scope=SCOPE,
            catalog=catalog,
            now=NOW,
            expires_at=NOW + timedelta(hours=1),
        )
    with factory() as db:
        issued = issue_agent_credential(db, owner=owner, task_ref=task.task_ref, now=NOW)
    return owner, catalog, task, issued


@pytest.fixture
def bound(db_factory):
    return new_task(db_factory)


def request_for(task, **changes):
    return ToolRequest.model_validate_json(
        json.dumps(
            {
                "request_id": f"req_{uuid4().hex}",
                "task_ref": task.task_ref,
                "action": "files.read",
                "purpose": SCOPE.purpose,
                "arguments": {"resource_id": PIN.resource_id},
                "idempotency_key": f"idem_{uuid4().hex}",
                **changes,
            }
        )
    )


def grant(factory, bound):
    owner, catalog, task, _ = bound
    payload = ConsentCreate(
        action="files.read",
        purpose=SCOPE.purpose,
        resource_ids=(PIN.resource_id,),
        expires_at=NOW + timedelta(minutes=10),
    )
    with factory() as db:
        return create_scoped_consent(
            db, owner=owner, task_ref=task.task_ref, payload=payload, catalog=catalog, now=NOW
        )


def authorize(factory, bound, now=NOW, **changes):
    _, catalog, task, issued = bound
    with factory() as db:
        return authorize_request(
            db, token=issued.token, request=request_for(task, **changes), catalog=catalog, now=now
        )


def test_mysql_schema_constraints_indexes_and_time(mysql_engine, db_factory, bound):
    inspector = inspect(mysql_engine)
    for table in Base.metadata.sorted_tables:
        assert {c["name"] for c in inspector.get_columns(table.name)} == set(table.columns.keys())
        checks = {item["name"] for item in inspector.get_check_constraints(table.name)}
        assert {
            item.name for item in table.constraints if isinstance(item, CheckConstraint)
        } <= checks
        indexes = {tuple(item["column_names"]) for item in inspector.get_indexes(table.name)}
        assert {
            tuple(column.name for column in index.columns) for index in table.indexes
        } <= indexes
    for table in ("agent_credentials", "scoped_consents"):
        keys = inspector.get_foreign_keys(table)
        assert any(
            item["constrained_columns"] == ["task_ref", "owner_id"]
            and item["referred_columns"] == ["task_ref", "owner_id"]
            for item in keys
        )
    assert any(
        set(item["column_names"]) == {"task_ref", "owner_id"}
        for item in inspector.get_unique_constraints("gateway_tasks")
    )
    assert any(
        item["column_names"] == ["token_digest"]
        for item in inspector.get_unique_constraints("agent_credentials")
    )
    _, _, task, issued = bound
    with db_factory() as db:
        assert db.get(GatewayTask, task.task_ref).created_at == NOW
        assert db.get(AgentCredential, issued.credential_ref).issued_at == NOW
    with mysql_engine.connect() as connection:
        assert connection.get_isolation_level() == "READ COMMITTED"
        assert connection.execute(text("SELECT @@session.time_zone")).scalar_one() == "+00:00"
        collations = (
            connection.execute(
                text(
                    "SELECT COLLATION_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='agent_credentials' "
                    "AND COLUMN_NAME IN ('credential_ref','task_ref','token_digest')"
                )
            )
            .scalars()
            .all()
        )
        assert len(collations) == 3 and set(collations) == {"ascii_bin"}


def test_mysql_task_credential_and_consent_persist(db_factory, bound):
    owner, _, task, issued = bound
    consent = grant(db_factory, bound)
    with db_factory() as db:
        assert db.get(GatewayTask, task.task_ref).owner_id == owner.owner_id
        row = db.get(AgentCredential, issued.credential_ref)
        assert (
            row.token_digest == hashlib.sha256(issued.token.get_secret_value().encode()).hexdigest()
        )
        assert db.get(ScopedConsent, consent.consent_ref).resource_versions == [PIN.model_dump()]
        assert issued.token.get_secret_value() not in repr(
            db.execute(text("SELECT * FROM agent_credentials")).all()
        )
    response = authorize(db_factory, bound)
    assert response.decision == "ALLOW" and response.execution_status == "NOT_EXECUTED"
    assert response.result is response.approval_ref is None
    with db_factory() as db:
        audit = db.get(AuditEvent, int(response.audit_event_ref.removeprefix("event_")))
        assert audit.detail["task_ref"] == task.task_ref and audit.detail["decision"] == "ALLOW"
        assert datetime.fromisoformat(audit.detail["timestamp"]).tzinfo is not None
        # Legacy audit DATETIME lacks fractions/timezone; detail retains precise UTC.
        assert audit.created_at.tzinfo is None and audit.created_at.microsecond == 0
        assert datetime.fromisoformat(audit.detail["timestamp"]) == NOW


def test_mysql_credential_expiry_and_revocation(db_factory, bound):
    owner, _, task, issued = bound
    with db_factory() as db, pytest.raises(AgentIdentityError, match="AUTH_INVALID"):
        validate_agent_credential(
            db, token=issued.token, task_ref=task.task_ref, now=issued.expires_at
        )
    with db_factory() as db:
        revoke_agent_credential(
            db, owner=owner, task_ref=task.task_ref, credential_ref=issued.credential_ref, now=NOW
        )
    with pytest.raises(AgentIdentityError, match="AUTH_INVALID"):
        authorize(db_factory, bound)


def test_mysql_owner_and_task_isolation(db_factory, bound):
    other = new_task(db_factory)
    _, _, task, issued = bound
    with db_factory() as db, pytest.raises(AgentIdentityError, match="TASK_SCOPE_MISMATCH"):
        validate_agent_credential(db, token=issued.token, task_ref=other[2].task_ref, now=NOW)
    payload = ConsentCreate(
        action="files.read",
        purpose=SCOPE.purpose,
        resource_ids=(PIN.resource_id,),
        expires_at=NOW + timedelta(minutes=5),
    )
    with db_factory() as db, pytest.raises(AgentIdentityError, match="NOT_FOUND"):
        create_scoped_consent(
            db, owner=other[0], task_ref=task.task_ref, payload=payload, catalog=other[1], now=NOW
        )


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"arguments": {"resource_id": "unknown_resource"}}, "RESOURCE_NOT_AUTHORIZED"),
        ({"purpose": "answer_question"}, "PURPOSE_MISMATCH"),
        (
            {
                "action": "email.send",
                "arguments": {
                    "recipient": "wrong@example.test",
                    "subject": "Synthetic",
                    "body": "Synthetic",
                },
            },
            "ACTION_DISABLED",
        ),
    ],
)
def test_mysql_exact_scope_mismatch(db_factory, bound, changes, reason):
    grant(db_factory, bound)
    result = authorize(db_factory, bound, **changes)
    assert result.decision == "DENY" and result.reason_code == reason


def test_mysql_missing_expired_and_revoked_consent(db_factory, bound):
    assert authorize(db_factory, bound).reason_code == "APPROVAL_UNAVAILABLE"
    consent = grant(db_factory, bound)
    assert authorize(db_factory, bound, now=consent.expires_at).reason_code == "CONSENT_EXPIRED"
    owner, _, task, _ = bound
    for _ in range(2):
        with db_factory() as db:
            revoke_scoped_consent(
                db, owner=owner, task_ref=task.task_ref, consent_ref=consent.consent_ref, now=NOW
            )
    assert authorize(db_factory, bound).reason_code == "CONSENT_REVOKED"


@pytest.mark.parametrize(
    "table,change",
    [
        ("task", None),
        ("credential", None),
        ("credential", "digest"),
        ("credential", "owner"),
        ("consent", "owner"),
        ("consent", "recipient"),
    ],
)
def test_mysql_duplicate_and_scope_constraints(db_factory, bound, table, change):
    owner, _, task, issued = bound
    consent = grant(db_factory, bound)
    other = new_task(db_factory)
    model, ref = {
        "task": (GatewayTask, task.task_ref),
        "credential": (AgentCredential, issued.credential_ref),
        "consent": (ScopedConsent, consent.consent_ref),
    }[table]
    with db_factory() as db:
        row = db.get(model, ref)
        values = {column.name: getattr(row, column.name) for column in model.__table__.columns}
    if change == "digest":
        values["credential_ref"] = f"cred_{uuid4().hex}"
    with db_factory() as db, pytest.raises(DBAPIError) as error:
        with db.begin():
            if change == "owner":
                db.get(model, ref).owner_id = other[0].owner_id
            elif change == "recipient":
                db.get(model, ref).recipient = "forbidden@example.test"
            else:
                db.execute(insert(model).values(**values))
    expected = 3819 if change == "recipient" else 1452 if change == "owner" else 1062
    assert error.value.orig.args[0] == expected


def test_mysql_concurrent_authorizations(db_factory, bound):
    grant(db_factory, bound)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: authorize(db_factory, bound), range(8)))
    assert all(result.decision == "ALLOW" for result in results)
    assert len({result.audit_event_ref for result in results}) == 8


def test_mysql_concurrent_credential_rotation(db_factory, bound):
    owner, _, task, _ = bound

    def issue(_):
        with db_factory() as db:
            return issue_agent_credential(db, owner=owner, task_ref=task.task_ref, now=NOW)

    with ThreadPoolExecutor(max_workers=4) as pool:
        issued = list(pool.map(issue, range(8)))
    valid = 0
    for credential in issued:
        try:
            with db_factory() as db:
                validate_agent_credential(
                    db, token=credential.token, task_ref=task.task_ref, now=NOW
                )
            valid += 1
        except AgentIdentityError as error:
            assert error.code == "AUTH_INVALID"
    assert valid == 1


@pytest.mark.parametrize("kind", ["consent", "credential"])
def test_mysql_row_lock_serializes_revocation(db_factory, mysql_engine, bound, monkeypatch, kind):
    import app.services.agent_identity as identity
    import app.services.scoped_consent as policy

    consent = grant(db_factory, bound)
    owner, _, task, issued = bound
    module = policy if kind == "consent" else identity
    locked, attempted, release = Event(), Event(), Event()
    original = module._owned_task

    def hold(*args, **kwargs):
        row = original(*args, **kwargs)
        locked.set()
        assert release.wait(8)
        return row

    def observe(connection, cursor, statement, parameters, context, many):
        if (
            current_thread().name.startswith("step10-reader")
            and "gateway_tasks" in statement
            and "FOR UPDATE" in statement
        ):
            attempted.set()

    def writer():
        with db_factory() as db:
            if kind == "consent":
                revoke_scoped_consent(
                    db,
                    owner=owner,
                    task_ref=task.task_ref,
                    consent_ref=consent.consent_ref,
                    now=NOW,
                )
            else:
                revoke_agent_credential(
                    db,
                    owner=owner,
                    task_ref=task.task_ref,
                    credential_ref=issued.credential_ref,
                    now=NOW,
                )

    def reader():
        try:
            return authorize(db_factory, bound).reason_code
        except AgentIdentityError as error:
            return error.code

    monkeypatch.setattr(module, "_owned_task", hold)
    event.listen(mysql_engine, "before_cursor_execute", observe)
    try:
        with (
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="step10-writer") as writers,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="step10-reader") as readers,
        ):
            write = writers.submit(writer)
            assert locked.wait(5)
            read = readers.submit(reader)
            try:
                assert attempted.wait(5)
                with pytest.raises(TimeoutError):
                    read.result(timeout=0.2)
            finally:
                release.set()
            write.result(5)
            assert read.result(5) == ("CONSENT_REVOKED" if kind == "consent" else "AUTH_INVALID")
    finally:
        release.set()
        event.remove(mysql_engine, "before_cursor_execute", observe)


def test_mysql_restart_writer(db_factory):
    owner = OwnerContext(owner_id="step10_restart_owner")
    bound = new_task(db_factory, owner)
    grant(db_factory, bound)
    assert authorize(db_factory, bound).decision == "ALLOW"


def test_mysql_restart_reader(db_factory):
    owner = OwnerContext(owner_id="step10_restart_owner")
    catalog = ResourceCatalog(
        resources=(CatalogResource(**PIN.model_dump(), owner_id=owner.owner_id),)
    )
    with db_factory() as db:
        task = db.scalar(select(GatewayTask).where(GatewayTask.owner_id == owner.owner_id))
        assert task is not None
        assert (
            db.scalar(select(ScopedConsent).where(ScopedConsent.task_ref == task.task_ref))
            is not None
        )
        assert db.scalar(select(AuditEvent).where(AuditEvent.user_id == owner.owner_id)) is not None
    with db_factory() as db:
        issued = issue_agent_credential(db, owner=owner, task_ref=task.task_ref, now=NOW)
    assert authorize(db_factory, (owner, catalog, task, issued)).decision == "ALLOW"
