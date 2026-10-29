"""Step 28: real Mailpit captures and overlapping disposable MySQL transactions."""

import json
import os
import smtplib
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event, Lock, current_thread
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.agent_schemas import OwnerContext, TaskScope
from app.gateway_contracts import ToolRequest
from app.models import (
    AgentCredential,
    AuditEvent,
    EmailArtifact,
    ExecutionAttempt,
    GatewayOperation,
    GatewayTask,
    PendingApproval,
    ScopedConsent,
)
from app.services.agent_identity import (
    AgentIdentityError,
    create_trusted_task,
    issue_agent_credential,
    revoke_agent_credential,
    revoke_trusted_task,
)
from app.services.approvals import owner_approval
from app.services.email_profile import BODY, SENDER, SUBJECT, arguments_for
from app.services.mailpit_email import MailpitSMTP
from app.services.operation_ledger import admit_operation
from app.services.scoped_consent import revoke_scoped_consent
from app.services.trusted_execution import dispatch_email
from pydantic import SecretStr
from sqlalchemy import delete, event, inspect, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.integration
NOW = datetime.now(UTC)
OWNER = OwnerContext(owner_id="local-user")


@pytest.fixture(scope="session", autouse=True)
def isolated_mailpit_target():
    if os.getenv("MYSQL_VALIDATION_PROJECT") != "ghost-mailpit-validation":
        pytest.skip("Requires the separately approved isolated Step 28 target")
    assert os.getenv("MYSQL_HOST") == "db" and os.getenv("MYSQL_SSL_CA")


