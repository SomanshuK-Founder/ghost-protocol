"""Offline synthetic dispatch ordering; SQLite does not prove MySQL locking safety."""

import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from pathlib import Path
from threading import Event

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.agent_schemas import OwnerContext
from app.gateway_contracts import ToolRequest, ToolResponse
from app.models import AuditEvent, ExecutionAttempt, GatewayOperation, GatewayTask
from app.services.agent_identity import (
    AgentIdentityError,
    revoke_agent_credential,
    revoke_trusted_task,
)
from app.services.operation_ledger import (
    OperationError,
    admit_operation,
    get_operation_status,
    validate_transition,
)
from app.services.scoped_consent import revoke_scoped_consent
from app.services.synthetic_executor import SyntheticExecutor, SyntheticOutcome
from app.services.trusted_execution import dispatch_simulated
from pydantic import SecretStr
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from tests.test_approvals import approved_task as _approved_task
from tests.test_approvals import decide, row, submit
from tests.test_operation_ledger import new_binding
from tests.test_scoped_consent import CATALOG, NOW, OWNER, grant, request_for
from tests.test_scoped_consent import gateway as _gateway
from tests.test_scoped_consent import member_b_contract as _member_b_contract

gateway = _gateway
approved_task = _approved_task
member_b_contract = _member_b_contract


def admit(bound, **changes):
    with bound[0]() as db:
        return admit_operation(
            db,
            token=bound[2].token,
            request=request_for(bound[1], **changes),
            catalog=CATALOG,
            now=NOW,
        )


def dispatch(bound, *, executor=None, now=NOW, **changes):
    with bound[0]() as db:
        return dispatch_simulated(
            db,
            token=bound[2].token,
            request=request_for(bound[1], **changes),
            catalog=CATALOG,
            executor=executor,
            now=now,
        )


def snapshot(bound):
    with bound[0]() as db:
        return db.scalar(select(GatewayOperation)), db.scalar(select(ExecutionAttempt))


@pytest.mark.parametrize("outcome", ["SUCCEEDED", "FAILED", "UNKNOWN"])
def test_simulated_outcomes_exact_replay_restart_and_member_b(gateway, member_b_contract, outcome):
    grant(gateway)
    admit(gateway)
    executor = SyntheticExecutor(outcome)
    first = dispatch(gateway, executor=executor)
    assert first.mode == "SIMULATED" and first.response.execution_status == outcome
    assert first.response.decision == "ALLOW"
    assert executor.calls == 1
    gateway[0].kw["bind"].dispose()  # New physical connections retain durable state.
    assert dispatch(gateway, executor=executor) == first
    assert admit(gateway) == first.response
    assert executor.calls == 1
    parsed = member_b_contract.ToolResponse.model_validate_json(first.response.model_dump_json())
    assert parsed.request_id == "req_scoped"
    if outcome == "SUCCEEDED":
        assert first.response.result.text.startswith("SIMULATED")
    else:
        assert first.response.result is None
    operation, attempt = snapshot(gateway)
    assert operation.operation_status == attempt.state == outcome
    assert attempt.audit_event_id == operation.audit_event_id
    with gateway[0]() as db:
        status = get_operation_status(
            db, token=gateway[2].token, request_id="req_scoped", catalog=CATALOG, now=NOW
        )
        assert status.operation_state == outcome
        assert db.scalar(select(func.count()).select_from(ExecutionAttempt)) == 1


def test_missing_consent_and_non_admitted_request_fail_closed(gateway):
    executor = SyntheticExecutor()
    with pytest.raises(OperationError, match="NOT_FOUND"):
        dispatch(gateway, executor=executor)
    assert admit(gateway).reason_code == "APPROVAL_UNAVAILABLE"
    with pytest.raises((OperationError, AgentIdentityError)):
        dispatch(gateway, executor=executor)
    assert executor.calls == 0 and snapshot(gateway)[1] is None


@pytest.mark.parametrize(
    "change",
    [
        {"action": "tasks.list", "arguments": {}},
        {"arguments": {"resource_id": "unapproved_resource"}},
        {"purpose": "answer_question"},
    ],
)
def test_unapproved_request_cannot_dispatch(gateway, change):
    grant(gateway)
    admit(gateway, **change)
    executor = SyntheticExecutor()
    with pytest.raises(AgentIdentityError):
        dispatch(gateway, executor=executor, **change)
    assert executor.calls == 0 and snapshot(gateway)[1] is None


