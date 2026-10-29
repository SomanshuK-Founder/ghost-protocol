"""v1.3 actual ASGI/SQLite tests; no MySQL, reader, or SMTP runtime."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event

import pytest
from app.controlled_contracts import ControlledExecutionResult
from app.main import app
from app.models import (
    AgentCredential,
    AuditEvent,
    ExecutionAttempt,
    GatewayOperation,
    GatewayTask,
    PendingApproval,
    ScopedConsent,
    WorkflowCheckpoint,
)
from app.services.controlled_execution import ControlledExecution, get_controlled_execution
from app.services.operation_ledger import OperationError, admit_operation
from app.services.synthetic_executor import SyntheticExecutor
from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError
from tests.test_approvals import approved_task as _approved_task
from tests.test_approvals import decide, row
from tests.test_mailpit_email import binding as email_binding
from tests.test_mailpit_email import decide as email_decide
from tests.test_mailpit_email import submit as email_submit
from tests.test_scoped_consent import CATALOG, NOW, OWNER, request_for
from tests.test_scoped_consent import gateway as _gateway
from tests.test_workflow_resume import call, identity, paused

gateway = _gateway
approved_task = _approved_task


@pytest.fixture
def ready(approved_task, monkeypatch):
    monkeypatch.setattr("app.services.trusted_execution._utc", lambda now: now or NOW)
    binding = paused(approved_task)
    decide(approved_task, "APPROVE")
    payload = identity(approved_task, binding)
    for command in ("admit", "claim", "complete"):
        binding = call(approved_task, command, payload, binding)
    hint = row(approved_task).resume_ref
    executor = SyntheticExecutor()
    service = ControlledExecution(executor)
    app.dependency_overrides[get_controlled_execution] = lambda: service
    return approved_task, binding, hint, executor


def send(ready, *, body=None, token=None, request_id=None):
    bound, binding, hint, _ = ready
    return bound[3].post(
        "/api/gateway/v1/operations/" + (request_id or binding.request_id) + "/resume",
        json=body if body is not None else {"resume_ref": hint},
        headers={"Authorization": "Bearer " + (token or bound[2].token.get_secret_value())},
    )


def count(bound):
    with bound[0]() as db:
        return db.scalar(select(func.count()).select_from(ExecutionAttempt))


def test_simulated_replay_restart_audit_and_separate_consumption(ready):
    bound, binding, hint, executor = ready
    assert row(bound).consumed_at is None
    response = send(ready)
    assert response.status_code == 200
    result = ControlledExecutionResult.model_validate_json(response.content)
    assert result.execution_status == "SUCCEEDED" and not result.replayed
    assert result.effect == "SIMULATED" and result.result.text.startswith("SIMULATED")
    assert response.headers["cache-control"] == "no-store"
    assert row(bound).consumed_at == NOW and row(bound).resume_ref is None
    bound[0].kw["bind"].dispose()
    replay = send(ready).json()
    assert replay == {**result.model_dump(mode="json"), "replayed": True}
    assert count(bound) == executor.calls == 1
    with bound[0]() as db:
        attempt = db.scalar(select(ExecutionAttempt))
        assert attempt.workflow_binding_ref == binding.binding_ref
        assert len(attempt.resume_hint_digest) == 64 and hint != attempt.resume_hint_digest
        assert db.get(AuditEvent, int(result.audit_event_ref.removeprefix("event_")))
        assert db.get(WorkflowCheckpoint, binding.binding_ref).phase == "RESUMED"


@pytest.mark.parametrize("token", ["invalid", "synthetic-owner-token", "gpa_fake"])
def test_invalid_or_owner_authentication(ready, token):
    assert send(ready, token=token).status_code in (401, 403)
    assert count(ready[0]) == 0


def test_missing_credential(ready):
    bound, binding, hint, _ = ready
    assert (
        bound[3]
        .post(f"/api/gateway/v1/operations/{binding.request_id}/resume", json={"resume_ref": hint})
        .status_code
        == 401
    )
    assert count(bound) == 0


@pytest.mark.parametrize("phase", ["PREPARING", "PAUSED", "ADMITTED", "RESUMING", "DENIED"])
def test_workflow_must_be_durably_completed(ready, phase):
    bound, binding, _, executor = ready
    with bound[0].begin() as db:
        db.get(WorkflowCheckpoint, binding.binding_ref).phase = phase
    assert send(ready).status_code == 409
    assert executor.calls == count(bound) == 0


@pytest.mark.parametrize(
    "field",
    [
        "request_id",
        "idempotency_key",
        "task_ref",
        "owner_id",
        "approval_ref",
        "canonical_request_digest",
        "audit_event_id",
    ],
)
def test_workflow_binding_corruption_fails_closed(ready, field):
    bound, binding, _, executor = ready
    with bound[0].begin() as db:
        current = db.get(WorkflowCheckpoint, binding.binding_ref)
        if field == "audit_event_id":
            current.audit_event_id = db.scalar(select(AuditEvent.id).order_by(AuditEvent.id))
        elif field in ("task_ref", "owner_id", "approval_ref"):
            # FK constraints prevent substitution; missing binding also fails closed.
            db.delete(current)
        else:
            setattr(
                current,
                field,
                "b" * 64 if field == "canonical_request_digest" else "foreign_identity",
            )
    assert send(ready).status_code in (409, 503)
    assert executor.calls == count(bound) == 0


@pytest.mark.parametrize(
    "change",
    [
        "approval_revoked",
        "approval_expired",
        "consent_revoked",
        "consent_expired",
        "consent_missing",
        "task",
        "credential_revoked",
        "credential_expired",
        "version",
        "resource",
        "purpose",
    ],
)
def test_fresh_authorization(ready, change, monkeypatch):
    bound, binding, _, executor = ready
    if change == "approval_revoked":
        decide(bound, revoke=True)
    elif change == "approval_expired":
        for module in (
            "agent_identity",
            "scoped_consent",
            "operation_ledger",
            "approvals",
            "trusted_execution",
        ):
            monkeypatch.setattr(
                "app.services." + module + "._utc", lambda now: now or NOW + timedelta(minutes=11)
            )
    else:
        with bound[0].begin() as db:
            approval = db.get(PendingApproval, binding.approval_ref)
            task = db.get(GatewayTask, binding.task_ref)
            if change.startswith("consent_"):
                consent = db.get(ScopedConsent, approval.consent_ref)
                if change == "consent_revoked":
                    consent.revoked_at = NOW
                elif change == "consent_expired":
                    consent.expires_at = NOW + timedelta(microseconds=1)
                else:
                    consent.action = "tasks.list"
            elif change == "task":
                task.status = "CANCELLED"
            elif change == "version":
                task.authorization_version += 1
            elif change in ("resource", "purpose"):
                task.authorization_scope = (
                    {**task.authorization_scope, "resource_ids": []}
                    if change == "resource"
                    else {**task.authorization_scope, "purpose": "answer_question"}
                )
            else:
                credential = db.get(AgentCredential, bound[2].credential_ref)
                if change == "credential_revoked":
                    credential.revoked_at = NOW
                else:
                    credential.issued_at = NOW - timedelta(minutes=1)
                    credential.expires_at = NOW
    if change == "consent_expired":
        monkeypatch.setattr(
            "app.services.trusted_execution._utc", lambda now: NOW + timedelta(seconds=1)
        )
    assert send(ready).status_code in (401, 403, 409, 503)
    assert count(bound) == executor.calls == 0


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"resume_ref": "wrong_hint"},
        {"resume_ref": "/tmp/private"},
        {"resume_ref": "hint", "arguments": {}},
        {"resume_ref": "hint", "owner_ref": "local-user"},
        {"resume_ref": "hint", "action": "shell.exec"},
    ],
)
def test_request_shape_and_hint(ready, body):
    assert send(ready, body=body).status_code in (409, 422)
    assert count(ready[0]) == 0


def test_unknown_request_and_cross_task(ready, gateway):
    assert send(ready, request_id="unknown").status_code == 404
    assert send(ready, token=gateway[2].token.get_secret_value()).status_code == 404
    assert count(ready[0]) == 0


def test_disabled_by_default(ready):
    app.dependency_overrides.pop(get_controlled_execution)
    assert send(ready).status_code == 403
    assert count(ready[0]) == 0


@pytest.mark.parametrize("outcome", ["FAILED", "UNKNOWN"])
def test_terminal_outcomes_never_retry(ready, outcome):
    executor = SyntheticExecutor(outcome)
    service = ControlledExecution(executor)
    app.dependency_overrides[get_controlled_execution] = lambda: service
    first = send(ready)
    assert first.status_code == 200 and first.json()["execution_status"] == outcome
    assert send(ready).json()["replayed"] is True
    assert executor.calls == count(ready[0]) == 1


def test_eight_concurrent_execution_requests(ready):
    bound, binding, hint, executor = ready
    service = ControlledExecution(executor)
    barrier = Barrier(8)

    def work(_):
        barrier.wait()
        try:
            with bound[0]() as db:
                return service.resume(
                    db,
                    token=bound[2].token,
                    request_id=binding.request_id,
                    hint=hint,
                    catalog=CATALOG,
                    now=NOW,
                )
        except OperationError as error:
            assert error.code == "OPERATION_IN_PROGRESS"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(work, range(8)))
    assert any(r and r.execution_status == "SUCCEEDED" for r in results)
    assert executor.calls == count(bound) == 1


@pytest.mark.parametrize(
    "failure", ["exception", "timeout", "before_submit", "commit_after_execution"]
)
def test_failure_windows(ready, monkeypatch, failure):
    bound, _, _, _ = ready
    entered, release = Event(), Event()

    class Executor:
        calls = 0

        def execute(self, request):
            self.calls += 1
            entered.set()
            if failure == "timeout":
                release.wait(2)
                return SyntheticExecutor().execute(request)
            if failure == "exception":
                raise RuntimeError("PRIVATE_SECRET_MARKER")
            return SyntheticExecutor().execute(request)

    executor = Executor()
    service = ControlledExecution(executor, timeout_seconds=0.02 if failure == "timeout" else 1.0)
    app.dependency_overrides[get_controlled_execution] = lambda: service
    if failure == "before_submit":

        def fail(*a, **k):
            raise RuntimeError("PRIVATE_SECRET_MARKER")

        monkeypatch.setattr("app.services.trusted_execution._WORKERS.submit", fail)
    elif failure == "commit_after_execution":

        def fail_commit(connection):
            if entered.is_set():
                raise OperationalError("controlled", {}, Exception("PRIVATE_SECRET_MARKER"))

        event.listen(bound[0].kw["bind"], "commit", fail_commit)
    try:
        response = send(ready)
        assert "PRIVATE_SECRET_MARKER" not in response.text
        assert (
            response.status_code == 503
            if failure == "commit_after_execution"
            else response.json()["execution_status"] == "UNKNOWN"
        )
    finally:
        release.set()
        if failure == "commit_after_execution":
            event.remove(bound[0].kw["bind"], "commit", fail_commit)
    assert count(bound) == 1
    replay = send(ready)
    assert (
        replay.status_code == 409
        if failure == "commit_after_execution"
        else replay.json()["execution_status"] == "UNKNOWN"
    )
    assert executor.calls <= 1


def test_database_failure_before_dispatch(ready, monkeypatch):
    def fail(*a, **kw):
        raise OperationalError("private", {}, Exception("SECRET_MARKER"))

    monkeypatch.setattr("app.services.trusted_execution._execution_audit", fail)
    assert send(ready).status_code == 503
    assert count(ready[0]) == ready[3].calls == 0


def test_expired_result_no_reexecution(ready):
    assert send(ready).status_code == 200
    with ready[0][0].begin() as db:
        attempt = db.scalar(select(ExecutionAttempt))
        attempt.result_expires_at = NOW + timedelta(microseconds=1)
    # Expiry still follows completion; advance only the dispatcher's clock.
    from unittest.mock import patch

    with patch("app.services.trusted_execution._utc", lambda now: NOW + timedelta(seconds=1)):
        assert send(ready).status_code == 410
    assert ready[3].calls == 1


@pytest.mark.parametrize(
    "action,state",
    [
        ("email.draft", "ACCEPTED"),
        ("email.send", "ACCEPTED"),
        ("email.send", "REJECTED"),
        ("email.send", "UNKNOWN"),
        ("email.send", RuntimeError("PRIVATE_SMTP_MARKER")),
    ],
)
def test_fixed_email_separate_approval_fake_transport_and_privacy(
    gateway, monkeypatch, action, state
):
    monkeypatch.setattr("app.services.trusted_execution._utc", lambda now: now or NOW)
    email = email_binding(gateway, action)
    email.smtp.state = state
    email.pending = email_submit(email)
    bound = email.factory, email.task, email.issued, email.client
    from uuid import uuid4

    from app.workflow_contracts import WorkflowPause, WorkflowPrepare

    binding = call(
        bound,
        "prepare",
        WorkflowPrepare(
            task_ref=email.task.task_ref,
            approval_ref=email.pending.approval_ref,
            request_id=email.request.request_id,
            idempotency_key=email.request.idempotency_key,
        ),
    )
    binding = call(bound, "pause", WorkflowPause(checkpoint_id=str(uuid4())), binding)
    email_decide(email)
    payload = identity(bound, binding)
    for command in ("admit", "claim", "complete"):
        binding = call(bound, command, payload, binding)
    hint = row(bound).resume_ref
    service = ControlledExecution(email_transport=email.smtp)
    app.dependency_overrides[get_controlled_execution] = lambda: service
    ready = bound, binding, hint, None
    first = send(ready)
    expected = (
        "SUCCEEDED"
        if action == "email.draft" or state == "ACCEPTED"
        else "FAILED"
        if state == "REJECTED"
        else "UNKNOWN"
    )
    assert first.status_code == 200 and first.json()["execution_status"] == expected
    assert "PRIVATE_SMTP_MARKER" not in first.text
    assert send(ready).json()["replayed"]
    assert email.smtp.calls == (1 if action == "email.send" else 0)
    with email.factory() as db:
        raw = str([e.detail for e in db.scalars(select(AuditEvent))]) + str(
            [o.__dict__ for o in db.scalars(select(GatewayOperation))]
        )
    assert email.request.arguments.body not in raw
    assert email.request.arguments.body not in first.text


def test_no_approval_or_workflow_cannot_use_dispatch_bridge(gateway):
    from tests.test_scoped_consent import grant

    grant(gateway)
    with gateway[0]() as db:
        admit_operation(
            db, token=gateway[2].token, request=request_for(gateway[1]), catalog=CATALOG, now=NOW
        )
    service = ControlledExecution()
    app.dependency_overrides[get_controlled_execution] = lambda: service
    response = gateway[3].post(
        "/api/gateway/v1/operations/req_scoped/resume",
        json={"resume_ref": "not_authority"},
        headers={"Authorization": "Bearer " + gateway[2].token.get_secret_value()},
    )
    assert response.status_code != 200 and count(gateway) == 0


@pytest.mark.parametrize("decision", [None, "REJECT"])
def test_genuine_pending_or_rejected_approval_never_dispatches(
    approved_task, decision, monkeypatch
):
    monkeypatch.setattr("app.services.trusted_execution._utc", lambda now: now or NOW)
    binding = paused(approved_task)
    if decision:
        decide(approved_task, decision)
    service = ControlledExecution()
    app.dependency_overrides[get_controlled_execution] = lambda: service
    response = send((approved_task, binding, "not_a_grant", None))
    assert response.status_code == 409 and count(approved_task) == 0


def test_wrong_owner_agent_cannot_find_operation(ready):
    from app.agent_schemas import OwnerContext
    from app.services.agent_identity import create_trusted_task, issue_agent_credential
    from app.services.resource_catalog import CatalogResource, ResourceCatalog
    from tests.test_scoped_consent import PIN, SCOPE

    bound = ready[0]
    owner = OwnerContext(owner_id="other-owner")
    catalog = ResourceCatalog(
        resources=(CatalogResource(**PIN.model_dump(), owner_id=owner.owner_id),)
    )
    with bound[0]() as db:
        task = create_trusted_task(
            db,
            owner=owner,
            scope=SCOPE,
            catalog=catalog,
            now=NOW,
            expires_at=NOW + timedelta(minutes=30),
        )
    with bound[0]() as db:
        issued = issue_agent_credential(db, owner=owner, task_ref=task.task_ref, now=NOW)
    assert send(ready, token=issued.token.get_secret_value()).status_code == 404
    assert count(bound) == ready[3].calls == 0


@pytest.mark.parametrize("change", ["recipient", "purpose", "payload"])
def test_email_substitution_cannot_send(gateway, monkeypatch, change):
    monkeypatch.setattr("app.services.trusted_execution._utc", lambda now: now or NOW)
    email = email_binding(gateway)
    email.pending = email_submit(email)
    bound = email.factory, email.task, email.issued, email.client
    from uuid import uuid4

    from app.workflow_contracts import WorkflowPause, WorkflowPrepare

    binding = call(
        bound,
        "prepare",
        WorkflowPrepare(
            task_ref=email.task.task_ref,
            approval_ref=email.pending.approval_ref,
            request_id=email.request.request_id,
            idempotency_key=email.request.idempotency_key,
        ),
    )
    binding = call(bound, "pause", WorkflowPause(checkpoint_id=str(uuid4())), binding)
    email_decide(email)
    payload = identity(bound, binding)
    for command in ("admit", "claim", "complete"):
        binding = call(bound, command, payload, binding)
    hint = row(bound).resume_ref
    with email.factory.begin() as db:
        if change == "payload":
            db.get(PendingApproval, binding.approval_ref).canonical_request_digest = "a" * 64
        else:
            task = db.get(GatewayTask, binding.task_ref)
            task.authorization_scope = {
                **task.authorization_scope,
                change: "reviewer@example.test" if change == "recipient" else "answer_question",
            }
    service = ControlledExecution(email_transport=email.smtp)
    app.dependency_overrides[get_controlled_execution] = lambda: service
    assert send((bound, binding, hint, None)).status_code in (403, 409, 503)
    assert email.smtp.calls == count(bound) == 0


def test_migration_0011_compiles_additively_without_applying():
    import importlib.util
    from io import StringIO
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).resolve().parents[1] / "migrations/versions/0011_controlled_execution.py"
    spec = importlib.util.spec_from_file_location("controlled_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "0010_workflow_resume"
    out = StringIO()
    context = MigrationContext.configure(
        dialect_name="mysql", opts={"as_sql": True, "output_buffer": out}
    )
    with Operations.context(context):
        migration.upgrade()
    sql = out.getvalue()
    assert "ADD COLUMN workflow_binding_ref" in sql and "ADD COLUMN resume_hint_digest" in sql
    assert "fk_attempt_workflow" in sql and "ck_attempt_controlled" in sql
    assert "DROP" not in sql


@pytest.mark.parametrize(
    "field,value", [("resume_hint_digest", "a" * 64), ("workflow_binding_ref", "missing")]
)
def test_database_controlled_identity_constraint(ready, field, value):
    from sqlalchemy.exc import IntegrityError

    send(ready)
    with ready[0][0]() as db:
        attempt = db.scalar(select(ExecutionAttempt))
        if field == "resume_hint_digest":
            attempt.workflow_binding_ref = None
        setattr(attempt, field, value)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_lost_http_ack_never_repeats_effect(ready):
    bound, binding, hint, executor = ready
    service = ControlledExecution(executor)
    with bound[0]() as db:
        # Committed success is deliberately discarded before HTTP acknowledgment.
        service.resume(
            db,
            token=bound[2].token,
            request_id=binding.request_id,
            hint=hint,
            catalog=CATALOG,
            now=NOW,
        )
    assert send(ready).json()["replayed"]
    assert executor.calls == count(bound) == 1


@pytest.mark.parametrize("field", ["request_id", "idempotency_key", "action"])
def test_conflicting_execution_identity_is_not_mutable(ready, field):
    response = send(ready, body={"resume_ref": ready[2], field: "foreign"})
    assert response.status_code == 422
    assert ready[3].calls == count(ready[0]) == 0


@pytest.mark.parametrize("bad", ["content", "object"])
def test_executor_cannot_smuggle_protected_result(ready, bad):
    from app.gateway_contracts import DocumentFileResult
    from app.services.synthetic_executor import ExecutionOutcome

    class Executor:
        calls = 0

        def execute(self, value):
            self.calls += 1
            return (
                object()
                if bad == "object"
                else ExecutionOutcome(
                    "SUCCEEDED",
                    DocumentFileResult(
                        resource_id=value.arguments.resource_id,
                        version_ref=value.version_ref,
                        text="PRIVATE_DOCUMENT_MARKER",
                    ),
                )
            )

    executor = Executor()
    service = ControlledExecution(executor)
    app.dependency_overrides[get_controlled_execution] = lambda: service
    response = send(ready)
    assert response.status_code == 200 and response.json()["execution_status"] == "UNKNOWN"
    assert response.json()["result"] is None and "PRIVATE_DOCUMENT_MARKER" not in response.text
    with ready[0][0]() as db:
        assert all(
            "PRIVATE_DOCUMENT_MARKER" not in str(a.detail) for a in db.scalars(select(AuditEvent))
        )
        assert db.scalar(select(ExecutionAttempt)).result_json is None
    assert send(ready).json()["replayed"] and executor.calls == 1


@pytest.mark.parametrize("kind", ["approval", "consent", "task", "credential"])
def test_revocation_racing_with_controlled_admission(ready, kind):
    from app.services.agent_identity import (
        AgentIdentityError,
        revoke_agent_credential,
        revoke_trusted_task,
    )
    from app.services.scoped_consent import revoke_scoped_consent

    bound, binding, hint, executor = ready
    service = ControlledExecution(executor)
    barrier = Barrier(2)

    def execute():
        barrier.wait()
        try:
            with bound[0]() as db:
                return service.resume(
                    db,
                    token=bound[2].token,
                    request_id=binding.request_id,
                    hint=hint,
                    catalog=CATALOG,
                    now=NOW,
                )
        except AgentIdentityError:
            return None

    def revoke():
        barrier.wait()
        if kind == "approval":
            decide(bound, revoke=True)
        elif kind == "consent":
            consent_ref = row(bound).consent_ref
            with bound[0]() as db:
                revoke_scoped_consent(
                    db, owner=OWNER, task_ref=binding.task_ref, consent_ref=consent_ref, now=NOW
                )
        else:
            with bound[0]() as db:
                if kind == "task":
                    revoke_trusted_task(db, owner=OWNER, task_ref=binding.task_ref, now=NOW)
                else:
                    revoke_agent_credential(
                        db,
                        owner=OWNER,
                        task_ref=binding.task_ref,
                        credential_ref=bound[2].credential_ref,
                        now=NOW,
                    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(execute), pool.submit(revoke)]
        for future in futures:
            future.result(timeout=10)
    assert executor.calls <= 1 and count(bound) <= 1
    assert send(ready).status_code in (401, 403, 409, 503)
    assert executor.calls <= 1


def test_workflow_deadline_rechecked_after_resource_lock_wait(ready, monkeypatch):
    ticks = iter((NOW, NOW + timedelta(seconds=61)))
    monkeypatch.setattr("app.services.trusted_execution._utc", lambda now: next(ticks))
    assert send(ready).status_code == 409
    assert ready[3].calls == count(ready[0]) == 0


def test_backend_envelope_failure_is_uncertain_not_invalid_client_input(ready):
    class BrokenEnvelope:
        def resume(self, *args, **kwargs):
            ControlledExecutionResult.model_validate({"private": "PRIVATE_VALIDATION_MARKER"})

    app.dependency_overrides[get_controlled_execution] = lambda: BrokenEnvelope()
    response = send(ready)
    assert response.status_code == 503 and response.json()["execution_uncertain"] is True
    assert "PRIVATE_VALIDATION_MARKER" not in response.text