def api(path):
    assert path.startswith("/api/v1/")
    request = urllib.request.Request("http://mailpit:8025" + path, method="GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=3) as response:
        return json.load(response)


def count():
    return api("/api/v1/messages")["total"]


def counts(case, before, expected_delta):
    deadline = time.monotonic() + 2
    after = count()
    while after != before + expected_delta and time.monotonic() < deadline:
        time.sleep(0.02)
        after = count()
    if expected_delta == 0:
        time.sleep(0.1)
        after = count()
    assert after == before + expected_delta
    print(
        json.dumps(
            {
                "case": case,
                "messages_before": before,
                "messages_after": after,
                "delta": after - before,
            }
        ),
        flush=True,
    )


def new(case, action="email.send", *, approve=True, enabled=True):
    with case.factory() as db:
        task = create_trusted_task(
            db,
            owner=OWNER,
            scope=TaskScope(
                purpose="prepare_email",
                allowed_actions=(action,),
                recipient="teammate@example.test",
                approval_enabled=enabled,
            ),
            expires_at=NOW + timedelta(hours=1),
            now=NOW,
        )
    case.tasks.append(task.task_ref)
    with case.factory() as db:
        issued = issue_agent_credential(db, owner=OWNER, task_ref=task.task_ref, now=NOW)
    request = ToolRequest(
        request_id="mail_" + uuid4().hex,
        task_ref=task.task_ref,
        idempotency_key="mail_key",
        action=action,
        purpose="prepare_email",
        arguments=arguments_for("teammate@example.test"),
    )
    bound = SimpleNamespace(factory=case.factory, task=task, issued=issued, request=request)
    with case.factory() as db:
        bound.admission = admit_operation(db, token=issued.token, request=request, now=NOW)
    if approve:
        decision(bound, "APPROVE")
    return bound


def decision(bound, resolution=None, *, revoke=False, owner=OWNER):
    with bound.factory() as db:
        return owner_approval(
            db,
            owner=owner,
            approval_ref=bound.admission.approval_ref,
            resolution=resolution,
            revoke=revoke,
            now=NOW,
        )


def dispatch(bound, *, request=None, token=None, now=NOW, transport=None, timeout_seconds=5):
    with bound.factory() as db:
        return dispatch_email(
            db,
            token=token or bound.issued.token,
            request=request or bound.request,
            transport=transport or MailpitSMTP(),
            now=now,
            timeout_seconds=timeout_seconds,
        )


def state(bound):
    with bound.factory() as db:
        operation = db.scalar(
            select(GatewayOperation).where(GatewayOperation.task_ref == bound.task.task_ref)
        )
        attempts = list(
            db.scalars(
                select(ExecutionAttempt).where(
                    ExecutionAttempt.operation_ref == operation.operation_ref
                )
            )
        )
        return operation, attempts


def privacy(factory, token=None):
    with factory() as db:
        serialized = json.dumps(
            [
                {c.name: str(getattr(row, c.name)) for c in row.__table__.columns}
                for model in (
                    GatewayOperation,
                    PendingApproval,
                    ScopedConsent,
                    ExecutionAttempt,
                    EmailArtifact,
                    AuditEvent,
                    AgentCredential,
                )
                for row in db.scalars(select(model))
            ]
        )
    assert BODY not in serialized and SUBJECT not in serialized
    if token is not None:
        assert token.get_secret_value() not in serialized


@pytest.fixture
def mail_case(mysql_engine):
    case = SimpleNamespace(
        factory=sessionmaker(mysql_engine, expire_on_commit=False, autoflush=False),
        tasks=[],
        engine=mysql_engine,
    )
    yield case
    cleanup(case)


def cleanup(case):
    # Test isolation only: remove this case's synthetic task rows after all assertions.
    # Captures and sanitized audits remain, so every next case measures actual counts.
    with case.factory() as db, db.begin():
        refs = list(
            db.scalars(
                select(GatewayOperation.operation_ref).where(
                    GatewayOperation.task_ref.in_(case.tasks)
                )
            )
        )
        db.execute(delete(EmailArtifact).where(EmailArtifact.operation_ref.in_(refs)))
        db.execute(delete(ExecutionAttempt).where(ExecutionAttempt.operation_ref.in_(refs)))
        db.execute(delete(PendingApproval).where(PendingApproval.task_ref.in_(case.tasks)))
        db.execute(delete(ScopedConsent).where(ScopedConsent.task_ref.in_(case.tasks)))
        db.execute(delete(GatewayOperation).where(GatewayOperation.operation_ref.in_(refs)))
        db.execute(delete(AgentCredential).where(AgentCredential.task_ref.in_(case.tasks)))
        db.execute(delete(GatewayTask).where(GatewayTask.task_ref.in_(case.tasks)))


def test_mysql_email_schema(mail_case):
    with mail_case.engine.connect() as connection:
        inspector = inspect(connection)
        assert "email_artifacts" in inspector.get_table_names()
        assert len(inspector.get_foreign_keys("email_artifacts")) == 2
        assert {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("email_artifacts")
        } >= {("operation_ref",), ("attempt_ref",)}
        for table in ("email_artifacts", "execution_attempts"):
            row = connection.execute(
                text(
                    "SELECT DATETIME_PRECISION FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=:table AND COLUMN_NAME=:column"
                ),
                {
                    "table": table,
                    "column": "created_at" if table == "email_artifacts" else "dispatch_at",
                },
            ).scalar_one()
            assert row == 6
        assert connection.get_isolation_level() == "READ COMMITTED"


@pytest.mark.parametrize("action", ["email.draft", "email.send"])
def test_mysql_real_mailpit_success(mail_case, action):
    before = count()
    bound = new(mail_case, action)
    with bound.factory() as db:
        review = owner_approval(db, owner=OWNER, approval_ref=bound.admission.approval_ref, now=NOW)
    assert review.arguments == bound.request.arguments and review.purpose == "prepare_email"
    first = dispatch(bound)
    assert first.response.execution_status == "SUCCEEDED"
    assert dispatch(bound).response == first.response
    counts(action, before, int(action == "email.send"))
    if action == "email.send":
        listing = api("/api/v1/messages")
        message = api("/api/v1/message/" + listing["messages"][0]["ID"])
        assert message["From"]["Address"] == SENDER
        assert [item["Address"] for item in message["To"]] == ["teammate@example.test"]
        assert message["Subject"] == SUBJECT and message["Text"] == BODY
    operation, attempts = state(bound)
    assert operation.operation_status == "SUCCEEDED" and len(attempts) == 1
    with bound.factory() as db:
        assert db.get(AuditEvent, operation.audit_event_id) is not None
        artifact = db.scalar(
            select(EmailArtifact).where(EmailArtifact.operation_ref == operation.operation_ref)
        )
        assert artifact is not None and artifact.attempt_ref == attempts[0].attempt_ref
    privacy(bound.factory, bound.issued.token)


@pytest.mark.parametrize(
    "scenario",
    [
        "missing_consent",
        "missing_approval",
        "expired_consent",
        "revoked_consent",
        "rejected_approval",
        "expired_approval",
        "revoked_approval",
        "wrong_recipient",
        "recipient_substitution",
        "purpose_substitution",
        "wrong_owner",
        "wrong_task",
        "invalid_credential",
        "idempotency_conflict",
        "invalid_resource",
        "unapproved_smtp",
        "authorization_version",
        "task_cancelled",
        "credential_revoked",
    ],
)
def test_mysql_denial_has_no_mailpit_capture(mail_case, scenario):
    before = count()
    bound = new(
        mail_case,
        approve=scenario not in ("missing_consent", "rejected_approval", "wrong_owner"),
        enabled=scenario != "missing_consent",
    )
    request, token, timestamp = bound.request, bound.issued.token, NOW
    if scenario == "wrong_owner":
        with pytest.raises(AgentIdentityError):
            decision(bound, "APPROVE", owner=OwnerContext(owner_id="other-owner"))
    elif scenario == "rejected_approval":
        decision(bound, "REJECT")
    elif scenario == "revoked_approval":
        decision(bound, revoke=True)
    elif scenario in ("expired_consent", "revoked_consent"):
        with bound.factory() as db:
            ref = db.scalar(
                select(ScopedConsent.consent_ref).where(
                    ScopedConsent.task_ref == bound.task.task_ref
                )
            )
        with bound.factory() as db:
            if scenario == "revoked_consent":
                revoke_scoped_consent(
                    db, owner=OWNER, task_ref=bound.task.task_ref, consent_ref=ref, now=NOW
                )
            else:
                with db.begin():
                    db.execute(
                        update(ScopedConsent)
                        .where(ScopedConsent.consent_ref == ref)
                        .values(expires_at=NOW + timedelta(seconds=1))
                    )
                timestamp += timedelta(seconds=2)
    elif scenario == "expired_approval":
        timestamp += timedelta(minutes=10)
    elif scenario == "missing_approval":
        with bound.factory() as db, db.begin():
            db.execute(
                delete(PendingApproval).where(
                    PendingApproval.operation_ref == state(bound)[0].operation_ref
                )
            )
    elif scenario == "authorization_version":
        with bound.factory() as db, db.begin():
            db.execute(
                update(GatewayTask)
                .where(GatewayTask.task_ref == bound.task.task_ref)
                .values(authorization_version=GatewayTask.authorization_version + 1)
            )
    elif scenario == "task_cancelled":
        with bound.factory() as db:
            revoke_trusted_task(db, owner=OWNER, task_ref=bound.task.task_ref, now=NOW)
    elif scenario == "credential_revoked":
        with bound.factory() as db:
            revoke_agent_credential(
                db,
                owner=OWNER,
                task_ref=bound.task.task_ref,
                credential_ref=bound.issued.credential_ref,
                now=NOW,
            )
    elif scenario == "invalid_credential":
        token = SecretStr("gpa_invalid")
    elif scenario == "unapproved_smtp":
        with pytest.raises(ValueError):
            MailpitSMTP(host="smtp.unapproved.example")
    else:
        data = request.model_dump(mode="json")
        if scenario in ("wrong_recipient", "recipient_substitution"):
            data["arguments"]["recipient"] = (
                "unapproved@example.test"
                if scenario == "wrong_recipient"
                else "reviewer@example.test"
            )
        elif scenario == "purpose_substitution":
            data["purpose"] = "answer_question"
        elif scenario == "wrong_task":
            data["task_ref"] = "task_other"
        elif scenario == "idempotency_conflict":
            data["request_id"] = "different_request"
        elif scenario == "invalid_resource":
            data["arguments"]["attachment_resource_ids"] = ["resource_unknown"]
        request = ToolRequest.model_validate_json(json.dumps(data))
    if scenario != "unapproved_smtp":
        with pytest.raises(AgentIdentityError):
            dispatch(bound, request=request, token=token, now=timestamp)
    counts(scenario, before, 0)
    assert not state(bound)[1]


def test_mysql_eight_overlapping_sends(mail_case):
    bound = new(mail_case)
    before = count()
    start, sql = Barrier(8), Barrier(4)
    entered, release = Event(), Event()
    seen, ids, mutex = set(), set(), Lock()

    class HeldSMTP:
        def submit(self, recipient, message):
            entered.set()
            assert release.wait(5)
            return MailpitSMTP().submit(recipient, message)

    def overlap(conn, cursor, statement, parameters, context, executemany):
        name = current_thread().name
        if (
            name.startswith("mail-eight")
            and "FROM gateway_tasks" in statement
            and "FOR UPDATE" in statement
        ):
            with mutex:
                first = name not in seen
                seen.add(name)
                if first:
                    ids.add(conn.connection.driver_connection.thread_id())
            if first:
                sql.wait(timeout=5)

    def send():
        start.wait(timeout=5)
        try:
            return dispatch(bound, transport=HeldSMTP()).response.execution_status
        except AgentIdentityError as exc:
            return exc.code

    event.listen(mail_case.engine, "before_cursor_execute", overlap)
    try:
        with ThreadPoolExecutor(max_workers=8, thread_name_prefix="mail-eight") as pool:
            futures = [pool.submit(send) for _ in range(8)]
            assert entered.wait(5)
            done, _ = wait(futures, timeout=0.3)
            assert len(done) == 7
            release.set()
            results = [future.result(timeout=6) for future in futures]
    finally:
        release.set()
        event.remove(mail_case.engine, "before_cursor_execute", overlap)
    operation, attempts = state(bound)
    assert len(ids) == 4 and len(attempts) == 1 and results.count("SUCCEEDED") == 1
    assert operation.operation_status == "SUCCEEDED"
    counts("eight_overlapping_sends", before, 1)
    print(
        json.dumps(
            {
                "case": "eight_sessions",
                "competing_requests": 8,
                "mysql_sessions": sorted(ids),
                "admitted_attempts": len(attempts),
                "results": results,
                "deadlocks": 0,
                "lock_timeouts": 0,
                "final_state": operation.operation_status,
            }
        )
    )


@pytest.mark.parametrize("kind", ["consent", "approval", "task", "credential"])
def test_mysql_committed_revocation_prevents_send(mail_case, kind):
    bound = new(mail_case)
    before = count()
    held, release, reader_sql = Event(), Event(), Event()
    sessions, mutex = set(), Lock()

    def before_commit(conn):
        if current_thread().name.startswith("mail-writer"):
            with mutex:
                sessions.add(conn.connection.driver_connection.thread_id())
            held.set()
            assert release.wait(5)

    def reader_query(conn, cursor, statement, parameters, context, executemany):
        if (
            current_thread().name.startswith("mail-reader")
            and "FROM gateway_tasks" in statement
            and "FOR UPDATE" in statement
        ):
            with mutex:
                sessions.add(conn.connection.driver_connection.thread_id())
            reader_sql.set()

    def revoke():
        if kind == "approval":
            return decision(bound, revoke=True)
        with bound.factory() as db:
            if kind == "task":
                return revoke_trusted_task(db, owner=OWNER, task_ref=bound.task.task_ref, now=NOW)
            if kind == "credential":
                return revoke_agent_credential(
                    db,
                    owner=OWNER,
                    task_ref=bound.task.task_ref,
                    credential_ref=bound.issued.credential_ref,
                    now=NOW,
                )
            ref = db.scalar(
                select(ScopedConsent.consent_ref).where(
                    ScopedConsent.task_ref == bound.task.task_ref
                )
            )
            db.rollback()
            return revoke_scoped_consent(
                db, owner=OWNER, task_ref=bound.task.task_ref, consent_ref=ref, now=NOW
            )

    event.listen(mail_case.engine, "commit", before_commit)
    event.listen(mail_case.engine, "before_cursor_execute", reader_query)
    try:
        with (
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="mail-writer") as writers,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="mail-reader") as readers,
        ):
            writer = writers.submit(revoke)
            assert held.wait(5)
            reader = readers.submit(dispatch, bound)
            assert reader_sql.wait(5)
            done, _ = wait((reader,), timeout=0.2)
            assert not done
            release.set()
            writer.result(timeout=6)
            with pytest.raises(AgentIdentityError) as error:
                reader.result(timeout=6)
    finally:
        release.set()
        event.remove(mail_case.engine, "commit", before_commit)
        event.remove(mail_case.engine, "before_cursor_execute", reader_query)
    counts("committed_" + kind + "_revocation", before, 0)
    operation, attempts = state(bound)
    assert not attempts and len(sessions) == 2
    with bound.factory() as db:
        approval = db.scalar(
            select(PendingApproval).where(PendingApproval.task_ref == bound.task.task_ref)
        )
        consent = db.scalar(
            select(ScopedConsent).where(ScopedConsent.task_ref == bound.task.task_ref)
        )
        assert approval.status == "REVOKED" and consent.revoked_at is not None
    print(
        json.dumps(
            {
                "case": "revocation_transactions_" + kind,
                "competing_requests": 2,
                "mysql_sessions": sorted(sessions),
                "committed_authority_writes": 1,
                "rejected_dispatches": 1,
                "dispatch_error": error.value.code,
                "admitted_attempts": 0,
                "final_operation": operation.operation_status,
                "final_approval": "REVOKED",
                "final_consent": "REVOKED",
                "reader_blocked_seconds": 0.2,
            }
        )
    )