@pytest.mark.parametrize("mutation", ["expired", "revoked", "task", "credential", "version"])
def test_authority_rechecked_before_dispatch(gateway, mutation):
    consent = grant(gateway)
    admit(gateway)
    now = NOW
    with gateway[0]() as db:
        if mutation == "expired":
            now += timedelta(minutes=10)
        elif mutation == "revoked":
            revoke_scoped_consent(
                db,
                owner=OWNER,
                task_ref=gateway[1].task_ref,
                consent_ref=consent.consent_ref,
                now=NOW,
            )
        elif mutation == "task":
            revoke_trusted_task(db, owner=OWNER, task_ref=gateway[1].task_ref, now=NOW)
        elif mutation == "credential":
            revoke_agent_credential(
                db,
                owner=OWNER,
                task_ref=gateway[1].task_ref,
                credential_ref=gateway[2].credential_ref,
                now=NOW,
            )
        else:
            with db.begin():
                db.get(GatewayTask, gateway[1].task_ref).authorization_version += 1
    executor = SyntheticExecutor()
    with pytest.raises(AgentIdentityError):
        dispatch(gateway, executor=executor, now=now)
    assert executor.calls == 0 and snapshot(gateway)[1] is None


@pytest.mark.parametrize("mutation", ["expired", "revoked", "consent", "task", "credential"])
def test_approval_rechecked_and_consumed_once(approved_task, mutation):
    submit(approved_task)
    decide(approved_task, "APPROVE")
    approval = row(approved_task)
    now = NOW
    if mutation == "expired":
        now += timedelta(minutes=10)
    elif mutation == "revoked":
        decide(approved_task, revoke=True)
    else:
        with approved_task[0]() as db:
            if mutation == "consent":
                revoke_scoped_consent(
                    db,
                    owner=OWNER,
                    task_ref=approval.task_ref,
                    consent_ref=approval.consent_ref,
                    now=NOW,
                )
            elif mutation == "task":
                revoke_trusted_task(db, owner=OWNER, task_ref=approval.task_ref, now=NOW)
            else:
                revoke_agent_credential(
                    db,
                    owner=OWNER,
                    task_ref=approval.task_ref,
                    credential_ref=approved_task[2].credential_ref,
                    now=NOW,
                )
    executor = SyntheticExecutor()
    with pytest.raises(AgentIdentityError):
        dispatch(approved_task, executor=executor, now=now)
    assert executor.calls == 0 and snapshot(approved_task)[1] is None


@pytest.mark.parametrize("after", ["revoke", "expire"])
def test_consumed_approval_preserves_historical_execution(approved_task, after):
    submit(approved_task)
    decide(approved_task, "APPROVE")
    executor = SyntheticExecutor()
    result = dispatch(approved_task, executor=executor)
    assert row(approved_task).consumed_at == NOW
    assert row(approved_task).resume_ref is None
    if after == "revoke":
        decide(approved_task, revoke=True)
        now = NOW
    else:
        now = NOW + timedelta(minutes=10)
        with approved_task[0]() as db:
            from app.services.approvals import owner_approval

            owner_approval(
                db,
                owner=OWNER,
                approval_ref=row(approved_task).approval_ref,
                catalog=CATALOG,
                now=now,
            )
    with pytest.raises(OperationError, match="RESULT_ACCESS_DENIED"):
        dispatch(approved_task, executor=executor, now=now)
    operation, attempt = snapshot(approved_task)
    assert operation.operation_status == attempt.state == "SUCCEEDED"
    assert operation.audit_event_ref == result.response.audit_event_ref
    assert executor.calls == 1


def test_approved_dispatch_and_exact_retry(approved_task):
    submit(approved_task)
    decide(approved_task, "APPROVE")
    first = dispatch(approved_task)
    assert dispatch(approved_task) == first
    assert row(approved_task).status == "APPROVED"
    assert row(approved_task).resume_ref is None


