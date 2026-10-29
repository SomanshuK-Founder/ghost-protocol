"""Offline synthetic email pipeline; SMTP is replaced before any I/O."""

import importlib.util
import json
import smtplib
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from email import policy
from email.parser import BytesParser
from io import StringIO
from pathlib import Path
from threading import Barrier, Event, Lock
from types import SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.agent_schemas import TaskScope
from app.gateway_contracts import EmailArguments, ToolRequest
from app.models import (
    AuditEvent,
    EmailArtifact,
    ExecutionAttempt,
    GatewayOperation,
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
from app.services.operation_ledger import OperationError, admit_operation, get_operation_status
from app.services.scoped_consent import revoke_scoped_consent
from app.services.trusted_execution import dispatch_email
from pydantic import ValidationError
from sqlalchemy import event, func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from tests.test_scoped_consent import NOW, OTHER, OWNER
from tests.test_scoped_consent import gateway as _gateway
from tests.test_scoped_consent import member_b_contract as _member_b_contract

gateway = _gateway
member_b_contract = _member_b_contract


class FakeSMTP:
    def __init__(self, state="ACCEPTED", *, block=False):
        self.state, self.calls, self.messages = state, 0, []
        self.entered, self.release, self.lock = Event(), Event(), Lock()
        if not block:
            self.release.set()

    def submit(self, recipient, message):
        with self.lock:
            self.calls += 1
            self.messages.append((recipient, message))
        self.entered.set()
        assert self.release.wait(5)
        if isinstance(self.state, Exception):
            raise self.state
        return self.state


def binding(
    gateway, action="email.send", *, enabled=True, recipient="teammate@example.test", actions=None
):
    factory = gateway[0]
    scope = TaskScope(
        purpose="prepare_email",
        allowed_actions=actions or (action,),
        recipient=recipient,
        approval_enabled=enabled,
    )
    with factory() as db:
        task = create_trusted_task(
            db, owner=OWNER, scope=scope, now=NOW, expires_at=NOW + timedelta(hours=1)
        )
    with factory() as db:
        issued = issue_agent_credential(db, owner=OWNER, task_ref=task.task_ref, now=NOW)
    request = ToolRequest(
        request_id="email_request_" + task.task_ref,
        idempotency_key="email_key",
        task_ref=task.task_ref,
        action=action,
        purpose=scope.purpose,
        arguments=arguments_for(recipient),
    )
    return SimpleNamespace(
        factory=factory,
        task=task,
        issued=issued,
        request=request,
        smtp=FakeSMTP(),
        client=gateway[3],
    )


def submit(bound, request=None):
    with bound.factory() as db:
        return admit_operation(
            db, token=bound.issued.token, request=request or bound.request, now=NOW
        )


def decide(bound, resolution="APPROVE", *, revoke=False, now=NOW, owner=OWNER):
    with bound.factory() as db:
        return owner_approval(
            db,
            owner=owner,
            approval_ref=bound.pending.approval_ref,
            resolution=None if revoke else resolution,
            revoke=revoke,
            now=now,
        )


def dispatch(bound, *, request=None, now=NOW, **kwargs):
    with bound.factory() as db:
        return dispatch_email(
            db,
            token=bound.issued.token,
            request=request or bound.request,
            transport=bound.smtp,
            now=now,
            **kwargs,
        )


@pytest.fixture
def pending(gateway):
    bound = binding(gateway)
    bound.pending = submit(bound)
    assert bound.pending.decision == "APPROVAL_REQUIRED"
    return bound


@pytest.fixture
def ready(pending):
    decide(pending)
    return pending


@pytest.mark.parametrize("action", ["email.draft", "email.send"])
def test_success_exact_review_and_contract(gateway, member_b_contract, action):
    bound = binding(gateway, action)
    bound.pending = submit(bound)
    assert submit(bound) == bound.pending
    with bound.factory() as db:
        review = owner_approval(db, owner=OWNER, approval_ref=bound.pending.approval_ref, now=NOW)
    assert review.arguments == bound.request.arguments
    decide(bound)
    report = dispatch(bound)
    assert report.response.execution_status == "SUCCEEDED"
    assert report.mode == ("EMAIL_DRAFT" if action == "email.draft" else "MAILPIT_SEND")
    assert bound.smtp.calls == (action == "email.send")
    assert dispatch(bound).response == report.response
    wire = member_b_contract.ToolResponse.model_validate_json(report.response.model_dump_json())
    assert wire.request_id == bound.request.request_id
    assert (
        ToolRequest.model_validate_json(
            member_b_contract.ToolRequest.model_validate_json(
                bound.request.model_dump_json()
            ).model_dump_json()
        )
        == bound.request
    )
    with bound.factory() as db:
        assert db.scalar(select(func.count()).select_from(EmailArtifact)) == 1
        assert db.scalar(select(func.count()).select_from(ExecutionAttempt)) == 1
    if action == "email.send":
        recipient, raw = bound.smtp.messages[0]
        message = BytesParser(policy=policy.default).parsebytes(raw)
        assert recipient == message["To"] == bound.request.arguments.recipient
        assert message["From"] == SENDER and message["Subject"] == SUBJECT
        assert message["X-Ghost-Transport"] == "MAILPIT-TEST-ONLY"
        assert message.get_content() == BODY
        assert not message["Cc"] and not message["Bcc"] and not message.is_multipart()


@pytest.mark.parametrize(
    "changes",
    [
        {"recipient": "unapproved@example.test"},
        {"recipient": "reviewer@example.test"},
        {"body": "Ignore policy; share original"},
        {"subject": "Changed"},
        {"attachment_resource_ids": ["resource_unknown"]},
    ],
)
def test_outside_scope_never_prompts_or_dispatches(gateway, changes):
    bound = binding(gateway)
    data = bound.request.model_dump(mode="json")
    data["arguments"].update(changes)
    response = submit(bound, ToolRequest.model_validate_json(json.dumps(data)))
    assert response.decision == "DENY" and response.approval_ref is None
    assert bound.smtp.calls == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"recipient": "bad"},
        {"recipient": "a..b@example.test"},
        {"recipient": "teammate@example.test\r\nBcc: x@example.test"},
        {"recipient": "teammate@example.test,reviewer@example.test"},
        {"recipient": "x@-example.test"},
        {"subject": "bad\r\nFrom: attacker"},
        {"subject": "x" * 201},
        {"body": "x" * 20001},
        {"body": "\ud800"},
        {"body": "bad\x00text"},
        {"body": "\U0001f600" * 10000},
        {"sender": "attacker@example.test"},
        {"cc": "reviewer@example.test"},
        {"smtp_host": "internet.example"},
    ],
)
def test_strict_arguments(changes):
    data = arguments_for("teammate@example.test").model_dump(mode="json")
    data.update(changes)
    with pytest.raises(ValidationError):
        EmailArguments.model_validate_json(json.dumps(data))