@pytest.mark.parametrize("field", ["request_id", "body"])
def test_mysql_concurrent_conflicting_identity(mail_case, field):
    bound = new(mail_case)
    data = bound.request.model_dump(mode="json")
    if field == "request_id":
        data[field] = "conflicting_request"
    else:
        data["arguments"][field] = "different synthetic payload"
    conflict = ToolRequest.model_validate_json(json.dumps(data))
    barrier, before = Barrier(2), count()
    sql, ids, seen, mutex = Barrier(2), set(), set(), Lock()

    def overlap(conn, cursor, statement, parameters, context, executemany):
        name = current_thread().name
        if (
            name.startswith("mail-conflict")
            and "FROM gateway_tasks" in statement
            and "FOR UPDATE" in statement
        ):
            with mutex:
                first = name not in seen
                seen.add(name)
                if first:
                    ids.add(conn.connection.driver_connection.thread_id())
            if first:
                sql.wait(timeout=5)

    def run(request):
        barrier.wait(timeout=5)
        try:
            return dispatch(bound, request=request).response.execution_status
        except AgentIdentityError as exc:
            return exc.code

    event.listen(mail_case.engine, "before_cursor_execute", overlap)
    try:
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="mail-conflict") as pool:
            results = list(pool.map(run, (bound.request, conflict)))
    finally:
        event.remove(mail_case.engine, "before_cursor_execute", overlap)
    assert sorted(results) == ["IDEMPOTENCY_CONFLICT", "SUCCEEDED"]
    assert len(state(bound)[1]) == 1 and len(ids) == 2
    counts("concurrent_conflict_" + field, before, 1)
    print(
        json.dumps(
            {
                "case": "conflict_transactions_" + field,
                "competing_requests": 2,
                "mysql_sessions": sorted(ids),
                "admitted_attempts": 1,
                "idempotency_conflicts": 1,
                "final_state": "SUCCEEDED",
            }
        )
    )


