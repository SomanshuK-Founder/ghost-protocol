"""Step 16: opt-in tests for the separately verified disposable MySQL target."""

import json
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from threading import Barrier, Event, Lock, current_thread

import pytest
from app.agent_schemas import OwnerContext
from app.database import get_db
from app.gateway_contracts import ConsentCreate, ToolRequest
from app.main import app
from app.models import AuditEvent, GatewayOperation, GatewayTask, PendingApproval, ScopedConsent
from app.services.agent_identity import (
    AgentIdentityError,
    create_trusted_task,
    issue_agent_credential,
    revoke_agent_credential,
    revoke_trusted_task,
)
from app.services.approvals import owner_approval
from app.services.operation_ledger import OperationError, admit_operation, get_operation_status
from app.services.resource_catalog import CatalogResource, ResourceCatalog, get_resource_catalog
from app.services.scoped_consent import create_scoped_consent, revoke_scoped_consent
from fastapi.testclient import TestClient
from sqlalchemy import event, insert, inspect, select
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import sessionmaker
from tests.integration.test_identity_mysql import NOW, PIN, SCOPE, request_for

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session", autouse=True)
def require_step16_runner():
    if os.getenv("MYSQL_VALIDATION_PROJECT") not in (
        "ghost-approval-validation",
        "ghost-execution-validation",
        "ghost-catalog-validation",
        "ghost-document-validation",
        "ghost-mailpit-validation",
    ):
        pytest.skip("Requires the separately approved Step 16 disposable MySQL target")


@dataclass
class Binding:
    factory: object
    owner: OwnerContext
    catalog: ResourceCatalog
    task: GatewayTask
    issued: object
    request: ToolRequest


def new_binding(engine, *, enabled=True, request_id=None):
    factory = sessionmaker(engine, autoflush=False, expire_on_commit=False)
    owner = OwnerContext(owner_id="local-user")
    scope = SCOPE.model_copy(update={"approval_enabled": enabled})
    catalog = ResourceCatalog(
        resources=(CatalogResource(**PIN.model_dump(), owner_id=owner.owner_id),)
    )
    with factory() as db:
        task = create_trusted_task(
            db,
            owner=owner,
            scope=scope,
            catalog=catalog,
            now=NOW,
            expires_at=NOW + timedelta(hours=1),
        )
    with factory() as db:
        issued = issue_agent_credential(db, owner=owner, task_ref=task.task_ref, now=NOW)
    return Binding(
        factory,
        owner,
        catalog,
        task,
        issued,
        request_for(task, **({"request_id": request_id} if request_id else {})),
    )


@pytest.fixture
def binding(mysql_engine):
    return new_binding(mysql_engine)


def admit(bound, *, request=None, now=NOW):
    with bound.factory() as db:
        return admit_operation(
            db,
            token=bound.issued.token,
            request=request or bound.request,
            catalog=bound.catalog,
            now=now,
        )


def approval(bound):
    with bound.factory() as db:
        return db.scalar(
            select(PendingApproval).where(PendingApproval.task_ref == bound.task.task_ref)
        )


def decide(bound, resolution=None, *, revoke=False, now=NOW, owner=None):
    ref = approval(bound).approval_ref
    with bound.factory() as db:
        return owner_approval(
            db,
            owner=owner or bound.owner,
            approval_ref=ref,
            resolution=resolution,
            revoke=revoke,
            catalog=bound.catalog,
            now=now,
        )


def status(bound, *, now=NOW):
    with bound.factory() as db:
        return get_operation_status(
            db,
            token=bound.issued.token,
            request_id=bound.request.request_id,
            catalog=bound.catalog,
            now=now,
        )


