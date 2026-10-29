"""Step 36 verified disposable MySQL/Mailpit only; no production code changes."""

import asyncio
import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event, Lock, current_thread
from uuid import uuid4

import httpx
import pytest
from app.agent_schemas import TaskScope
from app.database import get_db
from app.gateway_contracts import ToolRequest
from app.main import app
from app.models import (
    AuditEvent,
    ExecutionAttempt,
    GatewayOperation,
    PendingApproval,
    ScopedConsent,
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
from app.services.controlled_execution import ControlledExecution, get_controlled_execution
from app.services.email_profile import BODY, SENDER, SUBJECT, arguments_for
from app.services.mailpit_email import MailpitSMTP
from app.services.resource_catalog import get_resource_catalog
from app.services.scoped_consent import revoke_scoped_consent
from sqlalchemy import event, inspect, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from tests.integration.test_workflow_mysql import decide, identity, new_case, pending, step

pytestmark = pytest.mark.integration
EVIDENCE = []


@pytest.fixture(scope="session", autouse=True)
def approved_target():
    assert os.environ.get("MYSQL_VALIDATION_PROJECT") == "ghost-execution-validation"
    yield
    from pathlib import Path

    Path("/tmp/step36-mysql-evidence.json").write_text(json.dumps(EVIDENCE, indent=2))


def api(path):
    assert path.startswith("/api/v1/")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://mailpit:8025" + path, timeout=3) as response:
        return json.load(response)


def captures():
    return api("/api/v1/messages")["total"]


def record(case, before, delta, **fields):
    after = captures()
    assert after == before + delta
    EVIDENCE.append(
        dict(case=case, captures_before=before, captures_after=after, delta=delta, **fields)
    )


def ready(case):
    pending(case)
    decide(case)
    payload = identity(case)
    for command in ("admit", "claim", "complete"):
        case.binding = step(case, command, payload)
    with case.factory() as db:
        case.hint = db.get(PendingApproval, case.binding.approval_ref).resume_ref
    return case


def email_case(engine):
    case = new_case(engine)
    with case.factory() as db:
        case.task = create_trusted_task(
            db,
            owner=case.owner,
            scope=TaskScope(
                purpose="prepare_email",
                allowed_actions=("email.send",),
                recipient="teammate@example.test",
                approval_enabled=True,
            ),
            now=case.now,
            expires_at=case.now + timedelta(minutes=50),
        )
    with case.factory() as db:
        case.issued = issue_agent_credential(
            db, owner=case.owner, task_ref=case.task.task_ref, now=case.now
        )
    case.request = ToolRequest(
        request_id="mail_" + uuid4().hex,
        task_ref=case.task.task_ref,
        idempotency_key="mail_key",
        action="email.send",
        purpose="prepare_email",
        arguments=arguments_for("teammate@example.test"),
    )
    return case


def http(case, *, body=None, token=None, request_id=None, service=None):
    def database():
        with case.factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_resource_catalog] = lambda: case.catalog
    app.dependency_overrides[get_controlled_execution] = lambda: (
        service or ControlledExecution(email_transport=MailpitSMTP())
    )

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://asgi.test"
        ) as client:
            result = await client.post(
                "/api/gateway/v1/operations/" + (request_id or case.request.request_id) + "/resume",
                json=body or {"resume_ref": case.hint},
                headers={
                    "Authorization": "Bearer " + (token or case.issued.token.get_secret_value())
                },
            )
            assert all(
                marker not in result.text
                for marker in (
                    "PRIVATE_DOCUMENT_MARKER",
                    "PRIVATE_ERROR_MARKER",
                    case.issued.token.get_secret_value(),
                    os.environ["API_BEARER_TOKEN"],
                    os.environ["MYSQL_PASSWORD"],
                )
            )
            return result

    return asyncio.run(request())


def test_migrated_schema_and_real_configuration(mysql_engine):
    inspector = inspect(mysql_engine)
    fields = {c["name"]: c for c in inspector.get_columns("execution_attempts")}
    assert fields["resume_hint_digest"]["type"].length == 64
    assert fields["dispatch_at"]["type"].fsp == 6
    assert any(
        f["referred_table"] == "workflow_checkpoints"
        for f in inspector.get_foreign_keys("execution_attempts")
    )
    assert any(
        tuple(u["column_names"]) == ("operation_ref",)
        for u in inspector.get_unique_constraints("execution_attempts")
    )
    assert "ck_attempt_controlled" in {
        c["name"] for c in inspector.get_check_constraints("execution_attempts")
    }
    with mysql_engine.connect() as db:
        assert (
            db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "0013_application_interfaces"
        )
        assert db.execute(text("SELECT @@transaction_isolation,@@session.time_zone")).one() == (
            "READ-COMMITTED",
            "+00:00",
        )