@pytest.mark.parametrize("phase", ["before", "after"])
def test_mysql_database_failure_around_submission(mail_case, phase):
    bound, before = new(mail_case), count()

    def failure(conn, cursor, statement, parameters, context, executemany):
        table = "execution_attempts" if phase == "before" else "email_artifacts"
        if statement.startswith("INSERT INTO " + table):
            raise OperationalError("synthetic fault", {}, RuntimeError("not logged"))

    event.listen(mail_case.engine, "before_cursor_execute", failure)
    try:
        with pytest.raises(AgentIdentityError) as error:
            dispatch(bound)
        assert error.value.status_code == 503
    finally:
        event.remove(mail_case.engine, "before_cursor_execute", failure)
    counts("database_failure_" + phase, before, int(phase == "after"))
    assert len(state(bound)[1]) == int(phase == "after")
    if phase == "after":
        assert state(bound)[0].operation_status == "DISPATCHING"
        with pytest.raises(AgentIdentityError):
            dispatch(bound)
        counts("database_failure_after_replay", before, 1)


@pytest.mark.parametrize("fault", ["connection", "data_timeout", "accepted_lost_ack"])
def test_mysql_smtp_faults_and_unknown_replay(mail_case, monkeypatch, fault):
    bound, before = new(mail_case), count()
    original = smtplib.SMTP.data
    calls = []

    def broken_connect(*args, **kwargs):
        raise ConnectionRefusedError("synthetic connection fault")

    def broken_data(client, message):
        calls.append(1)
        if fault == "accepted_lost_ack":
            assert original(client, message)[0] == 250
        raise TimeoutError("synthetic lost acknowledgement")

    with monkeypatch.context() as patches:
        if fault == "connection":
            patches.setattr(smtplib.SMTP, "connect", broken_connect)
        else:
            patches.setattr(smtplib.SMTP, "data", broken_data)
        response = dispatch(bound).response
    expected = "FAILED" if fault == "connection" else "UNKNOWN"
    assert response.execution_status == expected
    counts(fault, before, int(fault == "accepted_lost_ack"))
    assert dispatch(bound).response == response
    counts(fault + "_replay", before, int(fault == "accepted_lost_ack"))
    assert len(state(bound)[1]) == 1
    if expected == "UNKNOWN":
        replacement = new(mail_case, approve=False)
        assert replacement.admission.reason_code == "SEND_RECONCILIATION_REQUIRED"
        counts(fault + "_replacement_task", before, int(fault == "accepted_lost_ack"))
    privacy(bound.factory, bound.issued.token)


