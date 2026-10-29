"""Step 19: synthetic dispatch against the explicitly approved disposable MySQL."""

import json
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import timedelta
from pathlib import Path
from threading import Barrier, Event, Lock, current_thread

import pytest
from app.agent_schemas import OwnerContext
from app.gateway_contracts import ToolRequest
from app.models import ExecutionAttempt, GatewayOperation, GatewayTask, PendingApproval
from app.services.agent_identity import (
    AgentIdentityError,
    issue_agent_credential,
    revoke_agent_credential,
    revoke_trusted_task,
)
from app.services.operation_ledger import OperationError, _history, admit_operation
from app.services.scoped_consent import revoke_scoped_consent
from app.services.synthetic_executor import SyntheticExecutor
from app.services.trusted_execution import dispatch_simulated
from sqlalchemy import event, insert, inspect, select, text, update
from sqlalchemy.exc import DBAPIError, OperationalError
from tests.integration.test_approval_mysql import (
    admit,
    approval,
    decide,
    new_binding,
    status,
)
from tests.integration.test_identity_mysql import NOW, grant, new_task, request_for

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session", autouse=True)
def require_execution_target():
    if os.getenv("MYSQL_VALIDATION_PROJECT") not in (
        "ghost-execution-validation",
        "ghost-catalog-validation",
        "ghost-document-validation",
        "ghost-mailpit-validation",
    ):
        pytest.skip("Requires the explicitly approved Step 19 isolated MySQL target")


@pytest.fixture
def execution_binding(mysql_engine):
    bound = new_binding(mysql_engine)
    assert admit(bound).decision == "APPROVAL_REQUIRED"
    decide(bound, "APPROVE")
    assert status(bound).operation_state == "READY"
    return bound


def dispatch(bound, *, executor=None, request=None, now=NOW):
    with bound.factory() as db:
        return dispatch_simulated(
            db,
            token=bound.issued.token,
            request=request or bound.request,
            catalog=bound.catalog,
            executor=executor,
            now=now,
            timeout_seconds=5,
        )


def snapshot(bound):
    with bound.factory() as db:
        operations = list(
            db.scalars(
                select(GatewayOperation).where(GatewayOperation.task_ref == bound.task.task_ref)
            )
        )
        assert len(operations) == 1
        operation = operations[0]
        _history(db, operation)
        attempts = list(
            db.scalars(
                select(ExecutionAttempt).where(
                    ExecutionAttempt.operation_ref == operation.operation_ref
                )
            )
        )
        row = db.scalar(
            select(PendingApproval).where(PendingApproval.operation_ref == operation.operation_ref)
        )
        return {
            "task_ref": bound.task.task_ref,
            "operation_ref": operation.operation_ref,
            "request_id": operation.request_id,
            "operation_state": operation.operation_status,
            "operation_records": len(operations),
            "attempts": len(attempts),
            "attempt_ref": attempts[0].attempt_ref if attempts else None,
            "attempt_state": attempts[0].state if attempts else None,
            "revision": operation.revision,
            "audit_id": operation.audit_event_id,
            "approval_state": row.status if row else None,
            "consumed_at": row.consumed_at.isoformat() if row and row.consumed_at else None,
        }


@pytest.mark.parametrize("outcome", ["SUCCEEDED", "FAILED", "UNKNOWN"])
def test_mysql_execution_outcomes_and_exact_replay(execution_binding, outcome):
    bound = execution_binding
    executor = SyntheticExecutor(outcome)
    first = dispatch(bound, executor=executor)
    assert first.mode == "SIMULATED" and first.response.execution_status == outcome
    assert dispatch(bound, executor=executor) == first
    with bound.factory() as db:
        replay = admit_operation(
            db, token=bound.issued.token, request=bound.request, catalog=bound.catalog, now=NOW
        )
    assert replay == first.response and executor.calls == 1
    if outcome == "SUCCEEDED":
        assert first.response.result.text == "SIMULATED: no document was read."
    else:
        assert first.response.result is None
    final = snapshot(bound)
    assert final["operation_state"] == final["attempt_state"] == outcome
    assert final["attempts"] == 1 and final["consumed_at"] == NOW.isoformat()
    assert status(bound).resume_ref is None
    print(
        json.dumps(
            {"case": "execution_outcome_" + outcome, "executor_calls": executor.calls, **final}
        )
    )


