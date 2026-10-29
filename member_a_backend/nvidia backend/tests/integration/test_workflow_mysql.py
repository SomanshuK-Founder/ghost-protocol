"""Step 33: verified disposable MySQL only; no protected executors or SMTP."""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event, Lock, current_thread
from uuid import uuid4

import pytest
from app.agent_schemas import OwnerContext, ResourceVersion, TaskScope
from app.gateway_contracts import ToolRequest
from app.models import (
    AuditEvent,
    ExecutionAttempt,
    GatewayOperation,
    PendingApproval,
    ScopedConsent,
    WorkflowCheckpoint,
)
from app.services.agent_identity import (
    AgentIdentityError,
    _owned_task,
    _transaction,
    create_trusted_task,
    issue_agent_credential,
    revoke_agent_credential,
    revoke_trusted_task,
)
from app.services.approvals import owner_approval
from app.services.operation_ledger import admit_operation
from app.services.resource_catalog import CatalogResource, ResourceCatalog
from app.services.scoped_consent import revoke_scoped_consent
from app.services.workflow_resume import workflow_checkpoint
from app.workflow_contracts import WorkflowIdentity, WorkflowPause, WorkflowPrepare
from sqlalchemy import event, func, inspect, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.integration
EVIDENCE = []


@pytest.fixture(scope="session", autouse=True)
def require_step33():
    assert os.environ.get("MYSQL_VALIDATION_PROJECT") == "ghost-resume-validation"
    yield
    destination = os.getenv("STEP33_EVIDENCE")
    if destination:
        from pathlib import Path

        Path(destination).write_text(json.dumps(EVIDENCE, indent=2), encoding="utf-8")


@dataclass
class Case:
    engine: object
    factory: object
    owner: OwnerContext
    task: object
    issued: object
    request: ToolRequest
    catalog: ResourceCatalog
    now: datetime
    binding: object = None


def new_case(engine, *, pin=None, owner_ref="local-user"):
    factory = sessionmaker(engine, autoflush=False, expire_on_commit=False)
    owner = OwnerContext(owner_id=owner_ref)
    now = datetime.now(UTC)
    pin = pin or ResourceVersion(
        resource_id="resource_resume_demo",
        version_ref="version_resume_demo",
        classification="SHAREABLE",
    )
    catalog = ResourceCatalog(
        resources=(CatalogResource(**pin.model_dump(), owner_id=owner.owner_id),)
    )
    scope = TaskScope(
        purpose="summarize_document",
        allowed_actions=("files.read",),
        resource_ids=(pin.resource_id,),
        resource_versions=(pin,),
        approval_enabled=True,
    )
    with factory() as db:
        task = create_trusted_task(
            db,
            owner=owner,
            scope=scope,
            catalog=catalog,
            now=now,
            expires_at=now + timedelta(minutes=50),
        )
    with factory() as db:
        issued = issue_agent_credential(db, owner=owner, task_ref=task.task_ref, now=now)
    request = ToolRequest(
        request_id="req_resume_" + uuid4().hex,
        task_ref=task.task_ref,
        idempotency_key="key_resume_" + uuid4().hex,
        action="files.read",
        purpose=scope.purpose,
        arguments={"resource_id": pin.resource_id},
    )
    return Case(engine, factory, owner, task, issued, request, catalog, now)


def step(case, command, payload=None, *, owner=None, now=None):
    with case.factory() as db:
        return workflow_checkpoint(
            db,
            owner=owner or case.owner,
            command=command,
            payload=payload,
            binding_ref=case.binding.binding_ref if case.binding else None,
            catalog=case.catalog,
            now=now or case.now,
        )


def pending(case):
    with case.factory() as db:
        result = admit_operation(
            db, token=case.issued.token, request=case.request, catalog=case.catalog, now=case.now
        )
    case.binding = step(
        case,
        "prepare",
        WorkflowPrepare(
            task_ref=case.task.task_ref,
            approval_ref=result.approval_ref,
            request_id=case.request.request_id,
            idempotency_key=case.request.idempotency_key,
        ),
    )
    case.binding = step(case, "pause", WorkflowPause(checkpoint_id=str(uuid4())))
    return case


def decide(case, resolution="APPROVE", *, revoke=False):
    with case.factory() as db:
        owner_approval(
            db,
            owner=case.owner,
            approval_ref=case.binding.approval_ref,
            resolution=None if revoke else resolution,
            revoke=revoke,
            catalog=case.catalog,
            now=case.now,
        )


def identity(case):
    snapshot = step(case, "get")
    return WorkflowIdentity(
        **{
            name: getattr(snapshot, name)
            for name in (
                "task_ref",
                "operation_ref",
                "approval_ref",
                "request_id",
                "idempotency_key",
                "thread_id",
                "checkpoint_id",
                "workflow_version",
            )
        },
        expected_authorization_version=snapshot.authorization_version,
    )