def test_mysql_email_constraints_reject_broad_grants(mail_case):
    bound = new(mail_case)
    with bound.factory() as db, pytest.raises((IntegrityError, OperationalError)) as error:
        with db.begin():
            db.execute(
                update(ScopedConsent)
                .where(ScopedConsent.task_ref == bound.task.task_ref)
                .values(recipient=None)
            )
    assert error.value.orig.args[0] == 3819
    with bound.factory() as db, pytest.raises((IntegrityError, OperationalError)) as error:
        with db.begin():
            db.execute(
                update(PendingApproval)
                .where(PendingApproval.task_ref == bound.task.task_ref)
                .values(template_ref=None)
            )
    assert error.value.orig.args[0] == 3819
    assert not state(bound)[1]


def test_mysql_mail_restart_writer(mysql_engine):
    case = SimpleNamespace(
        factory=sessionmaker(mysql_engine, expire_on_commit=False, autoflush=False), tasks=[]
    )
    before, snapshots = count(), []

    class LostAck:
        def submit(self, recipient, message):
            assert MailpitSMTP().submit(recipient, message) == "ACCEPTED"
            return "UNKNOWN"

    for action, uncertain in [("email.draft", False), ("email.send", False), ("email.send", True)]:
        bound = new(case, action)
        report = dispatch(bound, transport=LostAck() if uncertain else None)
        operation, attempts = state(bound)
        snapshots.append(
            {
                "task_ref": bound.task.task_ref,
                "request_id": bound.request.request_id,
                "key": bound.request.idempotency_key,
                "action": action,
                "operation_ref": operation.operation_ref,
                "attempt_ref": attempts[0].attempt_ref,
                "state": operation.operation_status,
                "audit_ref": operation.audit_event_ref,
                "approval_ref": bound.admission.approval_ref,
                "created_at": operation.created_at.isoformat(),
                "result": report.response.result.model_dump(mode="json")
                if report.response.result
                else None,
            }
        )
    counts("restart_writer", before, 2)
    record = {"mail_restart_expected": snapshots, "message_count": count()}
    print(json.dumps(record), flush=True)
    privacy(case.factory)