@pytest.mark.parametrize("change", ["request", "key", "payload"])
def test_mysql_execution_identity_conflicts(execution_binding, change):
    bound = execution_binding
    executor = SyntheticExecutor()
    dispatch(bound, executor=executor)
    changes = {
        "request": {"request_id": "req_step19_conflict"},
        "key": {"idempotency_key": "key_step19_conflict"},
        "payload": {"purpose": "answer_question"},
    }[change]
    request = ToolRequest.model_validate_json(
        json.dumps({**bound.request.model_dump(mode="json"), **changes})
    )
    with pytest.raises(OperationError, match="IDEMPOTENCY_CONFLICT") as error:
        dispatch(bound, executor=executor, request=request)
    assert error.value.status_code == 409 and executor.calls == 1
    assert snapshot(bound)["attempts"] == 1


def test_mysql_denied_operation_has_no_attempt(mysql_engine):
    bound = new_binding(mysql_engine, enabled=False)
    assert admit(bound).decision == "DENY"
    executor = SyntheticExecutor()
    with pytest.raises(AgentIdentityError):
        dispatch(bound, executor=executor)
    assert executor.calls == 0 and snapshot(bound)["attempts"] == 0


def test_mysql_execution_schema_constraints(execution_binding, mysql_engine):
    bound = execution_binding
    dispatch(bound)
    inspector = inspect(mysql_engine)
    table = ExecutionAttempt.__table__
    assert {c["name"] for c in inspector.get_columns(table.name)} == set(table.columns.keys())
    assert {("operation_ref",), ("dispatch_nonce",)} <= {
        tuple(k["column_names"]) for k in inspector.get_unique_constraints(table.name)
    }
    assert {("operation_ref",), ("audit_event_id",)} <= {
        tuple(k["constrained_columns"]) for k in inspector.get_foreign_keys(table.name)
    }
    assert {
        "ck_attempt_mode",
        "ck_attempt_state",
        "ck_attempt_times",
        "ck_attempt_result",
    } <= {c["name"] for c in inspector.get_check_constraints(table.name)}
    with bound.factory() as db:
        attempt = db.scalar(
            select(ExecutionAttempt).where(
                ExecutionAttempt.operation_ref == snapshot(bound)["operation_ref"]
            )
        )
        assert attempt.dispatch_at == attempt.completed_at == NOW
        assert attempt.dispatch_at.microsecond == 678901
        assert attempt.audit_event_id == snapshot(bound)["audit_id"]
        values = {c.name: getattr(attempt, c.name) for c in table.columns}
    mutations = [
        ({"attempt_ref": "attempt_duplicate", "operation_ref": values["operation_ref"]}, 1062),
        (
            {
                "attempt_ref": "attempt_bad_fk",
                "operation_ref": "op_missing",
                "dispatch_nonce": "a" * 64,
            },
            1452,
        ),
        ({"mode": "REAL"}, 3819),
        ({"state": "EXECUTING"}, 3819),
        ({"completed_at": NOW - timedelta(microseconds=1)}, 3819),
        ({"audit_event_id": -1}, 1452),
    ]
    for number, (changed, expected) in enumerate(mutations):
        probe = new_binding(mysql_engine)
        admit(probe)
        operation_ref = snapshot(probe)["operation_ref"]
        candidate = {
            **values,
            "operation_ref": operation_ref,
            "attempt_ref": "attempt_schema_" + str(number),
            "dispatch_nonce": format(number + 1, "064x"),
            **changed,
        }
        with bound.factory() as db, pytest.raises(DBAPIError) as error, db.begin():
            db.execute(insert(table).values(**candidate))
        assert error.value.orig.args[0] == expected
    reference = approval(bound)
    with bound.factory() as db, pytest.raises(DBAPIError) as error, db.begin():
        db.execute(
            update(PendingApproval)
            .where(PendingApproval.approval_ref == reference.approval_ref)
            .values(consumed_at=reference.expires_at)
        )
    assert error.value.orig.args[0] == 3819
    with mysql_engine.connect() as db:
        assert db.get_isolation_level() == "READ COMMITTED"
        assert db.execute(text("SELECT @@session.time_zone")).scalar_one() == "+00:00"
    print(
        json.dumps(
            {
                "case": "execution_schema",
                "negative_constraints": len(mutations),
                "mysql_codes": [code for _, code in mutations],
                "utc_microseconds": True,
            }
        )
    )


class HeldSyntheticExecutor(SyntheticExecutor):
    def __init__(self):
        super().__init__()
        self.entered, self.release = Event(), Event()

    def execute(self, request):
        result = super().execute(request)
        self.entered.set()
        assert self.release.wait(4), "Test executor release timed out"
        return result