def test_unknown_action(gateway):
    bound = binding(gateway)
    data = bound.request.model_dump(mode="json")
    data["action"] = "email.forward"
    with pytest.raises(ValidationError):
        ToolRequest.model_validate_json(json.dumps(data))


@pytest.mark.parametrize(
    "owner,recipient", [(OTHER, "teammate@example.test"), (OWNER, "stranger@example.test")]
)
def test_owner_recipient_allowlist(gateway, owner, recipient):
    with gateway[0]() as db, pytest.raises(ValueError):
        create_trusted_task(
            db,
            owner=owner,
            scope=TaskScope(
                purpose="prepare_email",
                allowed_actions=("email.send",),
                recipient=recipient,
            ),
            expires_at=NOW + timedelta(hours=1),
            now=NOW,
        )


def test_missing_consent_and_disabled_approval(gateway):
    bound = binding(gateway, enabled=False)
    assert submit(bound).reason_code == "APPROVAL_UNAVAILABLE"
    with pytest.raises(OperationError):
        dispatch(bound)
    assert bound.smtp.calls == 0


def test_draft_does_not_grant_send(gateway):
    bound = binding(gateway, "email.draft", actions=("email.draft", "email.send"))
    bound.pending = submit(bound)
    decide(bound)
    assert dispatch(bound).response.execution_status == "SUCCEEDED"
    data = bound.request.model_dump(mode="json")
    data.update(action="email.send", request_id="send_requires_review", idempotency_key="send_key")
    send = ToolRequest.model_validate_json(json.dumps(data))
    result = submit(bound, send)
    assert result.decision == "APPROVAL_REQUIRED"
    assert result.approval_ref != bound.pending.approval_ref
    with pytest.raises(OperationError):
        dispatch(bound, request=send)
    assert bound.smtp.calls == 0