def snapshot(bound):
    """Independent committed reads; references and counts only, never token or payload bytes."""
    with bound.factory() as db:
        approvals = list(
            db.scalars(
                select(PendingApproval).where(PendingApproval.task_ref == bound.task.task_ref)
            )
        )
        operations = list(
            db.scalars(
                select(GatewayOperation).where(GatewayOperation.task_ref == bound.task.task_ref)
            )
        )
        grants = list(
            db.scalars(
                select(ScopedConsent).where(
                    ScopedConsent.task_ref == bound.task.task_ref,
                    ScopedConsent.bound_operation_ref.is_not(None),
                )
            )
        )
        assert len(approvals) == len(operations) == 1
        row, operation = approvals[0], operations[0]
        assert row.owner_id == operation.owner_id == bound.owner.owner_id
        assert (
            row.operation_ref == operation.operation_ref
            and row.request_id == bound.request.request_id
        )
        assert row.audit_event_id and db.get(AuditEvent, row.audit_event_id).outcome == row.status
        assert (
            operation.audit_event_id
            and db.get(AuditEvent, operation.audit_event_id).detail["operation_ref"]
            == operation.operation_ref
        )
        assert row.authorization_version == operation.authorization_version
        expected = {"PENDING": "PENDING_APPROVAL", "APPROVED": "READY"}.get(row.status, "DENIED")
        assert operation.operation_status == expected
        assert operation.execution_started_at is operation.execution_finished_at is None
        active = [grant for grant in grants if grant.revoked_at is None]
        if row.status == "APPROVED":
            assert len(active) == 1 and active[0].consent_ref == row.consent_ref
            assert active[0].bound_operation_ref == operation.operation_ref
            assert active[0].expires_at == row.expires_at
            assert (
                db.get(GatewayTask, row.task_ref).authorization_version == row.authorization_version
            )
            assert operation.decision == "APPROVAL_REQUIRED"
        else:
            assert not active
        return {
            "approval_ref": row.approval_ref,
            "operation_ref": operation.operation_ref,
            "request_id": row.request_id,
            "approval_state": row.status,
            "operation_state": operation.operation_status,
            "approval_revision": row.revision,
            "operation_revision": operation.revision,
            "approval_audit_id": row.audit_event_id,
            "operation_audit_id": operation.audit_event_id,
            "approval_records": len(approvals),
            "operation_records": len(operations),
            "bound_consents": len(grants),
            "active_bound_consents": len(active),
        }


def test_mysql_pending_creation_and_exact_retry(binding):
    first = admit(binding)
    assert first.decision == "APPROVAL_REQUIRED" and first.execution_status == "NOT_EXECUTED"
    assert first.result is None and first.approval_ref == approval(binding).approval_ref
    assert admit(binding) == first
    row = approval(binding)
    assert row.created_at == NOW and row.expires_at == NOW + timedelta(minutes=10)
    assert row.created_at.microsecond == 678901
    assert snapshot(binding)["approval_state"] == "PENDING"


@pytest.mark.parametrize(
    "changes",
    [
        {"request_id": "req_conflicting"},
        {"idempotency_key": "key_conflicting"},
        {"purpose": "answer_question"},
        {"arguments": {"resource_id": "other_synthetic"}},
    ],
)
def test_mysql_approval_strict_identity(binding, changes):
    admit(binding)
    request = ToolRequest.model_validate_json(
        json.dumps({**binding.request.model_dump(mode="json"), **changes})
    )
    with pytest.raises(OperationError) as error:
        admit(binding, request=request)
    assert error.value.status_code == 409 and error.value.code == "IDEMPOTENCY_CONFLICT"
    assert snapshot(binding)["approval_records"] == 1


def test_mysql_owner_approval_is_not_execution(binding):
    admit(binding)
    first = decide(binding, "APPROVE")
    assert decide(binding, "APPROVE") == first
    result = status(binding)
    assert result.operation_state == "READY" and result.execution_status == "NOT_EXECUTED"
    assert result.decision == "APPROVAL_REQUIRED" and result.resume_ref
    with pytest.raises(OperationError, match="RESUME_REQUIRED"):
        admit(binding)
    assert snapshot(binding)["active_bound_consents"] == 1


@pytest.mark.parametrize(
    "mode", ["reject", "revoke", "expire", "approved_expire", "approved_revoke"]
)
def test_mysql_terminal_approval_cannot_reactivate(binding, mode):
    admit(binding)
    if mode.startswith("approved"):
        decide(binding, "APPROVE")
    if "expire" in mode:
        with pytest.raises(OperationError, match="APPROVAL_ALREADY_RESOLVED"):
            decide(binding, "APPROVE", now=NOW + timedelta(minutes=10))
        expected = "EXPIRED"
    elif "revoke" in mode:
        assert decide(binding, revoke=True)["state"] == "REVOKED"
        expected = "REVOKED"
    else:
        assert decide(binding, "REJECT")["state"] == "REJECTED"
        expected = "REJECTED"
    with pytest.raises(OperationError, match="APPROVAL_ALREADY_RESOLVED"):
        decide(binding, "APPROVE")
    result = admit(binding)
    assert result.decision == "DENY" and result.reason_code == f"APPROVAL_{expected}"
    assert result.approval_ref is result.result is None
    assert snapshot(binding)["approval_state"] == expected