@pytest.mark.parametrize("conflicting", [False, True])
def test_mysql_eight_overlapping_dispatches(
    execution_binding, mysql_engine, monkeypatch, conflicting
):
    bound = execution_binding
    executor = HeldSyntheticExecutor()
    entry, database = Barrier(8), Barrier(4)
    capacity_rejected = Event()
    rejected = []
    lock = Lock()
    seen, sessions, commits, errors = set(), set(), [], []
    original_commit = mysql_engine.dialect.do_commit

    def committed(connection):
        original_commit(connection)
        if current_thread().name.startswith("execution-compete"):
            with lock:
                commits.append(1)

    monkeypatch.setattr(mysql_engine.dialect, "do_commit", committed)

    def overlap(connection, cursor, statement, parameters, context, many):
        if current_thread().name.startswith("execution-compete") and (
            "gateway_tasks" in statement and "FOR UPDATE" in statement
        ):
            with lock:
                first = current_thread().name not in seen
                seen.add(current_thread().name)
                if first:
                    sessions.add(cursor.connection.thread_id())
            if first:
                database.wait(10)
                assert capacity_rejected.wait(5)

    def db_error(context):
        if current_thread().name.startswith("execution-compete"):
            code = getattr(context.original_exception, "args", (None,))[0]
            with lock:
                errors.append(code if isinstance(code, int) else "non_mysql")

    def call(index):
        entry.wait(10)
        request = bound.request
        if conflicting:
            request = request.model_copy(update={"request_id": "req_conflict_" + str(index)})
        try:
            result = dispatch(bound, executor=executor, request=request)
            return {"http": 200, "state": result.response.execution_status}
        except AgentIdentityError as error:
            if error.code == "CAPACITY_EXCEEDED":
                with lock:
                    rejected.append(1)
                    if len(rejected) == 4:
                        capacity_rejected.set()
            return {"http": error.status_code, "error": error.code}

    event.listen(mysql_engine, "before_cursor_execute", overlap)
    event.listen(mysql_engine, "handle_error", db_error)
    try:
        with ThreadPoolExecutor(8, thread_name_prefix="execution-compete") as pool:
            futures = [pool.submit(call, i) for i in range(8)]
            try:
                if not conflicting:
                    assert executor.entered.wait(3)
                    # Collect all seven nondispatch responses before allowing completion.
                    for _ in range(200):
                        if sum(f.done() for f in futures) >= 7:
                            break
                        Event().wait(0.01)
                    assert sum(f.done() for f in futures) == 7
                    during = snapshot(bound)
                    assert during["operation_state"] == "DISPATCHING" and during["attempts"] == 1
            finally:
                executor.release.set()
            outcomes = [f.result(10) for f in futures]
    finally:
        event.remove(mysql_engine, "before_cursor_execute", overlap)
        event.remove(mysql_engine, "handle_error", db_error)
    final = snapshot(bound)
    report = {
        "case": "eight_conflicting" if conflicting else "eight_identical",
        "requests": 8,
        "overlapping_mysql_sessions": len(sessions),
        "confirmed_commits": len(commits),
        "admitted_attempts": final["attempts"],
        "rejected_requests": sum(o["http"] != 200 for o in outcomes),
        "executor_calls": executor.calls,
        "outcomes": outcomes,
        "mysql_errors": errors,
        "isolation": "READ COMMITTED",
        **final,
    }
    print(json.dumps(report))
    assert len(sessions) >= 4 and len(seen) == 4 and not errors
    assert all(o["http"] in (200, 409, 429) for o in outcomes)
    assert sum(o.get("error") == "CAPACITY_EXCEEDED" for o in outcomes) == 4
    if conflicting:
        assert executor.calls == final["attempts"] == 0
        assert sum(o.get("error") == "IDEMPOTENCY_CONFLICT" for o in outcomes) == 4
        assert final["operation_state"] == "READY"
    else:
        assert executor.calls == final["attempts"] == 1
        assert final["operation_state"] == "SUCCEEDED"