@pytest.fixture
def case(mysql_engine):
    return pending(new_case(mysql_engine))


def test_schema(mysql_engine):
    inspector = inspect(mysql_engine)
    assert "workflow_checkpoints" in inspector.get_table_names()
    uniques = {
        tuple(row["column_names"])
        for row in inspector.get_unique_constraints("workflow_checkpoints")
    }
    assert {("operation_ref",), ("thread_id",), ("thread_id", "checkpoint_id")} <= uniques
    fks = inspector.get_foreign_keys("workflow_checkpoints")
    assert any(
        row["constrained_columns"] == ["operation_ref", "task_ref", "owner_id"] for row in fks
    )
    assert any(row["referred_table"] == "pending_approvals" for row in fks)
    assert any(row["referred_table"] == "audit_events" for row in fks)
    columns = {row["name"]: row for row in inspector.get_columns("workflow_checkpoints")}
    assert all(
        columns[name]["type"].fsp == 6 for name in ("created_at", "updated_at", "expires_at")
    )
    assert any(
        row["column_names"] == ["task_ref"] for row in inspector.get_indexes("workflow_checkpoints")
    )


def test_owner_admission_exact_identity_and_audit(case):
    decide(case)
    payload = identity(case)
    for command, phase in [("admit", "ADMITTED"), ("claim", "RESUMING"), ("complete", "RESUMED")]:
        result = step(case, command, payload)
        assert result.phase == phase
    with case.factory() as db:
        approval = db.get(PendingApproval, case.binding.approval_ref)
        operation = db.get(GatewayOperation, case.binding.operation_ref)
        assert approval.consumed_at is None and approval.resume_ref is not None
        assert operation.operation_status == "READY" and operation.execution_started_at is None
        assert db.get(AuditEvent, int(result.audit_event_ref.removeprefix("event_"))) is not None
        assert db.scalar(select(func.count()).select_from(ExecutionAttempt)) == 0


@pytest.mark.parametrize(
    "field",
    [
        "task_ref",
        "operation_ref",
        "approval_ref",
        "checkpoint_id",
        "thread_id",
        "request_id",
        "idempotency_key",
        "expected_authorization_version",
    ],
)
def test_conflicting_identity(case, field):
    decide(case)
    payload = identity(case)
    changed = payload.model_copy(
        update={
            field: payload.expected_authorization_version + 1
            if field == "expected_authorization_version"
            else str(uuid4())
            if field == "checkpoint_id"
            else "foreign_ref"
        }
    )
    with pytest.raises(AgentIdentityError):
        step(case, "admit", changed)
    assert step(case, "get").phase == "PAUSED"


def test_foreign_owner(case):
    with pytest.raises(AgentIdentityError):
        step(case, "get", owner=OwnerContext(owner_id="foreign-owner"))


def test_agent_cannot_be_resume_owner(case):
    with pytest.raises(AgentIdentityError):
        step(case, "get", owner=case.issued)


def mutate(case, change):
    if change == "approval":
        decide(case, revoke=True)
    elif change == "task":
        with case.factory() as db:
            revoke_trusted_task(db, owner=case.owner, task_ref=case.task.task_ref, now=case.now)
    elif change == "credential":
        with case.factory() as db:
            revoke_agent_credential(
                db,
                owner=case.owner,
                task_ref=case.task.task_ref,
                credential_ref=case.issued.credential_ref,
                now=case.now,
            )
    elif change == "consent":
        with case.factory() as db:
            ref = db.get(PendingApproval, case.binding.approval_ref).consent_ref
        with case.factory() as db:
            revoke_scoped_consent(
                db, owner=case.owner, task_ref=case.task.task_ref, consent_ref=ref, now=case.now
            )
    elif change == "version":
        with case.factory() as db, _transaction(db):
            _owned_task(db, case.owner, case.task.task_ref).authorization_version += 1