def test_mysql_wrong_owner_and_agent_cannot_approve(binding, monkeypatch):
    pending = admit(binding)
    with pytest.raises(AgentIdentityError) as error:
        decide(binding, "APPROVE", owner=OwnerContext(owner_id="foreign_owner"))
    assert error.value.status_code == 404

    def override_db():
        with binding.factory() as db:
            yield db

    for module in ("agent_identity", "operation_ledger", "approvals", "scoped_consent"):
        monkeypatch.setattr(
            f"app.services.{module}._utc", lambda value: value if value is not None else NOW
        )
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_resource_catalog] = lambda: binding.catalog
    try:
        with TestClient(app) as client:
            agent = {"Authorization": "Bearer " + binding.issued.token.get_secret_value()}
            for method, path, body in [
                ("GET", "/api/control/v1/approvals?task_ref=" + binding.task.task_ref, None),
                ("GET", f"/api/control/v1/approvals/{pending.approval_ref}", None),
                (
                    "POST",
                    f"/api/control/v1/approvals/{pending.approval_ref}/resolve",
                    {"resolution": "APPROVE"},
                ),
                (
                    "POST",
                    f"/api/control/v1/approvals/{pending.approval_ref}/resolve",
                    {"resolution": "REJECT"},
                ),
                ("POST", f"/api/control/v1/approvals/{pending.approval_ref}/revoke", {}),
            ]:
                response = client.request(method, path, headers=agent, json=body)
                assert response.status_code == 401
            owner = {"Authorization": "Bearer " + os.environ["API_BEARER_TOKEN"]}
            review = client.get(f"/api/control/v1/approvals/{pending.approval_ref}", headers=owner)
            assert review.status_code == 200 and review.headers["cache-control"] == "no-store"
            response = client.post(
                f"/api/control/v1/approvals/{pending.approval_ref}/resolve",
                headers=owner,
                json={"resolution": "APPROVE"},
            )
            assert response.status_code == 200 and response.json()["state"] == "APPROVED"
    finally:
        app.dependency_overrides.clear()
    assert snapshot(binding)["active_bound_consents"] == 1


def test_mysql_approval_schema_and_constraints(binding, mysql_engine):
    admit(binding)
    inspector = inspect(mysql_engine)
    table = PendingApproval.__table__
    assert {column["name"] for column in inspector.get_columns(table.name)} == set(
        table.columns.keys()
    )
    assert any(
        key["constrained_columns"] == ["operation_ref", "task_ref", "owner_id"]
        and key["referred_table"] == "gateway_operations"
        for key in inspector.get_foreign_keys(table.name)
    )
    assert {("operation_ref",), ("consent_ref",), ("resume_ref",)} <= {
        tuple(key["column_names"]) for key in inspector.get_unique_constraints(table.name)
    }
    assert {("consent_ref",), ("audit_event_id",)} <= {
        tuple(key["constrained_columns"]) for key in inspector.get_foreign_keys(table.name)
    }
    assert all(
        getattr(column["type"], "fsp", None) == 6
        for column in inspector.get_columns(table.name)
        if column["name"] in ("created_at", "expires_at", "decided_at")
    )
    assert any(index["column_names"] == ["task_ref"] for index in inspector.get_indexes(table.name))
    row = approval(binding)
    values = {column.name: getattr(row, column.name) for column in table.columns}
    other = new_binding(mysql_engine, enabled=False)
    assert admit(other).decision == "DENY"
    with other.factory() as db:
        unused = db.scalar(
            select(GatewayOperation).where(GatewayOperation.task_ref == other.task.task_ref)
        )
    fresh = {
        **values,
        "approval_ref": "approval_negative",
        "operation_ref": unused.operation_ref,
        "task_ref": other.task.task_ref,
        "owner_id": other.owner.owner_id,
    }
    for changes, code in [
        ({**values, "approval_ref": "approval_duplicate"}, 1062),
        ({**fresh, "task_ref": binding.task.task_ref}, 1452),
        ({**fresh, "owner_id": "foreign_owner"}, 1452),
        ({**fresh, "status": "CANCELLED", "decided_at": NOW}, 3819),
        ({**fresh, "expires_at": NOW}, 3819),
        ({**fresh, "status": "APPROVED", "decided_at": NOW}, 3819),
        ({**fresh, "audit_event_id": -1}, 1452),
        ({**fresh, "authorization_version": -1}, 3819),
    ]:
        with pytest.raises(DBAPIError) as error:
            with mysql_engine.begin() as db:
                db.execute(insert(table).values(**changes))
        assert error.value.orig.args[0] == code
    assert snapshot(binding)["approval_records"] == 1