@pytest.mark.parametrize("kind", ["consent", "approval", "task", "credential", "expiry"])
def test_mysql_revocation_commit_precedes_dispatch(
    execution_binding, mysql_engine, monkeypatch, kind
):
    import app.services.agent_identity as identity
    import app.services.approvals as approvals
    import app.services.scoped_consent as consent_service

    bound = execution_binding
    reference = approval(bound)
    executor = SyntheticExecutor()
    module = (
        consent_service
        if kind == "consent"
        else approvals
        if kind in ("approval", "expiry")
        else identity
    )
    original = module._owned_task
    locked, attempted, release = Event(), Event(), Event()

    def hold(*args, **kwargs):
        task = original(*args, **kwargs)
        locked.set()
        assert release.wait(8), "Writer lock release timed out"
        return task

    monkeypatch.setattr(module, "_owned_task", hold)

    def observe(connection, cursor, statement, parameters, context, many):
        if current_thread().name.startswith("execution-waiter") and (
            "gateway_tasks" in statement and "FOR UPDATE" in statement
        ):
            attempted.set()

    def write():
        if kind in ("approval", "expiry"):
            return decide(
                bound,
                revoke=kind == "approval",
                now=NOW + timedelta(minutes=10) if kind == "expiry" else NOW,
            )
        with bound.factory() as db:
            if kind == "consent":
                return revoke_scoped_consent(
                    db,
                    owner=bound.owner,
                    task_ref=bound.task.task_ref,
                    consent_ref=reference.consent_ref,
                    now=NOW,
                )
            if kind == "task":
                return revoke_trusted_task(
                    db, owner=bound.owner, task_ref=bound.task.task_ref, now=NOW
                )
            return revoke_agent_credential(
                db,
                owner=bound.owner,
                task_ref=bound.task.task_ref,
                credential_ref=bound.issued.credential_ref,
                now=NOW,
            )

    def read():
        try:
            dispatch(
                bound,
                executor=executor,
                now=NOW + timedelta(minutes=10) if kind == "expiry" else NOW,
            )
        except AgentIdentityError as error:
            return {"http": error.status_code, "error": error.code}
        raise AssertionError("Revoked authority dispatched")

    event.listen(mysql_engine, "before_cursor_execute", observe)
    try:
        with (
            ThreadPoolExecutor(1, thread_name_prefix="execution-writer") as writers,
            ThreadPoolExecutor(1, thread_name_prefix="execution-waiter") as readers,
        ):
            writer = writers.submit(write)
            try:
                assert locked.wait(5)
                reader = readers.submit(read)
                assert attempted.wait(5)
                with pytest.raises(TimeoutError):
                    reader.result(0.2)
            finally:
                release.set()
            writer.result(10)
            outcome = reader.result(10)
    finally:
        event.remove(mysql_engine, "before_cursor_execute", observe)
    final = snapshot(bound)
    print(
        json.dumps(
            {
                "case": "revocation_first_" + kind,
                "requests": 2,
                "overlapping_sessions": 2,
                "blocked_reader_observed": True,
                "outcome": outcome,
                "executor_calls": executor.calls,
                **final,
            }
        )
    )
    assert final["attempts"] == executor.calls == 0


@pytest.mark.parametrize(
    "stage", ["before_commit", "lost_claim_ack", "outcome_rollback", "lost_outcome_ack"]
)
def test_mysql_controlled_uncertainty(execution_binding, stage):
    bound = execution_binding
    executor = SyntheticExecutor()
    with bound.factory() as db:
        count = 0
        hook = "after_commit" if stage.startswith("lost_") else "before_commit"
        failure = 2 if stage in ("outcome_rollback", "lost_outcome_ack") else 1

        def fail(session):
            nonlocal count
            count += 1
            if count == failure:
                raise OperationalError("redacted", {}, Exception("injected failure"))

        event.listen(db, hook, fail)
        with pytest.raises(OperationError, match="GATEWAY_UNAVAILABLE") as error:
            dispatch_simulated(
                db,
                token=bound.issued.token,
                request=bound.request,
                catalog=bound.catalog,
                executor=executor,
                now=NOW,
            )
        assert error.value.execution_uncertain
        event.remove(db, hook, fail)
    final = snapshot(bound)
    expected = {
        "before_commit": "READY",
        "lost_claim_ack": "DISPATCHING",
        "outcome_rollback": "DISPATCHING",
        "lost_outcome_ack": "SUCCEEDED",
    }[stage]
    assert final["operation_state"] == expected
    calls = executor.calls
    if expected == "DISPATCHING":
        with pytest.raises(OperationError, match="OPERATION_IN_PROGRESS"):
            dispatch(bound, executor=executor)
        assert status(bound).execution_status == "UNKNOWN"
        assert executor.calls == calls
    elif expected == "SUCCEEDED":
        assert dispatch(bound, executor=executor).response.execution_status == "SUCCEEDED"
        assert executor.calls == calls
    else:
        assert calls == final["attempts"] == 0 and approval(bound).consumed_at is None
    print(
        json.dumps(
            {
                "case": "fault_" + stage,
                "executor_calls": executor.calls,
                "fault_injection_not_actual_crash": True,
                **final,
            }
        )
    )