@pytest.mark.parametrize(
    "change",
    [
        "pending",
        "rejected",
        "expired_approval",
        "approval",
        "task",
        "credential",
        "consent",
        "expired_consent",
        "missing_matching_consent",
        "version",
        "invalid_phase",
    ],
)
def test_invalid_authorization(case, change):
    if change == "rejected":
        decide(case, "REJECT")
    elif change != "pending":
        decide(case)
    payload = identity(case)
    now = case.now
    if change in ("approval", "task", "credential", "consent", "version"):
        mutate(case, change)
    elif change == "expired_approval":
        now += timedelta(minutes=11)
    elif change in ("expired_consent", "missing_matching_consent"):
        with case.factory.begin() as db:
            consent = db.scalar(
                select(ScopedConsent).where(ScopedConsent.task_ref == case.task.task_ref)
            )
            if change == "expired_consent":
                consent.expires_at = now + timedelta(seconds=1)
            else:
                consent.action = "tasks.list"
                consent.resource_versions = []
        now += timedelta(seconds=2)
    elif change == "invalid_phase":
        with case.factory.begin() as db:
            db.get(WorkflowCheckpoint, case.binding.binding_ref).phase = "PREPARING"
    with pytest.raises(AgentIdentityError):
        step(case, "admit", payload, now=now)


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner_id", "wrong-owner"),
        ("task_ref", "task_missing"),
        ("approval_ref", "approval_missing"),
        ("audit_event_id", 2147483647),
        ("phase", "INVALID"),
        ("registration_authorization_version", -1),
    ],
)
def test_database_constraints(case, field, value):
    with case.factory() as db:
        row = db.get(WorkflowCheckpoint, case.binding.binding_ref)
        with pytest.raises((IntegrityError, OperationalError)) as error:
            setattr(row, field, value)
            db.flush()
        assert error.value.orig.args[0] in (1452, 1062, 3819)
        db.rollback()


def _lock_waiters(connection):
    return connection.execute(
        text(
            "SELECT COUNT(DISTINCT w.REQUESTING_THREAD_ID) "
            "FROM performance_schema.data_lock_waits w JOIN performance_schema.data_locks l "
            "ON l.ENGINE_LOCK_ID=w.REQUESTING_ENGINE_LOCK_ID "
            "WHERE l.OBJECT_SCHEMA='nvidia_app_test' AND l.OBJECT_NAME='gateway_tasks'"
        )
    ).scalar_one()


def contend(case, functions, label):
    count = len(functions)
    ready = Event()
    lock = Lock()
    barrier = Barrier(count)
    connection_ids = set()
    arrivals = 0
    prefix = "step33-" + uuid4().hex[:8]

    def observe(conn, cursor, statement, parameters, context, executemany):
        nonlocal arrivals
        if (
            current_thread().name.startswith(prefix)
            and "gateway_tasks" in statement
            and "FOR UPDATE" in statement
            and case.task.task_ref in str(parameters)
        ):
            with lock:
                connection_ids.add(conn.connection.driver_connection.thread_id())
                arrivals += 1
                if arrivals >= count:
                    ready.set()

    event.listen(case.engine, "before_cursor_execute", observe)
    anchor = case.engine.connect()
    transaction = anchor.begin()
    anchor.execute(
        text("SELECT task_ref FROM gateway_tasks WHERE task_ref=:task FOR UPDATE"),
        {"task": case.task.task_ref},
    )

    def work(function):
        barrier.wait(timeout=10)
        try:
            result = function()
            return {"ok": True, "phase": getattr(result, "phase", None)}
        except AgentIdentityError as exc:
            return {"ok": False, "error": exc.code}

    try:
        with ThreadPoolExecutor(max_workers=count, thread_name_prefix=prefix) as pool:
            futures = [pool.submit(work, function) for function in functions]
            assert ready.wait(8), "Concurrent sessions did not reach task locking"
            with case.engine.connect() as observer:
                deadline = time.monotonic() + 6
                while time.monotonic() < deadline:
                    waiters = _lock_waiters(observer)
                    if waiters >= count:
                        break
                    time.sleep(0.02)
                assert waiters >= count, "Actual overlapping MySQL lock waits not observed"
            transaction.commit()
            results = [future.result(timeout=20) for future in futures]
    finally:
        if transaction.is_active:
            transaction.rollback()
        anchor.close()
        event.remove(case.engine, "before_cursor_execute", observe)
    assert len(connection_ids) == count
    record = {
        "case": label,
        "requests": count,
        "distinct_connections": len(connection_ids),
        "observed_lock_waiters": waiters,
        "successful": sum(row["ok"] for row in results),
        "rejected": sum(not row["ok"] for row in results),
        "outcomes": results,
    }
    EVIDENCE.append(record)
    return results, record


@pytest.mark.parametrize("command", ["admit", "claim"])
def test_eight_concurrent_admissions_and_claims(case, command):
    decide(case)
    payload = identity(case)
    if command == "claim":
        step(case, "admit", payload)
    results, record = contend(case, [lambda: step(case, command, payload)] * 8, "eight_" + command)
    assert sum(row["ok"] for row in results) == 1
    record["final_phase"] = step(case, "get").phase
    assert record["final_phase"] == ("ADMITTED" if command == "admit" else "RESUMING")


@pytest.mark.parametrize("change", ["approval", "consent", "task", "version"])
def test_revocation_racing_with_admission(case, change):
    decide(case)
    payload = identity(case)
    results, record = contend(
        case,
        [lambda: step(case, "admit", payload), lambda: mutate(case, change)],
        "admit_vs_" + change,
    )
    assert results[1]["ok"]
    with pytest.raises(AgentIdentityError):
        step(case, "claim", payload)
    record["final_phase"] = step(case, "get").phase
    assert record["final_phase"] == "DENIED"