def test_mysql_approval_audit_failure_rolls_back_grant(binding, monkeypatch):
    first = admit(binding)

    def fail(*args, **kwargs):
        raise OperationalError("synthetic_audit_failure", {}, Exception("synthetic"))

    monkeypatch.setattr("app.services.approvals.audit_approval", fail)
    with pytest.raises(AgentIdentityError, match="GATEWAY_UNAVAILABLE"):
        decide(binding, "APPROVE")
    assert admit(binding) == first
    assert snapshot(binding)["approval_state"] == "PENDING"


MODES = (
    "approve_reject",
    "approve_revoke",
    "approve_expiry",
    "two_approvals",
    "two_rejections",
    "duplicate_creation",
    "consent_revoke",
    "task_cancel",
    "credential_revoke",
)


@pytest.mark.parametrize("mode", MODES)
def test_mysql_overlapping_approval_transactions(binding, mysql_engine, monkeypatch, mode):
    consent = None
    if mode == "consent_revoke":
        with binding.factory() as db:
            consent = create_scoped_consent(
                db,
                owner=binding.owner,
                task_ref=binding.task.task_ref,
                payload=ConsentCreate(
                    action="tasks.list",
                    purpose=SCOPE.purpose,
                    resource_ids=(),
                    expires_at=NOW + timedelta(minutes=10),
                ),
                catalog=binding.catalog,
                now=NOW,
            )
    if mode != "duplicate_creation":
        admit(binding)
    requests = 8 if mode == "duplicate_creation" else 2
    workers = min(requests, 4)
    barrier, lock = Barrier(workers), Lock()
    threads, sessions, commits, errors = set(), set(), [], []
    original_commit = mysql_engine.dialect.do_commit

    def committed(connection):
        original_commit(connection)
        if current_thread().name.startswith("approval-compete"):
            with lock:
                commits.append(1)

    monkeypatch.setattr(mysql_engine.dialect, "do_commit", committed)

    def overlap(connection, cursor, statement, parameters, context, many):
        if (
            current_thread().name.startswith("approval-compete")
            and "gateway_tasks" in statement
            and "FOR UPDATE" in statement
        ):
            with lock:
                first = current_thread().name not in threads
                threads.add(current_thread().name)
                sessions.add(cursor.connection.thread_id())
            if first:
                barrier.wait(10)

    def database_error(context):
        if current_thread().name.startswith("approval-compete"):
            code = getattr(context.original_exception, "args", (None,))[0]
            with lock:
                errors.append(code if isinstance(code, int) else "non_mysql")

    def submit(index):
        try:
            if mode == "duplicate_creation":
                value = admit(binding)
                return {"http": 200, "state": "PENDING", "approval_ref": value.approval_ref}
            if index == 0 or mode in ("two_approvals", "two_rejections"):
                result = decide(
                    binding,
                    "REJECT" if mode == "two_rejections" else "APPROVE",
                    now=NOW + timedelta(minutes=9, seconds=59) if mode == "approve_expiry" else NOW,
                )
                return {"http": 200, "state": result["state"]}
            if mode == "approve_reject":
                result = decide(binding, "REJECT")
            elif mode == "approve_revoke":
                result = decide(binding, revoke=True)
            elif mode == "approve_expiry":
                result = decide(binding, now=NOW + timedelta(minutes=10))
                return {"http": 200, "state": result.state}
            else:
                with binding.factory() as db:
                    if mode == "task_cancel":
                        revoke_trusted_task(
                            db, owner=binding.owner, task_ref=binding.task.task_ref, now=NOW
                        )
                    elif mode == "credential_revoke":
                        revoke_agent_credential(
                            db,
                            owner=binding.owner,
                            task_ref=binding.task.task_ref,
                            credential_ref=binding.issued.credential_ref,
                            now=NOW,
                        )
                    else:
                        revoke_scoped_consent(
                            db,
                            owner=binding.owner,
                            task_ref=binding.task.task_ref,
                            consent_ref=consent.consent_ref,
                            now=NOW,
                        )
                return {"http": 200, "state": "REVOKED"}
            return {"http": 200, "state": result["state"]}
        except AgentIdentityError as error:
            return {"http": error.status_code, "error": error.code}

    event.listen(mysql_engine, "before_cursor_execute", overlap)
    event.listen(mysql_engine, "handle_error", database_error)
    try:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="approval-compete") as pool:
            outcomes = list(pool.map(submit, range(requests)))
    finally:
        event.remove(mysql_engine, "before_cursor_execute", overlap)
        event.remove(mysql_engine, "handle_error", database_error)
    final = snapshot(binding)
    report = {
        "case": mode,
        "requests": requests,
        "overlapping_sessions": len(sessions),
        "workers_at_lock_barrier": len(threads),
        "confirmed_commits": len(commits),
        "responses_200": sum(item["http"] == 200 for item in outcomes),
        "responses_conflict": sum(item["http"] == 409 for item in outcomes),
        "outcomes": outcomes,
        "mysql_errors": errors,
        "isolation": "READ COMMITTED",
        **final,
    }
    print(json.dumps(report))
    assert len(threads) == workers and len(sessions) >= workers
    assert not errors and len(commits) == requests
    assert all(item["http"] in (200, 409) for item in outcomes)
    if mode == "duplicate_creation":
        assert (
            final["approval_state"] == "PENDING"
            and len({item["approval_ref"] for item in outcomes}) == 1
        )
    elif mode == "two_approvals":
        assert final["approval_state"] == "APPROVED" and all(
            item["http"] == 200 for item in outcomes
        )
    elif mode == "two_rejections":
        assert final["approval_state"] == "REJECTED" and all(
            item["http"] == 200 for item in outcomes
        )
    elif mode == "approve_reject":
        assert final["approval_state"] in ("APPROVED", "REJECTED")
        assert sum(item["http"] == 409 for item in outcomes) == 1
    else:
        assert final["approval_state"] == ("EXPIRED" if mode == "approve_expiry" else "REVOKED")
        assert final["active_bound_consents"] == 0