@pytest.mark.parametrize(
    "mutation",
    ["rejected", "expired", "revoked", "consent_revoked", "consent_expired", "task", "credential"],
)
def test_authority_rechecked(pending, mutation):
    bound = pending
    if mutation == "rejected":
        decide(bound, "REJECT")
    else:
        decide(bound)
        if mutation == "revoked":
            decide(bound, revoke=True)
        elif mutation == "consent_revoked":
            with bound.factory() as db:
                consent = db.scalar(
                    select(ScopedConsent).where(ScopedConsent.task_ref == bound.task.task_ref)
                )
                ref = consent.consent_ref
            with bound.factory() as db:
                revoke_scoped_consent(
                    db, owner=OWNER, task_ref=bound.task.task_ref, consent_ref=ref, now=NOW
                )
        elif mutation == "consent_expired":
            with bound.factory() as db, db.begin():
                db.execute(
                    update(ScopedConsent)
                    .where(ScopedConsent.task_ref == bound.task.task_ref)
                    .values(expires_at=NOW + timedelta(seconds=1))
                )
        elif mutation == "task":
            with bound.factory() as db:
                revoke_trusted_task(db, owner=OWNER, task_ref=bound.task.task_ref, now=NOW)
        elif mutation == "credential":
            with bound.factory() as db:
                revoke_agent_credential(
                    db,
                    owner=OWNER,
                    task_ref=bound.task.task_ref,
                    credential_ref=bound.issued.credential_ref,
                    now=NOW,
                )
    with pytest.raises(AgentIdentityError):
        dispatch(
            bound,
            now=NOW + timedelta(minutes=10)
            if mutation == "expired"
            else NOW + timedelta(seconds=2),
        )
    assert bound.smtp.calls == 0


@pytest.mark.parametrize(
    "change", ["recipient", "body", "purpose", "request_id", "idempotency_key", "task_ref"]
)
def test_approved_identity_cannot_change(ready, change):
    data = ready.request.model_dump(mode="json")
    if change in ("recipient", "body"):
        data["arguments"][change] = "reviewer@example.test" if change == "recipient" else "Changed"
    else:
        data[change] = "answer_question" if change == "purpose" else "different_identity"
    with pytest.raises(AgentIdentityError):
        dispatch(ready, request=ToolRequest.model_validate_json(json.dumps(data)))
    assert ready.smtp.calls == 0


def test_wrong_owner_and_agent_cannot_decide(pending):
    with pytest.raises(AgentIdentityError):
        decide(pending, owner=OTHER)
    response = pending.client.post(
        f"/api/control/v1/approvals/{pending.pending.approval_ref}/resolve",
        json={"resolution": "APPROVE"},
        headers={"Authorization": "Bearer " + pending.issued.token.get_secret_value()},
    )
    assert response.status_code in (401, 403) and pending.smtp.calls == 0


@pytest.mark.parametrize(
    "state,expected",
    [("REJECTED", "FAILED"), ("UNKNOWN", "UNKNOWN"), (TimeoutError("private text"), "UNKNOWN")],
)
def test_transport_failure_and_unknown_never_retry(ready, state, expected):
    ready.smtp.state = state
    result = dispatch(ready)
    assert result.response.execution_status == expected
    assert result.response.result is None and "private text" not in repr(result)
    assert dispatch(ready).response == result.response and ready.smtp.calls == 1


def test_unknown_blocks_replacement_task(ready, gateway):
    ready.smtp.state = "UNKNOWN"
    assert dispatch(ready).response.execution_status == "UNKNOWN"
    other = binding(gateway)
    assert submit(other).reason_code == "SEND_RECONCILIATION_REQUIRED"
    assert other.smtp.calls == 0


def test_task_send_slot_cannot_be_replaced(pending):
    data = pending.request.model_dump(mode="json")
    data["request_id"], data["idempotency_key"] = "another_request", "another_key"
    data["arguments"]["body"] = "Changed"
    # Out-of-profile content is denied without a second pending record.
    assert submit(pending, ToolRequest.model_validate_json(json.dumps(data))).decision == "DENY"
    with pending.factory() as db:
        slot = db.scalar(
            select(GatewayOperation).where(
                GatewayOperation.send_slot_task_ref == pending.task.task_ref
            )
        )
        assert slot is not None
    # Database also enforces the reserved slot, independently of service locks.
    with pending.factory() as db, pytest.raises(IntegrityError):
        with db.begin():
            db.execute(
                update(GatewayOperation)
                .where(GatewayOperation.request_id == "another_request")
                .values(send_slot_task_ref=pending.task.task_ref)
            )


def test_eight_concurrent_dispatches_admit_one(ready):
    ready.smtp = FakeSMTP(block=True)
    barrier = Barrier(8)

    def run():
        barrier.wait(timeout=5)
        try:
            return dispatch(ready, timeout_seconds=5).response.execution_status
        except AgentIdentityError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(run) for _ in range(8)]
        assert ready.smtp.entered.wait(5)
        with ready.factory() as db:
            assert (
                get_operation_status(
                    db, token=ready.issued.token, request_id=ready.request.request_id, now=NOW
                ).execution_status
                == "UNKNOWN"
            )
        ready.smtp.release.set()
        outcomes = [f.result(timeout=8) for f in futures]
    assert ready.smtp.calls == 1 and "SUCCEEDED" in outcomes
    with ready.factory() as db:
        assert db.scalar(select(func.count()).select_from(ExecutionAttempt)) == 1