@pytest.mark.parametrize(
    "changes",
    [
        {"request_id": "req_changed"},
        {"idempotency_key": "key_changed"},
        {"arguments": {"resource_id": "other_resource"}},
        {"purpose": "answer_question"},
    ],
)
def test_dispatch_strict_replay_identity(gateway, changes):
    grant(gateway)
    admit(gateway)
    executor = SyntheticExecutor()
    dispatch(gateway, executor=executor)
    with pytest.raises(OperationError, match="IDEMPOTENCY_CONFLICT"):
        dispatch(gateway, executor=executor, **changes)
    assert executor.calls == 1


@pytest.mark.parametrize("owner", [OWNER, OwnerContext(owner_id="synthetic-other-owner")])
def test_wrong_authenticated_task_or_owner_cannot_dispatch(gateway, owner):
    grant(gateway)
    admit(gateway)
    _, issued, _ = new_binding(gateway, owner=owner)
    executor = SyntheticExecutor()
    with gateway[0]() as db, pytest.raises(AgentIdentityError):
        dispatch_simulated(
            db,
            token=issued.token,
            request=request_for(gateway[1]),
            catalog=CATALOG,
            executor=executor,
            now=NOW,
        )
    assert executor.calls == 0 and snapshot(gateway)[1] is None


class BlockingExecutor(SyntheticExecutor):
    def __init__(self):
        super().__init__()
        self.entered, self.release = Event(), Event()

    def execute(self, request):
        self.entered.set()
        assert self.release.wait(3), "Test executor was not released"
        return super().execute(request)


def test_concurrent_dispatch_and_no_locks_held_during_executor(gateway):
    consent = grant(gateway)
    admit(gateway)
    executor = BlockingExecutor()
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(dispatch, gateway, executor=executor)
        try:
            assert executor.entered.wait(2)
            # A second DB transaction completes while the executor is blocked.
            with pytest.raises(OperationError, match="OPERATION_IN_PROGRESS"):
                pool.submit(dispatch, gateway, executor=executor).result(2)
            with gateway[0]() as db:
                assert (
                    revoke_scoped_consent(
                        db,
                        owner=OWNER,
                        task_ref=gateway[1].task_ref,
                        consent_ref=consent.consent_ref,
                        now=NOW,
                    )
                    is True
                )
        finally:
            executor.release.set()
        assert first.result(2).response.execution_status == "SUCCEEDED"
    assert executor.calls == 1
    assert snapshot(gateway)[0].operation_status == "SUCCEEDED"
    with gateway[0]() as db:
        assert db.scalar(select(func.count()).select_from(ExecutionAttempt)) == 1


@pytest.mark.parametrize("stage", ["before", "after"])
def test_database_failure_never_causes_retry(gateway, stage):
    grant(gateway)
    admit(gateway)
    executor = SyntheticExecutor()
    with gateway[0]() as db:
        commits = 0

        def fail(session):
            nonlocal commits
            commits += 1
            if commits == (1 if stage == "before" else 2):
                raise OperationalError("redacted", {}, Exception("private exception text"))

        event.listen(db, "before_commit", fail)
        with pytest.raises(OperationError, match="GATEWAY_UNAVAILABLE") as error:
            dispatch_simulated(
                db,
                token=gateway[2].token,
                request=request_for(gateway[1]),
                catalog=CATALOG,
                executor=executor,
                now=NOW,
            )
        assert error.value.execution_uncertain
        event.remove(db, "before_commit", fail)
    assert executor.calls == (0 if stage == "before" else 1)
    operation, attempt = snapshot(gateway)
    assert operation.operation_status == ("ADMITTED" if stage == "before" else "DISPATCHING")
    assert (attempt is None) == (stage == "before")
    if stage == "after":
        with pytest.raises(OperationError, match="OPERATION_IN_PROGRESS"):
            dispatch(gateway, executor=executor)
        assert executor.calls == 1


@pytest.mark.parametrize("kind", ["exception", "timeout", "invalid_result"])
def test_executor_errors_sanitized_and_never_retried(gateway, kind):
    grant(gateway)
    admit(gateway)

    class BrokenExecutor(SyntheticExecutor):
        def execute(self, request):
            super().execute(request)
            if kind == "timeout":
                raise TimeoutError("private timeout")
            if kind == "exception":
                raise RuntimeError("private credential and document text")
            return SyntheticOutcome("SUCCEEDED", None)

    executor = BrokenExecutor()
    result = dispatch(gateway, executor=executor)
    assert result.response.execution_status == "UNKNOWN"
    assert dispatch(gateway, executor=executor) == result and executor.calls == 1
    operation, attempt = snapshot(gateway)
    assert operation.sanitized_error_code in ("EXECUTOR_TIMEOUT", "EXECUTOR_UNCONFIRMED")
    assert result.sanitized_error_code == operation.sanitized_error_code
    assert attempt.result_json is None
    with gateway[0]() as db:
        serialized = json.dumps([e.detail for e in db.scalars(select(AuditEvent))])
        assert "private" not in serialized and "credential" not in serialized


