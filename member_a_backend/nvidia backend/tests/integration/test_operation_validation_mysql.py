"""Step 13 tests; only the explicitly approved isolated MySQL runner may connect."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Lock, current_thread

import pytest
from app.agent_schemas import OwnerContext
from app.gateway_contracts import Authorization, ToolRequest, ToolResponse
from app.models import AuditEvent, GatewayOperation, GatewayTask
from app.services.agent_identity import (
    AgentIdentityError,
    issue_agent_credential,
    revoke_agent_credential,
)
from app.services.operation_ledger import (
    OperationError,
    admit_operation,
    get_operation_status,
    validate_transition,
)
from app.services.scoped_consent import record_decision, revoke_scoped_consent
from sqlalchemy import event, func, insert, inspect, select, text
from sqlalchemy.exc import DBAPIError, OperationalError
from tests.integration.test_identity_mysql import NOW, grant, new_task, request_for
from tests.integration.test_operation_mysql import call, count
from tests.integration.test_operation_mysql import ledger_binding as _ledger_binding

pytestmark = pytest.mark.integration
ledger_binding = _ledger_binding


@pytest.fixture(scope="session", autouse=True)
def require_step13_runner():
    if os.getenv("MYSQL_VALIDATION_PROJECT") not in (
        "ghost-ledger-validation",
        "ghost-approval-validation",
        "ghost-execution-validation",
        "ghost-catalog-validation",
        "ghost-document-validation",
        "ghost-mailpit-validation",
    ):
        pytest.skip("Requires the separately approved Step 13 disposable target")


def operation(binding):
    factory, (_, _, task, _), _ = binding
    with factory() as db:
        return db.scalar(select(GatewayOperation).where(GatewayOperation.task_ref == task.task_ref))


def test_mysql_admission_exact_replay_and_time(ledger_binding, mysql_engine):
    first = call(ledger_binding)
    assert call(ledger_binding) == first
    row = operation(ledger_binding)
    assert first.decision == "ALLOW" and first.execution_status == "NOT_EXECUTED"
    assert first.result is first.approval_ref is None
    assert row.operation_status == "ADMITTED" and row.audit_event_ref == first.audit_event_ref
    assert row.created_at == row.updated_at == NOW and row.created_at.microsecond == 678901
    assert row.execution_started_at is row.execution_finished_at is None
    assert count(ledger_binding) == 1
    with mysql_engine.connect() as db:
        assert db.get_isolation_level() == "READ COMMITTED"
        assert db.execute(text("SELECT @@session.time_zone")).scalar_one() == "+00:00"


@pytest.mark.parametrize("change", ["request", "key", "payload", "new_identity"])
def test_mysql_strict_replay_conflicts(ledger_binding, change):
    call(ledger_binding)
    changes = {
        "request": {"request_id": "req_conflicting"},
        "key": {"idempotency_key": "key_conflicting"},
        "payload": {"arguments": {"resource_id": "unknown_synthetic"}},
        "new_identity": {"request_id": "req_other", "idempotency_key": "key_other"},
    }[change]
    request = ToolRequest.model_validate_json(
        json.dumps({**ledger_binding[2].model_dump(mode="json"), **changes})
    )
    with pytest.raises(OperationError) as error:
        call(ledger_binding, request)
    assert error.value.status_code == 409
    assert error.value.code == (
        "LOGICAL_OPERATION_EXISTS" if change == "new_identity" else "IDEMPOTENCY_CONFLICT"
    )
    assert count(ledger_binding) == 1 and operation(ledger_binding).revision == 0


@pytest.mark.parametrize("different_owner", [False, True])
def test_mysql_task_and_owner_operation_isolation(ledger_binding, different_owner):
    factory, bound, original = ledger_binding
    first = call(ledger_binding)
    other = new_task(factory, None if different_owner else bound[0])
    grant(factory, other)
    request = original.model_copy(
        update={"task_ref": other[2].task_ref, "request_id": "req_isolated"}
    )
    second_binding = (factory, other, request)
    assert call(second_binding).decision == "ALLOW"
    assert count(ledger_binding) == count(second_binding) == 1
    with factory() as db:
        with pytest.raises(OperationError) as error:
            get_operation_status(db, token=other[3].token, request_id=first.request_id, now=NOW)
    assert error.value.status_code == 404


def test_mysql_ledger_constraints(ledger_binding, mysql_engine):
    call(ledger_binding)
    table = GatewayOperation.__table__
    reflected = inspect(mysql_engine)
    uniques = {tuple(item["column_names"]) for item in reflected.get_unique_constraints(table.name)}
    assert {
        ("owner_id", "request_id"),
        ("owner_id", "task_ref", "idempotency_key"),
        ("task_ref", "canonical_request_digest"),
    } <= uniques
    assert any(
        key["constrained_columns"] == ["task_ref", "owner_id"]
        and key["referred_table"] == "gateway_tasks"
        for key in reflected.get_foreign_keys(table.name)
    )
    assert any(item["column_names"] == ["task_ref"] for item in reflected.get_indexes(table.name))
    assert {"operation_ref", "request_id", "task_ref", "idempotency_key"} <= {
        column["name"]
        for column in reflected.get_columns(table.name)
        if getattr(column["type"], "collation", None) == "ascii_bin"
    }
    original = operation(ledger_binding)
    values = {column.name: getattr(original, column.name) for column in table.columns}
    cases = [
        (
            {
                "operation_ref": "op_duplicate_request",
                "idempotency_key": "key_new",
                "canonical_request_digest": "b" * 64,
            },
            1062,
        ),
        (
            {
                "operation_ref": "op_duplicate_key",
                "request_id": "req_new",
                "canonical_request_digest": "b" * 64,
            },
            1062,
        ),
        (
            {
                "operation_ref": "op_duplicate_digest",
                "request_id": "req_new",
                "idempotency_key": "key_new",
            },
            1062,
        ),
        (
            {
                "operation_ref": "op_bad_owner",
                "owner_id": "owner_nonexistent",
                "request_id": "req_new",
                "idempotency_key": "key_new",
                "canonical_request_digest": "b" * 64,
            },
            1452,
        ),
        (
            {
                "operation_ref": "op_bad_state",
                "request_id": "req_new",
                "idempotency_key": "key_new",
                "canonical_request_digest": "b" * 64,
                "operation_status": "UNKNOWN",
            },
            3819,
        ),
    ]
    for changes, expected in cases:
        with pytest.raises(DBAPIError) as error:
            with mysql_engine.begin() as db:
                db.execute(insert(table).values(**{**values, "audit_event_id": None, **changes}))
        assert error.value.orig.args[0] == expected
    assert count(ledger_binding) == 1


def test_mysql_outer_rollback_removes_operation_and_audit(ledger_binding, monkeypatch):
    def fail(*args, **kwargs):
        raise OperationalError("synthetic_audit_failure", {}, Exception("synthetic"))

    monkeypatch.setattr("app.services.operation_ledger.record_decision", fail)
    with pytest.raises(AgentIdentityError) as error:
        call(ledger_binding)
    assert error.value.code == "GATEWAY_UNAVAILABLE" and count(ledger_binding) == 0
    with ledger_binding[0]() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.user_id == ledger_binding[1][0].owner_id)
            )
            == 0
        )


@pytest.mark.parametrize("conflicting", [False, True])
def test_mysql_actual_unique_failure_reloads_identity(ledger_binding, monkeypatch, conflicting):
    import app.services.operation_ledger as ledger

    first = call(ledger_binding)
    original = ledger._candidates
    reads = []

    def miss_once(*args, **kwargs):
        reads.append(1)
        return [] if len(reads) == 1 else original(*args, **kwargs)

    # Fault injection misses the first lookup; the real MySQL unique index still rejects insertion.
    monkeypatch.setattr(ledger, "_candidates", miss_once)
    request = ledger_binding[2].model_copy(
        update={"purpose": "answer_question"} if conflicting else {}
    )
    if conflicting:
        with pytest.raises(OperationError, match="IDEMPOTENCY_CONFLICT"):
            call(ledger_binding, request)
    else:
        assert call(ledger_binding, request) == first
    assert len(reads) == 2 and count(ledger_binding) == 1


@pytest.mark.parametrize("revoked", [False, True])
def test_mysql_replay_rechecks_persisted_consent(ledger_binding, revoked):
    first = call(ledger_binding)
    factory, (owner, catalog, task, issued), request = ledger_binding
    if revoked:
        from app.models import ScopedConsent

        with factory() as db:
            consent = db.scalar(
                select(ScopedConsent).where(ScopedConsent.task_ref == task.task_ref)
            )
        with factory() as db:
            revoke_scoped_consent(
                db, owner=owner, task_ref=task.task_ref, consent_ref=consent.consent_ref, now=NOW
            )
    with factory() as db:
        result = admit_operation(
            db,
            token=issued.token,
            request=request,
            catalog=catalog,
            now=NOW if revoked else NOW + timedelta(minutes=10),
        )
    assert result.decision == "DENY" and result.execution_status == "NOT_EXECUTED"
    assert result.reason_code == ("CONSENT_REVOKED" if revoked else "CONSENT_EXPIRED")
    assert result.audit_event_ref != first.audit_event_ref
    assert operation(ledger_binding).revision == 1 and count(ledger_binding) == 1
    assert call(ledger_binding) == result


def test_mysql_replay_rechecks_revoked_credential(ledger_binding):
    call(ledger_binding)
    factory, (owner, _, task, issued), _ = ledger_binding
    with factory() as db:
        revoke_agent_credential(
            db, owner=owner, task_ref=task.task_ref, credential_ref=issued.credential_ref, now=NOW
        )
    with pytest.raises(AgentIdentityError) as error:
        call(ledger_binding)
    assert error.value.status_code == 401 and error.value.code == "AUTH_INVALID"
    assert count(ledger_binding) == 1 and operation(ledger_binding).revision == 0


def make_unknown(binding):
    """Persist simulated state transitions only; there is no handler or dispatch attempt."""
    call(binding)
    factory, (_, _, task, _), request = binding
    with factory() as db, db.begin():
        row = db.scalar(
            select(GatewayOperation)
            .where(GatewayOperation.task_ref == task.task_ref)
            .with_for_update()
        )
        validate_transition(
            "ADMITTED",
            "DISPATCHING",
            authorization=Authorization(decision="ALLOW", reason_code="EXECUTION_NOT_STARTED"),
            versions_match=True,
        )
        row.execution_started_at = NOW
        for state in ("DISPATCHING", "UNKNOWN"):
            row.operation_status = state
            row.reason_code = "EXECUTION_UNCONFIRMED"
            row.revision += 1
            ref = record_decision(
                db,
                task,
                request,
                Authorization(decision="ALLOW", reason_code="EXECUTION_UNCONFIRMED"),
                NOW,
                operation=row,
            )
            row.audit_event_id = int(ref.removeprefix("event_"))


def test_mysql_unknown_replays_without_retry(ledger_binding):
    make_unknown(ledger_binding)
    before = operation(ledger_binding)
    first = call(ledger_binding)
    assert first.execution_status == "UNKNOWN" and first.result is first.approval_ref is None
    assert call(ledger_binding) == first
    with pytest.raises(OperationError, match="IDEMPOTENCY_CONFLICT"):
        call(ledger_binding, ledger_binding[2].model_copy(update={"request_id": "req_new"}))
    after = operation(ledger_binding)
    assert count(ledger_binding) == 1 and before.revision == after.revision == 2
    assert after.audit_event_ref == first.audit_event_ref


@pytest.mark.parametrize("mode", ["identical", "request_ids", "payloads"])
def test_mysql_overlapping_sessions(ledger_binding, mysql_engine, mode):
    workers, requests = 4, 8
    barrier, lock = Barrier(workers), Lock()
    sessions, threads, errors = set(), set(), []

    def overlap(connection, cursor, statement, parameters, context, many):
        if (
            current_thread().name.startswith("step13-compete")
            and "gateway_tasks" in statement
            and "FOR UPDATE" in statement
        ):
            session = cursor.connection.thread_id()
            with lock:
                first = current_thread().name not in threads
                threads.add(current_thread().name)
                sessions.add(session)
            if first:
                barrier.wait(10)

    def database_error(context):
        code = getattr(context.original_exception, "args", (None,))[0]
        with lock:
            errors.append(code if isinstance(code, int) else "non_mysql")

    def submit(index):
        original = ledger_binding[2]
        changes = (
            {"request_id": f"req_competing_{index}"}
            if mode == "request_ids"
            else {"purpose": f"synthetic_purpose_{index}"}
            if mode == "payloads"
            else {}
        )
        try:
            return call(ledger_binding, original.model_copy(update=changes))
        except AgentIdentityError as error:
            return error.code

    event.listen(mysql_engine, "before_cursor_execute", overlap)
    event.listen(mysql_engine, "handle_error", database_error)
    try:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="step13-compete") as pool:
            results = list(pool.map(submit, range(requests)))
    finally:
        event.remove(mysql_engine, "before_cursor_execute", overlap)
        event.remove(mysql_engine, "handle_error", database_error)
    responses = [result for result in results if isinstance(result, ToolResponse)]
    conflicts = results.count("IDEMPOTENCY_CONFLICT")
    row = operation(ledger_binding)
    print(
        json.dumps(
            {
                "case": mode,
                "requests": requests,
                "overlapping_sessions": len(sessions),
                "responses": len(responses),
                "allow": sum(r.decision == "ALLOW" for r in responses),
                "conflicts": conflicts,
                "operations": count(ledger_binding),
                "final_state": row.operation_status,
                "mysql_errors": errors,
                "isolation": "READ COMMITTED",
            }
        )
    )
    assert len(sessions) >= workers and len(threads) == workers and count(ledger_binding) == 1
    assert not errors
    assert len(responses) == (requests if mode == "identical" else 1)
    assert conflicts == (0 if mode == "identical" else requests - 1)


@pytest.mark.parametrize("state", ["ADMITTED", "UNKNOWN"])
def test_mysql_ledger_restart_writer(mysql_engine, state):
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(mysql_engine, autoflush=False, expire_on_commit=False)
    bound = new_task(factory, OwnerContext(owner_id=f"step13_restart_{state}"))
    grant(factory, bound)
    binding = (
        factory,
        bound,
        request_for(
            bound[2], request_id=f"req_restart_{state}", idempotency_key=f"key_restart_{state}"
        ),
    )
    if state == "UNKNOWN":
        make_unknown(binding)
    else:
        call(binding)
    assert operation(binding).operation_status == state


@pytest.mark.parametrize("state", ["ADMITTED", "UNKNOWN"])
def test_mysql_ledger_restart_reader(mysql_engine, state):
    from app.services.resource_catalog import CatalogResource, ResourceCatalog
    from sqlalchemy.orm import sessionmaker
    from tests.integration.test_identity_mysql import PIN

    factory = sessionmaker(mysql_engine, autoflush=False, expire_on_commit=False)
    owner = OwnerContext(owner_id=f"step13_restart_{state}")
    with factory() as db:
        task = db.scalar(select(GatewayTask).where(GatewayTask.owner_id == owner.owner_id))
        before = db.scalar(
            select(GatewayOperation).where(GatewayOperation.task_ref == task.task_ref)
        )
    # New process obtains a new synthetic token; no plaintext token crosses the restart.
    with factory() as db:
        issued = issue_agent_credential(db, owner=owner, task_ref=task.task_ref, now=NOW)
    catalog = ResourceCatalog(
        resources=(CatalogResource(**PIN.model_dump(), owner_id=owner.owner_id),)
    )
    request = request_for(
        task, request_id=f"req_restart_{state}", idempotency_key=f"key_restart_{state}"
    )
    binding = (factory, (owner, catalog, task, issued), request)
    response = call(binding)
    after = operation(binding)
    assert response.execution_status == ("UNKNOWN" if state == "UNKNOWN" else "NOT_EXECUTED")
    assert (
        after.operation_ref == before.operation_ref
        and after.audit_event_id == before.audit_event_id
    )
    assert after.revision == before.revision and count(binding) == 1