@pytest.mark.parametrize("phase", ["before", "after"])
def test_database_failure_fails_closed(ready, phase):
    engine = ready.factory.kw["bind"]

    def fail(conn, cursor, statement, parameters, context, executemany):
        table = "execution_attempts" if phase == "before" else "email_artifacts"
        if statement.startswith("INSERT INTO " + table):
            raise OperationalError("synthetic failure", {}, Exception("private body"))

    event.listen(engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(AgentIdentityError) as error:
            dispatch(ready)
        assert error.value.status_code == 503 and "private body" not in str(error.value)
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert ready.smtp.calls == (phase == "after")
    with ready.factory() as db:
        count = db.scalar(select(func.count()).select_from(ExecutionAttempt))
        assert count == (phase == "after")
    if phase == "after":
        with pytest.raises(OperationError, match="OPERATION_IN_PROGRESS"):
            dispatch(ready)
        assert ready.smtp.calls == 1


def test_no_payload_credentials_or_addresses_in_audit_or_ledger(ready, caplog):
    result = dispatch(ready)
    with ready.factory() as db:
        rows = db.scalars(select(GatewayOperation)).all()
        serialized = json.dumps(
            [{c.name: str(getattr(row, c.name)) for c in row.__table__.columns} for row in rows]
        )
        audits = json.dumps([row.detail for row in db.scalars(select(AuditEvent))])
        attempts = json.dumps([row.result_json for row in db.scalars(select(ExecutionAttempt))])
    for value in (BODY, SUBJECT, ready.issued.token.get_secret_value()):
        assert value not in serialized + audits + attempts + caplog.text + repr(result)
    assert ready.request.arguments.recipient not in audits


def test_http_stays_non_dispatching(pending, monkeypatch):
    import app.services.agent_identity as identity
    import app.services.approvals as approvals
    import app.services.operation_ledger as ledger
    import app.services.trusted_execution as dispatcher

    for module in (identity, approvals, ledger):
        monkeypatch.setattr(module, "_utc", lambda value: NOW)

    def forbidden(*args, **kwargs):
        pytest.fail("HTTP bypassed admission")

    monkeypatch.setattr(dispatcher, "dispatch_email", forbidden)
    response = pending.client.post(
        "/api/gateway/v1/execute",
        json=pending.request.model_dump(mode="json"),
        headers={"Authorization": "Bearer " + pending.issued.token.get_secret_value()},
    )
    assert response.status_code == 200
    assert response.json()["execution_status"] == "NOT_EXECUTED"
    assert response.json()["approval_ref"] == pending.pending.approval_ref
    assert pending.smtp.calls == 0


@pytest.mark.parametrize(
    "host,port",
    [
        ("smtp.gmail.com", 1025),
        ("127.0.0.1", 1025),
        ("mailpit", 25),
        ("mailpit", 587),
        ("mailpit", True),
    ],
)
def test_smtp_destination_cannot_change(host, port):
    with pytest.raises(ValueError):
        MailpitSMTP(host=host, port=port)


@pytest.mark.parametrize(
    "addresses", [["8.8.8.8"], ["127.0.0.1"], ["169.254.1.1"], ["172.25.0.2", "172.25.0.3"]]
)
def test_public_ambiguous_and_local_destinations_rejected(monkeypatch, addresses):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 1025)) for ip in addresses],
    )
    monkeypatch.setattr(smtplib, "SMTP", lambda **kw: pytest.fail("Unsafe SMTP connection"))
    assert MailpitSMTP().submit("teammate@example.test", b"synthetic") == "REJECTED"


