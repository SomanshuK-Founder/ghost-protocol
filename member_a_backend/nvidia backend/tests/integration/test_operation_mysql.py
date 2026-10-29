"""Opt-in ledger tests: not executed during Step 12; require separately migrated MySQL."""

import json
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Barrier, Event, current_thread

import pytest
from app.models import GatewayOperation
from app.services.agent_identity import AgentIdentityError, revoke_agent_credential
from app.services.operation_ledger import admit_operation
from app.services.scoped_consent import revoke_scoped_consent
from sqlalchemy import event, func, select
from sqlalchemy.orm import sessionmaker
from tests.integration.test_identity_mysql import NOW, grant, new_task, request_for

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session", autouse=True)
def require_disposable_runner():
    if os.getenv("MYSQL_VALIDATION_PROJECT") not in (
        "ghost-mysql-validation",
        "ghost-ledger-validation",
        "ghost-approval-validation",
        "ghost-execution-validation",
        "ghost-catalog-validation",
        "ghost-document-validation",
        "ghost-mailpit-validation",
    ):
        pytest.skip("Requires separately approved disposable MySQL and migration 0004")


@pytest.fixture
def ledger_binding(mysql_engine):
    factory = sessionmaker(mysql_engine, autoflush=False, expire_on_commit=False)
    bound = new_task(factory)
    grant(factory, bound)
    return factory, bound, request_for(bound[2])


def call(binding, request=None):
    factory, (_, catalog, _, issued), original = binding
    with factory() as db:
        return admit_operation(
            db, token=issued.token, request=request or original, catalog=catalog, now=NOW
        )


def count(binding):
    factory, (_, _, task, _), _ = binding
    with factory() as db:
        return db.scalar(
            select(func.count())
            .select_from(GatewayOperation)
            .where(GatewayOperation.task_ref == task.task_ref)
        )


def test_mysql_identical_admissions_have_one_operation(ledger_binding):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: call(ledger_binding), range(8)))
    assert len({result.audit_event_ref for result in results}) == 1
    assert count(ledger_binding) == 1


def test_mysql_conflicting_admissions_do_not_replace(ledger_binding):
    original = ledger_binding[2]
    other = original.model_copy(update={"purpose": "answer_question"})

    def submit(request):
        try:
            return call(ledger_binding, request)
        except AgentIdentityError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, [original, other]))
    assert sum(isinstance(result, str) for result in results) == 1
    assert any(
        result in ("IDEMPOTENCY_CONFLICT", "GATEWAY_UNAVAILABLE")
        for result in results
        if isinstance(result, str)
    )
    assert count(ledger_binding) == 1


def test_mysql_cross_task_request_id_uniqueness_race(ledger_binding, mysql_engine):
    factory, bound, original = ledger_binding
    other = new_task(factory, bound[0])
    grant(factory, other)
    other_binding = (factory, other, original.model_copy(update={"task_ref": other[2].task_ref}))

    def submit(binding):
        try:
            return call(binding)
        except AgentIdentityError as error:
            return error.code

    barrier, sessions, errors = Barrier(2), set(), []

    def overlap(connection, cursor, statement, parameters, context, many):
        if (
            current_thread().name.startswith("cross-task")
            and "gateway_tasks" in statement
            and "FOR UPDATE" in statement
        ):
            sessions.add(cursor.connection.thread_id())
            barrier.wait(10)

    def database_error(context):
        code = getattr(context.original_exception, "args", (None,))[0]
        errors.append(code if isinstance(code, int) else "non_mysql")

    event.listen(mysql_engine, "before_cursor_execute", overlap)
    event.listen(mysql_engine, "handle_error", database_error)
    try:
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="cross-task") as pool:
            results = list(pool.map(submit, [ledger_binding, other_binding]))
    finally:
        event.remove(mysql_engine, "before_cursor_execute", overlap)
        event.remove(mysql_engine, "handle_error", database_error)
    print(
        json.dumps(
            {
                "case": "cross_task_request_id",
                "requests": 2,
                "overlapping_sessions": len(sessions),
                "responses": sum(not isinstance(result, str) for result in results),
                "errors": [result for result in results if isinstance(result, str)],
                "mysql_errors": errors,
                "operations": count(ledger_binding) + count(other_binding),
            }
        )
    )
    assert len(sessions) == 2
    assert sum(isinstance(result, str) for result in results) == 1
    assert all(
        result in ("IDEMPOTENCY_CONFLICT", "GATEWAY_UNAVAILABLE")
        for result in results
        if isinstance(result, str)
    )
    assert count(ledger_binding) + count(other_binding) == 1


@pytest.mark.parametrize("kind", ["consent", "credential"])
def test_mysql_revocation_before_admission_denies(ledger_binding, mysql_engine, monkeypatch, kind):
    import app.services.agent_identity as identity
    import app.services.scoped_consent as policy
    from app.models import ScopedConsent

    factory, (owner, _, task, issued), _ = ledger_binding
    with factory() as db:
        consent = db.scalar(select(ScopedConsent).where(ScopedConsent.task_ref == task.task_ref))
    module = policy if kind == "consent" else identity
    original = module._owned_task
    locked, attempted, release = Event(), Event(), Event()

    def hold(*args, **kwargs):
        row = original(*args, **kwargs)
        locked.set()
        if not release.wait(8):
            raise RuntimeError("Test release timed out")
        return row

    def observe(connection, cursor, statement, parameters, context, many):
        if (
            current_thread().name.startswith("ledger-reader")
            and "gateway_tasks" in statement
            and "FOR UPDATE" in statement
        ):
            attempted.set()

    def revoke():
        with factory() as db:
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

    def read():
        try:
            return call(ledger_binding).reason_code
        except AgentIdentityError as error:
            return error.code

    monkeypatch.setattr(module, "_owned_task", hold)
    event.listen(mysql_engine, "before_cursor_execute", observe)
    try:
        with (
            ThreadPoolExecutor(max_workers=1) as writers,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="ledger-reader") as readers,
        ):
            writer = writers.submit(revoke)
            assert locked.wait(5)
            reader = readers.submit(read)
            try:
                assert attempted.wait(5)
                with pytest.raises(TimeoutError):
                    reader.result(0.2)
            finally:
                release.set()
            writer.result(5)
            outcome = reader.result(5)
            assert outcome == ("CONSENT_REVOKED" if kind == "consent" else "AUTH_INVALID")
            print(
                json.dumps(
                    {
                        "case": f"{kind}_revocation",
                        "requests": 2,
                        "blocked_reader_ms": 200,
                        "outcome": outcome,
                        "operations": count(ledger_binding),
                    }
                )
            )
    finally:
        release.set()
        event.remove(mysql_engine, "before_cursor_execute", observe)
    assert count(ledger_binding) == (1 if kind == "consent" else 0)