def test_mysql_completion_races_status(execution_binding):
    bound = execution_binding
    executor = HeldSyntheticExecutor()
    with ThreadPoolExecutor(2) as pool:
        running = pool.submit(dispatch, bound, executor=executor)
        try:
            assert executor.entered.wait(3)
            before = status(bound)
            assert before.operation_state == "DISPATCHING" and before.execution_status == "UNKNOWN"
            future = pool.submit(status, bound)
        finally:
            executor.release.set()
        read = future.result(5)
        result = running.result(5)
    assert read.operation_state in ("DISPATCHING", "SUCCEEDED")
    assert result.response.execution_status == status(bound).operation_state == "SUCCEEDED"
    assert snapshot(bound)["attempts"] == executor.calls == 1
    print(
        json.dumps(
            {
                "case": "completion_vs_status",
                "requests": 2,
                "observed_states": [
                    before.operation_state,
                    read.operation_state,
                    status(bound).operation_state,
                ],
                **snapshot(bound),
            }
        )
    )


@pytest.mark.parametrize("state", ["SUCCEEDED", "FAILED", "UNKNOWN", "DISPATCHING", "ADMITTED"])
def test_mysql_execution_restart_writer(mysql_engine, state):
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(mysql_engine, autoflush=False, expire_on_commit=False)
    owner = OwnerContext(owner_id="step19_restart_" + state)
    identity = new_task(factory, owner)
    grant(factory, identity)
    request = request_for(
        identity[2],
        request_id="req_step19_restart_" + state,
        idempotency_key="key_step19_restart_" + state,
    )
    from types import SimpleNamespace

    bound = SimpleNamespace(
        factory=factory,
        owner=owner,
        catalog=identity[1],
        task=identity[2],
        issued=identity[3],
        request=request,
    )
    with factory() as db:
        admit_operation(db, token=identity[3].token, request=request, catalog=identity[1], now=NOW)
    executor = SyntheticExecutor(
        state if state in ("SUCCEEDED", "FAILED", "UNKNOWN") else "SUCCEEDED"
    )
    if state == "DISPATCHING":
        with factory() as db:

            def lost_ack(session):
                raise OperationalError("redacted", {}, Exception("lost claim acknowledgment"))

            event.listen(db, "after_commit", lost_ack)
            with pytest.raises(OperationError):
                dispatch_simulated(
                    db,
                    token=identity[3].token,
                    request=request,
                    catalog=identity[1],
                    executor=executor,
                    now=NOW,
                )
            event.remove(db, "after_commit", lost_ack)
    elif state != "ADMITTED":
        dispatch(bound, executor=executor)
    expected = snapshot(bound)
    assert expected["operation_state"] == state
    print(
        json.dumps(
            {"case": "restart_writer_" + state, "executor_calls": executor.calls, **expected}
        )
    )


@pytest.mark.parametrize("state", ["SUCCEEDED", "FAILED", "UNKNOWN", "DISPATCHING", "ADMITTED"])
def test_mysql_execution_restart_reader(mysql_engine, state):
    from types import SimpleNamespace

    from app.services.resource_catalog import CatalogResource, ResourceCatalog
    from sqlalchemy.orm import sessionmaker
    from tests.integration.test_identity_mysql import PIN

    expected = json.loads(Path(os.environ["EXECUTION_RESTART_EXPECTED"]).read_text())[state]
    factory = sessionmaker(mysql_engine, autoflush=False, expire_on_commit=False)
    owner = OwnerContext(owner_id="step19_restart_" + state)
    with factory() as db:
        task = db.get(GatewayTask, expected["task_ref"])
    with factory() as db:
        issued = issue_agent_credential(db, owner=owner, task_ref=task.task_ref, now=NOW)
    catalog = ResourceCatalog(
        resources=(CatalogResource(**PIN.model_dump(), owner_id=owner.owner_id),)
    )
    request = request_for(
        task,
        request_id="req_step19_restart_" + state,
        idempotency_key="key_step19_restart_" + state,
    )
    bound = SimpleNamespace(
        factory=factory, owner=owner, catalog=catalog, task=task, issued=issued, request=request
    )
    executor = SyntheticExecutor()
    assert snapshot(bound) == expected
    if state == "DISPATCHING":
        with pytest.raises(OperationError, match="OPERATION_IN_PROGRESS"):
            dispatch(bound, executor=executor)
        assert status(bound).execution_status == "UNKNOWN"
    elif state == "ADMITTED":
        assert status(bound).operation_state == "ADMITTED"
        # Restart/status alone never calls the dispatcher or creates an attempt.
    else:
        assert dispatch(bound, executor=executor).response.execution_status == state
    assert executor.calls == 0 and snapshot(bound) == expected
    print(json.dumps({"case": "restart_reader_" + state, "executor_calls": 0, **expected}))