@pytest.mark.parametrize("kind", ["consent", "task", "credential", "expiry"])
def test_mysql_revocation_lock_wins_before_approval(binding, mysql_engine, monkeypatch, kind):
    import app.services.agent_identity as identity
    import app.services.approvals as approvals
    import app.services.scoped_consent as policy

    consent = None
    if kind == "consent":
        with binding.factory() as db:
            consent = create_scoped_consent(
                db,
                owner=binding.owner,
                task_ref=binding.task.task_ref,
                payload=ConsentCreate(
                    action="tasks.list",
                    purpose=SCOPE.purpose,
                    resource_ids=(),
                    expires_at=NOW + timedelta(minutes=10),
                ),
                catalog=binding.catalog,
                now=NOW,
            )
    admit(binding)
    module = policy if kind == "consent" else approvals if kind == "expiry" else identity
    original = module._owned_task
    locked, attempted, release = Event(), Event(), Event()

    def hold(*args, **kwargs):
        value = original(*args, **kwargs)
        locked.set()
        if not release.wait(8):
            raise RuntimeError("Test lock release timed out")
        return value

    def observe(connection, cursor, statement, parameters, context, many):
        if (
            current_thread().name.startswith("approval-waiter")
            and "gateway_tasks" in statement
            and "FOR UPDATE" in statement
        ):
            attempted.set()

    def write():
        if kind == "expiry":
            return decide(binding, now=NOW + timedelta(minutes=10)).state
        with binding.factory() as db:
            if kind == "task":
                revoke_trusted_task(
                    db, owner=binding.owner, task_ref=binding.task.task_ref, now=NOW
                )
            elif kind == "credential":
                revoke_agent_credential(
                    db,
                    owner=binding.owner,
                    task_ref=binding.task.task_ref,
                    credential_ref=binding.issued.credential_ref,
                    now=NOW,
                )
            else:
                revoke_scoped_consent(
                    db,
                    owner=binding.owner,
                    task_ref=binding.task.task_ref,
                    consent_ref=consent.consent_ref,
                    now=NOW,
                )
        return "REVOKED"

    def read():
        try:
            return decide(binding, "APPROVE")["state"]
        except OperationError as error:
            return error.code

    monkeypatch.setattr(module, "_owned_task", hold)
    event.listen(mysql_engine, "before_cursor_execute", observe)
    try:
        with (
            ThreadPoolExecutor(max_workers=1) as writers,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="approval-waiter") as readers,
        ):
            writer = writers.submit(write)
            assert locked.wait(5)
            reader = readers.submit(read)
            try:
                assert attempted.wait(5)
                with pytest.raises(TimeoutError):
                    reader.result(0.2)
            finally:
                release.set()
            writer_state = writer.result(5)
            outcome = reader.result(5)
    finally:
        release.set()
        event.remove(mysql_engine, "before_cursor_execute", observe)
    final = snapshot(binding)
    print(
        json.dumps(
            {
                "case": f"{kind}_lock_first",
                "requests": 2,
                "blocked_reader_ms": 200,
                "writer_state": writer_state,
                "reader_outcome": outcome,
                **final,
            }
        )
    )
    assert outcome == "APPROVAL_ALREADY_RESOLVED"
    assert final["approval_state"] == ("EXPIRED" if kind == "expiry" else "REVOKED")
    assert final["bound_consents"] == final["active_bound_consents"] == 0