@pytest.mark.parametrize("email", [False, True])
def test_http_success_exact_replay_and_audit(mysql_engine, email):
    case = ready(email_case(mysql_engine) if email else new_case(mysql_engine))
    before = captures()
    first = http(case)
    assert first.status_code == 200 and first.json()["execution_status"] == "SUCCEEDED"
    second = http(case)
    assert second.status_code == 200 and second.json() == {**first.json(), "replayed": True}
    with case.factory() as db:
        attempts = list(
            db.scalars(
                select(ExecutionAttempt).where(
                    ExecutionAttempt.operation_ref == case.binding.operation_ref
                )
            )
        )
        assert len(attempts) == 1 and attempts[0].workflow_binding_ref == case.binding.binding_ref
        assert (
            attempts[0].resume_hint_digest != case.hint
            and len(attempts[0].resume_hint_digest) == 64
        )
        assert (
            db.get(AuditEvent, int(first.json()["audit_event_ref"].removeprefix("event_")))
            is not None
        )
        assert db.get(PendingApproval, case.binding.approval_ref).consumed_at is not None
    if email:
        message = api("/api/v1/message/" + api("/api/v1/messages")["messages"][0]["ID"])
        assert message["From"]["Address"] == SENDER and [x["Address"] for x in message["To"]] == [
            "teammate@example.test"
        ]
        assert message["Subject"] == SUBJECT and message["Text"] == BODY
    record(
        "http_email_success" if email else "http_simulation_success",
        before,
        int(email),
        attempts=1,
        phase="RESUMED",
        execution_status="SUCCEEDED",
    )


@pytest.mark.parametrize(
    "negative",
    [
        "missing_consent",
        "expired_consent",
        "revoked_consent",
        "missing_approval",
        "rejected_approval",
        "expired_approval",
        "revoked_approval",
        "invalid_agent",
        "wrong_task",
        "wrong_owner",
        "wrong_operation",
        "wrong_request",
        "wrong_key",
        "recipient",
        "purpose",
        "version",
        "paused",
        "resuming",
        "incomplete",
        "replay",
        "revoked_credential",
        "cancelled_task",
        "unapproved_smtp",
    ],
)
def test_denied_email_capture_counts(mysql_engine, negative):
    case = email_case(mysql_engine)
    if negative == "missing_approval":
        from app.services.operation_ledger import admit_operation

        with case.factory() as db, _transaction(db):
            task = _owned_task(db, case.owner, case.task.task_ref)
            task.authorization_scope = {**task.authorization_scope, "approval_enabled": False}
        with case.factory() as db:
            admission = admit_operation(
                db, token=case.issued.token, request=case.request, catalog=case.catalog
            )
        assert admission.decision == "DENY" and admission.approval_ref is None
        case.hint = "not_authority"
        before = captures()
        response = http(case)
        assert response.status_code == 503
        record(negative, before, 0, http_status=response.status_code, approval_record_absent=True)
        return
    pending(case)
    if negative == "rejected_approval":
        decide(case, "REJECT")
    elif negative not in ("paused", "missing_approval"):
        decide(case)
    if negative not in (
        "paused",
        "missing_approval",
        "rejected_approval",
        "resuming",
        "incomplete",
    ):
        payload = identity(case)
        for command in ("admit", "claim", "complete"):
            case.binding = step(case, command, payload)
    elif negative in ("resuming", "incomplete"):
        payload = identity(case)
        case.binding = step(case, "admit", payload)
        if negative == "resuming":
            case.binding = step(case, "claim", payload)
    with case.factory() as db:
        case.hint = db.get(PendingApproval, case.binding.approval_ref).resume_ref or "not_authority"
    before = captures()
    token = None
    body = None
    request_id = None
    if negative == "replay":
        first = http(case)
        assert first.status_code == 200
        record("replay_initial_authorized", before, 1)
        before = captures()
    elif negative == "revoked_approval":
        decide(case, revoke=True)
    elif negative == "revoked_consent":
        with case.factory() as db:
            ref = db.get(PendingApproval, case.binding.approval_ref).consent_ref
        with case.factory() as db:
            revoke_scoped_consent(
                db, owner=case.owner, task_ref=case.task.task_ref, consent_ref=ref
            )
    elif negative == "cancelled_task":
        with case.factory() as db:
            revoke_trusted_task(db, owner=case.owner, task_ref=case.task.task_ref)
    elif negative == "revoked_credential":
        with case.factory() as db:
            revoke_agent_credential(
                db,
                owner=case.owner,
                task_ref=case.task.task_ref,
                credential_ref=case.issued.credential_ref,
            )
    elif negative in (
        "missing_consent",
        "expired_consent",
        "expired_approval",
        "recipient",
        "purpose",
        "version",
    ):
        with case.factory() as db, _transaction(db):
            task = _owned_task(db, case.owner, case.task.task_ref)
            approval = db.get(PendingApproval, case.binding.approval_ref)
            if negative in ("missing_consent", "expired_consent"):
                consent = db.get(ScopedConsent, approval.consent_ref)
                if negative == "missing_consent":
                    consent.payload_digest = "0" * 64
                else:
                    consent.expires_at = datetime.now(UTC)
            elif negative == "expired_approval":
                # Invalid immutable expiry must fail history validation, not be repaired.
                approval.expires_at = datetime.now(UTC)
            elif negative == "version":
                task.authorization_version += 1
            else:
                task.authorization_scope = {
                    **task.authorization_scope,
                    "recipient" if negative == "recipient" else "purpose": "reviewer@example.test"
                    if negative == "recipient"
                    else "answer_question",
                }
    elif negative in ("wrong_task", "wrong_owner"):
        foreign = new_case(
            mysql_engine, owner_ref="foreign-owner" if negative == "wrong_owner" else "local-user"
        )
        token = foreign.issued.token.get_secret_value()
    elif negative == "invalid_agent":
        token = "not-a-credential"
    elif negative in ("wrong_operation", "wrong_request"):
        request_id = "foreign_" + uuid4().hex
    elif negative == "wrong_key":
        body = {"resume_ref": case.hint, "idempotency_key": "foreign"}
    elif negative == "unapproved_smtp":
        with pytest.raises(ValueError):
            MailpitSMTP(host="external.invalid")
        record(negative, before, 0, transport_configuration_rejected=True)
        return
    response = http(case, body=body, token=token, request_id=request_id)
    assert (
        response.status_code == 200 and response.json()["replayed"]
        if negative == "replay"
        else response.status_code in (401, 403, 404, 409, 422, 503)
    )
    record(
        negative,
        before,
        0,
        http_status=response.status_code,
        error_code=response.json().get("error_code"),
    )