def test_claim_racing_with_cancellation(case):
    decide(case)
    payload = identity(case)
    step(case, "admit", payload)
    _, record = contend(
        case,
        [lambda: step(case, "claim", payload), lambda: mutate(case, "task")],
        "claim_vs_cancellation",
    )
    with pytest.raises(AgentIdentityError):
        step(case, "complete", payload)
    record["final_phase"] = step(case, "get").phase
    assert record["final_phase"] == "DENIED"


def test_complete_racing_with_status(case):
    decide(case)
    payload = identity(case)
    step(case, "admit", payload)
    step(case, "claim", payload)
    results, record = contend(
        case,
        [lambda: step(case, "complete", payload), lambda: step(case, "get")],
        "complete_vs_status",
    )
    assert all(row["ok"] for row in results)
    assert results[0]["phase"] == "RESUMED" and results[1]["phase"] in ("RESUMING", "RESUMED")
    record["final_phase"] = step(case, "get").phase
    assert record["final_phase"] == "RESUMED"


def test_concurrent_conflicting_checkpoint(case):
    decide(case)
    payload = identity(case)
    bad = payload.model_copy(update={"checkpoint_id": str(uuid4())})
    results, record = contend(
        case,
        [lambda: step(case, "admit", payload), lambda: step(case, "admit", bad)],
        "conflicting_checkpoint",
    )
    assert results[0]["ok"] and not results[1]["ok"]
    record["final_phase"] = step(case, "get").phase


def test_transaction_commit_failure_rolls_back(case):
    decide(case)
    payload = identity(case)

    def fail(connection):
        raise OperationalError("synthetic commit failure", {}, Exception("redacted"))

    event.listen(case.engine, "commit", fail)
    try:
        with pytest.raises(AgentIdentityError):
            step(case, "admit", payload)
    finally:
        event.remove(case.engine, "commit", fail)
    assert step(case, "get").phase == "PAUSED"


def test_terminal_replay_and_duplicate_events(case):
    decide(case)
    payload = identity(case)
    for command in ("admit", "claim", "complete"):
        step(case, command, payload)
    for command in ("admit", "claim"):
        with pytest.raises(AgentIdentityError):
            step(case, command, payload)
    with pytest.raises(AgentIdentityError):
        step(case, "pause", WorkflowPause(checkpoint_id=payload.checkpoint_id))
    same = step(
        case,
        "prepare",
        WorkflowPrepare(
            task_ref=case.task.task_ref,
            approval_ref=case.binding.approval_ref,
            request_id=case.request.request_id,
            idempotency_key=case.request.idempotency_key,
        ),
    )
    assert same.binding_ref == case.binding.binding_ref and same.phase == "RESUMED"


@pytest.mark.parametrize("credential", ["agent", "invalid"])
def test_http_roles_fail_closed(case, mysql_client, credential):
    value = case.issued.token.get_secret_value() if credential == "agent" else "invalid-synthetic"
    response = mysql_client.post(
        f"/api/control/v1/workflow-checkpoints/{case.binding.binding_ref}/admit",
        json=identity(case).model_dump(mode="json"),
        headers={"Authorization": "Bearer " + value},
    )
    assert response.status_code in (401, 403)
    assert step(case, "get").phase == "PAUSED"


def test_managed_resource_deactivation(case):
    from app.models import DocumentResource, User
    from app.services.document_catalog import deactivate_resource

    owner_ref = "catalog_owner_" + uuid4().hex
    resource_ref, version_ref = "resource_" + uuid4().hex, "version_" + uuid4().hex
    with case.factory.begin() as db:
        db.add(User(id=owner_ref))
        db.flush()
        db.add(
            DocumentResource(
                resource_ref=resource_ref,
                owner_ref=owner_ref,
                resource_type="SYNTHETIC_TEXT",
                display_name="Synthetic metadata only",
                classification="SHAREABLE",
                storage_reference="ghost_demo_v1_doc_project_report",
                content_digest="a" * 64,
                version_ref=version_ref,
                active=True,
                created_at=case.now,
                updated_at=case.now,
            )
        )
    pin = ResourceVersion(
        resource_id=resource_ref, version_ref=version_ref, classification="SHAREABLE"
    )
    managed = pending(new_case(case.engine, pin=pin, owner_ref=owner_ref))
    decide(managed)
    payload = identity(managed)
    with managed.factory() as db:
        deactivate_resource(db, owner=managed.owner, resource_ref=resource_ref, now=managed.now)
    with pytest.raises(AgentIdentityError):
        step(managed, "admit", payload)