@pytest.mark.parametrize(
    "phase,expected",
    [
        ("connect", "REJECTED"),
        ("rcpt", "REJECTED"),
        ("data_timeout", "UNKNOWN"),
        ("negative_data", "REJECTED"),
        ("success", "ACCEPTED"),
    ],
)
def test_mailpit_protocol_acknowledgement_without_network(monkeypatch, phase, expected):
    calls = []

    class SMTPFake:
        def __init__(self, **kw):
            assert kw["local_hostname"] == "ghost-demo.example.test"

        def connect(self, host, port):
            calls.append((host, port))
            if phase == "connect":
                raise TimeoutError("not logged")
            return 220, b"synthetic"

        def ehlo(self):
            return 250, b"synthetic"

        def mail(self, sender):
            assert sender == SENDER
            return 250, b"OK"

        def rcpt(self, recipient):
            return (550 if phase == "rcpt" else 250), b"synthetic"

        def data(self, message):
            if phase == "data_timeout":
                raise TimeoutError("lost acknowledgement")
            if phase == "negative_data":
                raise smtplib.SMTPDataError(550, b"rejected")
            return 250, b"synthetic queued"

        def close(self):
            pass

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("172.25.0.2", 1025))],
    )
    monkeypatch.setattr(smtplib, "SMTP", SMTPFake)
    assert MailpitSMTP().submit("teammate@example.test", b"synthetic") == expected
    assert calls == [("172.25.0.2", 1025)]


def test_result_expiry_never_resends(ready):
    dispatch(ready)
    # Shorten the cache boundary so the task credential remains current at equality.
    with ready.factory() as db, db.begin():
        db.execute(update(ExecutionAttempt).values(result_expires_at=NOW + timedelta(seconds=1)))
    with pytest.raises(OperationError, match="RESULT_EXPIRED"):
        dispatch(ready, now=NOW + timedelta(seconds=1))
    assert ready.smtp.calls == 1


def test_executor_timeout_does_not_resend_or_overwrite_unknown(ready):
    ready.smtp = FakeSMTP(block=True)
    try:
        report = dispatch(ready, timeout_seconds=0.02)
        assert report.response.execution_status == "UNKNOWN"
        assert report.sanitized_error_code == "EXECUTOR_TIMEOUT"
    finally:
        ready.smtp.release.set()
    assert dispatch(ready).response.execution_status == "UNKNOWN"
    assert ready.smtp.calls == 1


def test_no_smtp_transport_is_fail_closed(ready):
    with ready.factory() as db:
        report = dispatch_email(db, token=ready.issued.token, request=ready.request, now=NOW)
    assert report.response.execution_status == "FAILED"
    assert ready.smtp.calls == 0


def test_only_fake_transport_used_no_files_shell_or_network(ready, monkeypatch):
    import builtins
    import os
    import subprocess

    def forbidden(*args, **kwargs):
        pytest.fail("Forbidden external side effect")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(smtplib, "SMTP", forbidden)
        patch.setattr(socket, "getaddrinfo", forbidden)
        patch.setattr(os, "system", forbidden)
        patch.setattr(subprocess, "Popen", forbidden)
        assert dispatch(ready).response.execution_status == "SUCCEEDED"
    assert ready.smtp.calls == 1


def test_pending_template_cannot_be_null(pending):
    with pending.factory() as db, pytest.raises(IntegrityError):
        with db.begin():
            db.execute(
                update(PendingApproval)
                .where(PendingApproval.approval_ref == pending.pending.approval_ref)
                .values(template_ref=None)
            )


def test_restart_connections_preserve_identity_and_receipt(ready):
    result = dispatch(ready)
    ready.factory.kw["bind"].dispose()
    replay = dispatch(ready)
    assert replay.response == result.response and ready.smtp.calls == 1


def test_recipient_case_and_exact_template_bytes(gateway):
    bound = binding(gateway)
    data = bound.request.model_dump(mode="json")
    data["arguments"]["recipient"] = "teammate@EXAMPLE.TEST"
    normalized = ToolRequest.model_validate_json(json.dumps(data))
    assert normalized == bound.request
    data["arguments"]["body"] += "\n"
    assert (
        submit(bound, ToolRequest.model_validate_json(json.dumps(data))).reason_code
        == "EMAIL_CONTENT_NOT_AUTHORIZED"
    )


def test_consent_and_approval_digest_cannot_substitute(ready):
    with ready.factory() as db, db.begin():
        db.execute(
            update(ScopedConsent)
            .where(ScopedConsent.task_ref == ready.task.task_ref)
            .values(payload_digest="a" * 64)
        )
    with pytest.raises(AgentIdentityError):
        dispatch(ready)
    assert ready.smtp.calls == 0


def test_migration_mysql_sql_only():
    path = Path(__file__).parents[1] / "migrations/versions/0009_mailpit_email.py"
    spec = importlib.util.spec_from_file_location("mailpit_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = StringIO()
    context = MigrationContext.configure(
        url="mysql+pymysql://", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        module.upgrade()
    sql = output.getvalue()
    assert "CREATE TABLE email_artifacts" in sql
    assert "uq_operation_send_slot" in sql and "ck_scoped_consent_email_scope" in sql
    assert "DATETIME(6)" in sql and module.down_revision == "0008_secure_document_reading"