def overlap(case, functions, label):
    count = len(functions)
    gate = Barrier(count)
    lock = Lock()
    arrived = Event()
    ids = set()
    active = True
    main = current_thread()

    def observe(conn, cursor, statement, parameters, context, many):
        if (
            active
            and current_thread() != main
            and "gateway_tasks" in statement
            and "FOR UPDATE" in statement
            and case.task.task_ref in str(parameters)
        ):
            with lock:
                ids.add(conn.connection.driver_connection.thread_id())
                if len(ids) >= count:
                    arrived.set()

    event.listen(case.engine, "before_cursor_execute", observe)
    anchor = case.engine.connect()
    transaction = anchor.begin()
    anchor.execute(
        text("SELECT task_ref FROM gateway_tasks WHERE task_ref=:ref FOR UPDATE"),
        {"ref": case.task.task_ref},
    )

    def call(fn):
        gate.wait(timeout=10)
        return fn()

    try:
        with ThreadPoolExecutor(max_workers=count) as pool:
            pending_calls = [pool.submit(call, fn) for fn in functions]
            assert arrived.wait(8)
            with case.engine.connect() as db:
                deadline = time.monotonic() + 6
                while True:
                    waits = db.execute(
                        text(
                            "SELECT COUNT(DISTINCT w.REQUESTING_THREAD_ID) "
                            "FROM performance_schema.data_lock_waits w "
                            "JOIN performance_schema.data_locks l "
                            "ON l.ENGINE_LOCK_ID=w.REQUESTING_ENGINE_LOCK_ID "
                            "WHERE l.OBJECT_SCHEMA=DATABASE() "
                            "AND l.OBJECT_NAME='gateway_tasks'"
                        )
                    ).scalar_one()
                    if waits >= count or time.monotonic() > deadline:
                        break
                    time.sleep(0.02)
                assert waits >= count
            active = False
            transaction.commit()
            results = [future.result(timeout=25) for future in pending_calls]
    finally:
        if transaction.is_active:
            transaction.rollback()
        anchor.close()
        event.remove(case.engine, "before_cursor_execute", observe)
    return results, dict(
        case=label, requests=count, distinct_sessions=len(ids), observed_lock_waiters=waits
    )