def test_real_wait_timeout_does_not_release_task_for_retry(gateway):
    grant(gateway)
    admit(gateway)
    executor = BlockingExecutor()
    try:
        with gateway[0]() as db:
            result = dispatch_simulated(
                db,
                token=gateway[2].token,
                request=request_for(gateway[1]),
                catalog=CATALOG,
                executor=executor,
                now=NOW,
                timeout_seconds=0.01,
            )
        assert result.response.execution_status == "UNKNOWN"
        assert dispatch(gateway, executor=executor) == result
    finally:
        executor.release.set()
    assert executor.entered.is_set()


@pytest.mark.parametrize("state", ["SUCCEEDED", "FAILED", "UNKNOWN", "DENIED", "DISPATCHING"])
def test_terminal_states_cannot_dispatch(state):
    with pytest.raises(OperationError):
        validate_transition(state, "DISPATCHING")


def test_authorization_http_stays_non_dispatching(gateway):
    grant(gateway)
    headers = {"Authorization": "Bearer " + gateway[2].token.get_secret_value()}
    for _ in range(2):
        response = gateway[3].post(
            "/api/gateway/v1/execute",
            json=request_for(gateway[1]).model_dump(mode="json"),
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["execution_status"] == "NOT_EXECUTED"
    assert snapshot(gateway)[1] is None
    from app.main import app

    assert not any("simulat" in path or "dispatch" in path for path in app.openapi()["paths"])


def test_no_credentials_private_payload_or_real_adapters(gateway, monkeypatch):
    grant(gateway)
    admit(gateway)

    def forbidden(*args, **kwargs):
        pytest.fail("Forbidden real side effect")

    import builtins
    import smtplib
    import socket
    import subprocess

    for target, attribute in [
        (smtplib, "SMTP"),
        (socket, "create_connection"),
        (subprocess, "Popen"),
        (builtins, "open"),
    ]:
        monkeypatch.setattr(target, attribute, forbidden)
    received = []

    class CapturingExecutor(SyntheticExecutor):
        def execute(self, value):
            received.append(value)
            return super().execute(value)

    result = dispatch(gateway, executor=CapturingExecutor())
    assert "SIMULATED" in repr(result)
    assert gateway[2].token.get_secret_value() not in repr(received)
    assert not {"token", "credentials", "owner_id", "body", "path"} & received[0].__dict__.keys()
    assert {c.name for c in ExecutionAttempt.__table__.columns}.isdisjoint(
        {"token", "token_digest", "arguments", "body", "document", "password"}
    )


def test_corrupt_attempt_or_history_fails_closed(gateway):
    grant(gateway)
    admit(gateway)
    dispatch(gateway)
    with gateway[0]() as db, db.begin():
        db.scalar(select(ExecutionAttempt)).audit_event_id = 1
    with pytest.raises(OperationError, match="GATEWAY_UNAVAILABLE"):
        dispatch(gateway)


def test_migration_compiles_offline_without_database():
    path = Path(__file__).parents[1] / "migrations/versions/0006_trusted_execution.py"
    spec = importlib.util.spec_from_file_location("execution_migration", path)
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    assert revision.down_revision == "0005_durable_approvals"
    buffer = StringIO()
    context = MigrationContext.configure(
        dialect_name="mysql", opts={"as_sql": True, "output_buffer": buffer}
    )
    with Operations.context(context):
        revision.upgrade()
    sql = buffer.getvalue()
    assert "DATETIME(6)" in sql and "CREATE TABLE execution_attempts" in sql
    assert "UNIQUE (operation_ref)" in sql and "FOREIGN KEY(operation_ref)" in sql
    assert "consumed_at" in sql and "ck_attempt_simulated" in sql


def test_result_contract_rejects_false_success():
    with pytest.raises(ValueError):
        ToolResponse(
            request_id="req_bad",
            decision="ALLOW",
            reason_code="EXECUTION_SUCCEEDED",
            execution_status="NOT_EXECUTED",
            audit_event_ref="event_1",
        )


@pytest.mark.parametrize("token", [None, "not-a-secret-wrapper", SecretStr("invalid")])
def test_missing_or_invalid_authentication_never_dispatches(gateway, token):
    grant(gateway)
    admit(gateway)
    executor = SyntheticExecutor()
    with gateway[0]() as db, pytest.raises(AgentIdentityError, match="AUTH_INVALID"):
        dispatch_simulated(
            db,
            token=token,
            request=request_for(gateway[1]),
            catalog=CATALOG,
            executor=executor,
            now=NOW,
        )
    assert executor.calls == 0 and snapshot(gateway)[1] is None


def test_malformed_or_unknown_action_revalidated(gateway):
    executor = SyntheticExecutor()
    for field, value in [("action", "shell.exec"), ("arguments", {"path": "C:/private"})]:
        bad = request_for(gateway[1]).model_copy(update={field: value})
        with gateway[0]() as db, pytest.raises(OperationError, match="INVALID_REQUEST"):
            dispatch_simulated(db, token=gateway[2].token, request=bad, executor=executor, now=NOW)
    assert executor.calls == 0


def test_database_unavailable_before_admission(gateway):
    grant(gateway)
    admit(gateway)
    engine = gateway[0].kw["bind"]
    executor = SyntheticExecutor()

    def fail(*args):
        raise OperationalError("redacted", {}, Exception("synthetic private DB address"))

    event.listen(engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(OperationError, match="GATEWAY_UNAVAILABLE"):
            dispatch(gateway, executor=executor)
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert executor.calls == 0 and snapshot(gateway)[1] is None


def test_lost_dispatch_commit_acknowledgment_never_calls_executor(gateway):
    grant(gateway)
    admit(gateway)
    executor = SyntheticExecutor()
    with gateway[0]() as db:

        def fail_after_commit(session):
            raise OperationalError("redacted", {}, Exception("lost commit acknowledgment"))

        event.listen(db, "after_commit", fail_after_commit)
        with pytest.raises(OperationError, match="GATEWAY_UNAVAILABLE"):
            dispatch_simulated(
                db,
                token=gateway[2].token,
                request=request_for(gateway[1]),
                executor=executor,
                catalog=CATALOG,
                now=NOW,
            )
        event.remove(db, "after_commit", fail_after_commit)
    assert executor.calls == 0
    operation, attempt = snapshot(gateway)
    assert operation.operation_status == attempt.state == "DISPATCHING"
    with pytest.raises(OperationError, match="OPERATION_IN_PROGRESS"):
        dispatch(gateway, executor=executor)
    assert executor.calls == 0


def test_lost_outcome_commit_acknowledgment_replays_without_execution(gateway):
    grant(gateway)
    admit(gateway)
    executor = SyntheticExecutor()
    commits = 0
    with gateway[0]() as db:

        def fail_after_outcome(session):
            nonlocal commits
            commits += 1
            if commits == 2:
                raise OperationalError("redacted", {}, Exception("lost outcome acknowledgment"))

        event.listen(db, "after_commit", fail_after_outcome)
        with pytest.raises(OperationError, match="GATEWAY_UNAVAILABLE"):
            dispatch_simulated(
                db,
                token=gateway[2].token,
                request=request_for(gateway[1]),
                executor=executor,
                catalog=CATALOG,
                now=NOW,
            )
        event.remove(db, "after_commit", fail_after_outcome)
    assert snapshot(gateway)[0].operation_status == "SUCCEEDED"
    assert dispatch(gateway, executor=executor).response.execution_status == "SUCCEEDED"
    assert executor.calls == 1


def test_database_uniqueness_is_the_attempt_fence(gateway):
    grant(gateway)
    admit(gateway)
    dispatch(gateway)
    _, first = snapshot(gateway)
    with gateway[0]() as db, pytest.raises(IntegrityError), db.begin():
        db.add(
            ExecutionAttempt(
                attempt_ref="attempt_forbidden_duplicate",
                operation_ref=first.operation_ref,
                dispatch_nonce="0" * 64,
                mode="SIMULATED",
                state="DISPATCHING",
                dispatch_at=NOW,
                audit_event_id=first.audit_event_id,
            )
        )
    with gateway[0]() as db:
        assert db.scalar(select(func.count()).select_from(ExecutionAttempt)) == 1


def test_stale_nonce_cannot_overwrite_result(gateway):
    grant(gateway)
    admit(gateway)
    inputs = []

    class Capture(SyntheticExecutor):
        def execute(self, value):
            inputs.append(value)
            return super().execute(value)

    first = dispatch(gateway, executor=Capture())
    from app.services.trusted_execution import _finish

    with gateway[0]() as db, pytest.raises(OperationError, match="GATEWAY_UNAVAILABLE"):
        _finish(
            db,
            inputs[0],
            "bad-nonce",
            request_for(gateway[1]),
            SyntheticOutcome("UNKNOWN"),
            "EXECUTOR_UNCONFIRMED",
            NOW,
        )
    assert dispatch(gateway) == first


@pytest.mark.parametrize("when", ["before", "at", "after"])
def test_result_cache_expiration_never_regenerates(gateway, when):
    from app.services.agent_identity import issue_agent_credential

    grant(gateway, expires_at=(NOW + timedelta(minutes=30)).isoformat())
    admit(gateway)
    executor = SyntheticExecutor()
    first = dispatch(gateway, executor=executor)
    offset = {
        "before": timedelta(minutes=15, microseconds=-1),
        "at": timedelta(minutes=15),
        "after": timedelta(minutes=16),
    }[when]
    # A current credential is required before any historical outcome disclosure.
    with gateway[0]() as db:
        issued = issue_agent_credential(
            db, owner=OWNER, task_ref=gateway[1].task_ref, now=NOW + offset
        )
    bound = gateway[0], gateway[1], issued, gateway[3]
    if when == "before":
        assert dispatch(bound, executor=executor, now=NOW + offset) == first
    else:
        with pytest.raises(OperationError, match="RESULT_EXPIRED"):
            dispatch(bound, executor=executor, now=NOW + offset)
        with bound[0]() as db:
            status = get_operation_status(
                db, token=issued.token, request_id="req_scoped", catalog=CATALOG, now=NOW + offset
            )
        assert status.operation_state == "SUCCEEDED"
    assert executor.calls == 1


@pytest.mark.parametrize("mutation", ["consent", "credential", "task", "approval"])
def test_revocation_after_claim_does_not_rewrite_recorded_outcome(approved_task, mutation):
    submit(approved_task)
    decide(approved_task, "APPROVE")
    executor = BlockingExecutor()
    with ThreadPoolExecutor(1) as pool:
        running = pool.submit(dispatch, approved_task, executor=executor)
        try:
            assert executor.entered.wait(2)
            approval = row(approved_task)
            if mutation == "approval":
                assert decide(approved_task, revoke=True)["in_flight"] is True
            with approved_task[0]() as db:
                if mutation == "consent":
                    revoke_scoped_consent(
                        db,
                        owner=OWNER,
                        task_ref=approval.task_ref,
                        consent_ref=approval.consent_ref,
                        now=NOW,
                    )
                elif mutation == "credential":
                    revoke_agent_credential(
                        db,
                        owner=OWNER,
                        task_ref=approval.task_ref,
                        credential_ref=approved_task[2].credential_ref,
                        now=NOW,
                    )
                elif mutation == "task":
                    revoke_trusted_task(db, owner=OWNER, task_ref=approval.task_ref, now=NOW)
        finally:
            executor.release.set()
        assert running.result(2).response.execution_status == "SUCCEEDED"
    assert snapshot(approved_task)[0].operation_status == "SUCCEEDED"
    assert executor.calls == 1


def test_executor_only_supports_closed_synthetic_action():
    from app.services.synthetic_executor import ExecutionContext, ExecutionInput

    bad = ExecutionInput(
        "op_synthetic",
        "task_synthetic",
        "req_synthetic",
        "key_synthetic",
        "0" * 64,
        "email.send",
        None,
        "version_synthetic",
        ExecutionContext("attempt_synthetic", NOW),
    )
    with pytest.raises(ValueError, match="Unsupported synthetic action"):
        SyntheticExecutor().execute(bad)


def test_unknown_action_is_not_accepted_as_a_tool_request():
    with pytest.raises(ValueError):
        ToolRequest.model_validate({"action": "shell.exec"})