def test_mysql_mail_restart_reader(mysql_engine):
    record = json.loads(Path(os.environ["MAIL_RESTART_EXPECTED"]).read_text())
    factory = sessionmaker(mysql_engine, expire_on_commit=False, autoflush=False)
    before = count()
    assert before == record["message_count"]
    for expected in record["mail_restart_expected"]:
        with factory() as db:
            issued = issue_agent_credential(db, owner=OWNER, task_ref=expected["task_ref"], now=NOW)
        request = ToolRequest(
            request_id=expected["request_id"],
            task_ref=expected["task_ref"],
            idempotency_key=expected["key"],
            action=expected["action"],
            purpose="prepare_email",
            arguments=arguments_for("teammate@example.test"),
        )
        bound = SimpleNamespace(
            factory=factory,
            task=SimpleNamespace(task_ref=expected["task_ref"]),
            issued=issued,
            request=request,
        )
        operation, attempts = state(bound)
        assert (
            operation.operation_ref == expected["operation_ref"]
            and operation.operation_status == expected["state"]
        )
        assert (
            attempts[0].attempt_ref == expected["attempt_ref"]
            and operation.audit_event_ref == expected["audit_ref"]
        )
        assert operation.created_at.isoformat() == expected["created_at"]
        with factory() as db:
            assert db.get(PendingApproval, expected["approval_ref"]) is not None
        replay = dispatch(bound).response
        assert replay.execution_status == expected["state"]
        assert (replay.result.model_dump(mode="json") if replay.result else None) == expected[
            "result"
        ]
    counts("restart_reader_no_resend", before, 0)
    privacy(factory)
    cleanup(
        SimpleNamespace(
            factory=factory, tasks=[item["task_ref"] for item in record["mail_restart_expected"]]
        )
    )