def test_eight_overlapping_http_send_requests(mysql_engine):
    case = ready(email_case(mysql_engine))
    before = captures()
    results, details = overlap(case, [lambda: http(case)] * 8, "eight_http_execution_requests")
    assert any(r.status_code == 200 for r in results)
    assert all(r.status_code in (200, 409, 429) for r in results)
    with case.factory() as db:
        attempts = list(
            db.scalars(
                select(ExecutionAttempt).where(
                    ExecutionAttempt.operation_ref == case.binding.operation_ref
                )
            )
        )
        assert len(attempts) == 1 and attempts[0].state == "SUCCEEDED"
    details.update(
        admitted_attempts=1,
        successful_http=sum(r.status_code == 200 for r in results),
        rejected_http=sum(r.status_code != 200 for r in results),
        final_state="SUCCEEDED",
    )
    record(details.pop("case"), before, 1, **details)


@pytest.mark.parametrize("kind", ["approval", "consent", "task"])
def test_authority_race(mysql_engine, kind):
    case = ready(email_case(mysql_engine))
    before = captures()

    def revoke():
        if kind == "approval":
            decide(case, revoke=True)
        elif kind == "task":
            with case.factory() as db:
                revoke_trusted_task(db, owner=case.owner, task_ref=case.task.task_ref)
        else:
            with case.factory() as db:
                ref = db.get(PendingApproval, case.binding.approval_ref).consent_ref
            with case.factory() as db:
                revoke_scoped_consent(
                    db, owner=case.owner, task_ref=case.task.task_ref, consent_ref=ref
                )
        return None

    results, details = overlap(case, [lambda: http(case), revoke], "execution_vs_" + kind)
    assert results[0].status_code in (200, 401, 403, 409)
    after = captures()
    assert after - before in (0, 1)
    second = http(case)
    assert second.status_code in (401, 403, 409)
    details.update(
        http_status=results[0].status_code,
        replay_http=second.status_code,
        revocation_committed=True,
    )
    record(details.pop("case"), before, after - before, **details)


def test_actual_controlled_foreign_key_and_digest_checks(mysql_engine):
    case = ready(new_case(mysql_engine))
    assert http(case).status_code == 200
    for field, value in (("workflow_binding_ref", "wf_missing"), ("resume_hint_digest", "short")):
        with case.factory() as db:
            attempt = db.scalar(
                select(ExecutionAttempt).where(
                    ExecutionAttempt.operation_ref == case.binding.operation_ref
                )
            )
            with pytest.raises((IntegrityError, OperationalError)) as error:
                setattr(attempt, field, value)
                db.flush()
            assert error.value.orig.args[0] in (1452, 3819)
            db.rollback()
    EVIDENCE.append(
        {
            "case": "mysql_fk_and_digest_constraint",
            "foreign_key_enforced": True,
            "digest_pair_check_enforced": True,
        }
    )


@pytest.mark.parametrize("change", ["request_id", "idempotency_key", "payload", "logical_identity"])
def test_admission_identity_conflicts_do_not_create_another_operation(mysql_engine, change):
    from app.services.operation_ledger import admit_operation

    case = ready(new_case(mysql_engine))
    before = captures()
    updates = (
        {change: "conflict_" + uuid4().hex}
        if change in ("request_id", "idempotency_key")
        else {"arguments": {"resource_id": "resource_foreign"}}
        if change == "payload"
        else {"request_id": "new_" + uuid4().hex, "idempotency_key": "new_key"}
    )
    with case.factory() as db:
        with pytest.raises(AgentIdentityError) as error:
            admit_operation(
                db,
                token=case.issued.token,
                request=case.request.model_copy(update=updates),
                catalog=case.catalog,
            )
    assert error.value.status_code == 409
    with case.factory() as db:
        assert (
            len(
                list(
                    db.scalars(
                        select(GatewayOperation).where(
                            GatewayOperation.task_ref == case.task.task_ref
                        )
                    )
                )
            )
            == 1
        )
    record("conflicting_" + change, before, 0, error_code=error.value.code)


def test_overlapping_credential_revocation(mysql_engine):
    case = ready(new_case(mysql_engine))
    before = captures()

    def revoke():
        with case.factory() as db:
            revoke_agent_credential(
                db,
                owner=case.owner,
                task_ref=case.task.task_ref,
                credential_ref=case.issued.credential_ref,
            )

    results, details = overlap(case, [lambda: http(case), revoke], "execution_vs_credential")
    assert results[0].status_code in (200, 401, 403, 409)
    assert http(case).status_code == 401
    record(
        details.pop("case"),
        before,
        0,
        **details,
        http_status=results[0].status_code,
        committed_revocation_blocks_replay=True,
    )