STATES = ("PENDING", "APPROVED", "REJECTED", "REVOKED", "EXPIRED")


@pytest.mark.parametrize("state", STATES)
def test_mysql_approval_restart_writer(mysql_engine, state):
    bound = new_binding(mysql_engine, request_id=f"req_approval_restart_{state}")
    admit(bound)
    if state in ("APPROVED", "REVOKED", "EXPIRED"):
        decide(bound, "APPROVE")
    if state == "REJECTED":
        decide(bound, "REJECT")
    elif state == "REVOKED":
        decide(bound, revoke=True)
    elif state == "EXPIRED":
        decide(bound, now=NOW + timedelta(minutes=10))
    result = snapshot(bound)
    assert result["approval_state"] == state
    print(json.dumps({"restart_expected": result}))


@pytest.mark.parametrize("state", STATES)
def test_mysql_approval_restart_reader(mysql_engine, state):
    expected = {
        item["approval_state"]: item
        for item in json.loads(Path("/validation/restart_expected.json").read_text())
    }[state]
    factory = sessionmaker(mysql_engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        record = db.get(PendingApproval, expected["approval_ref"])
        task = db.get(GatewayTask, record.task_ref)
    owner = OwnerContext(owner_id=record.owner_id)
    catalog = ResourceCatalog(
        resources=(CatalogResource(**PIN.model_dump(), owner_id=owner.owner_id),)
    )
    with factory() as db:
        issued = issue_agent_credential(db, owner=owner, task_ref=task.task_ref, now=NOW)
    bound = Binding(
        factory,
        owner,
        catalog,
        task,
        issued,
        request_for(task, request_id=record.request_id, idempotency_key=record.idempotency_key),
    )
    actual = snapshot(bound)
    assert actual == expected
    result = status(bound)
    assert result.approval_state == state and result.execution_status == "NOT_EXECUTED"
    if state in ("REJECTED", "EXPIRED", "REVOKED"):
        with pytest.raises(OperationError, match="APPROVAL_ALREADY_RESOLVED"):
            decide(bound, "APPROVE")
    assert snapshot(bound) == expected
    print(json.dumps({"restart_state": state, "same_operation_approval_audit_revisions": True}))
