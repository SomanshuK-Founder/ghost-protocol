"""Deterministic SQLite approval tests; no claim of MySQL concurrency validation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event

import pytest
from app.agent_schemas import OwnerContext
from app.models import AuditEvent, GatewayOperation, GatewayTask, PendingApproval, ScopedConsent
from app.services.agent_identity import (
    AgentIdentityError,
    create_trusted_task,
    issue_agent_credential,
    revoke_agent_credential,
    revoke_trusted_task,
    validate_agent_credential,
)
from app.services.approvals import owner_approval
from app.services.operation_ledger import (
    OperationError,
    admit_operation,
    get_operation_status,
    validate_future_dispatch,
)
from app.services.scoped_consent import revoke_scoped_consent
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import OperationalError
from tests.test_scoped_consent import CATALOG, NOW, OWNER, SCOPE, request_for
from tests.test_scoped_consent import gateway as _gateway
from tests.test_scoped_consent import member_b_contract as _member_b_contract

gateway = _gateway
member_b_contract = _member_b_contract


@pytest.fixture
def approved_task(gateway):
    factory, _, _, client = gateway
    with factory() as db:
        task = create_trusted_task(
            db,
            owner=OWNER,
            scope=SCOPE.model_copy(update={"approval_enabled": True}),
            catalog=CATALOG,
            now=NOW,
            expires_at=NOW + timedelta(hours=1),
        )
    with factory() as db:
        issued = issue_agent_credential(db, owner=OWNER, task_ref=task.task_ref, now=NOW)
    return factory, task, issued, client


def submit(bound, *, now=NOW, **changes):
    with bound[0]() as db:
        return admit_operation(
            db,
            token=bound[2].token,
            request=request_for(bound[1], **changes),
            catalog=CATALOG,
            now=now,
        )


def row(bound):
    with bound[0]() as db:
        return db.scalar(
            select(PendingApproval).where(PendingApproval.task_ref == bound[1].task_ref)
        )


def decide(bound, resolution=None, *, revoke=False, now=NOW, owner=OWNER):
    approval = row(bound)
    with bound[0]() as db:
        return owner_approval(
            db,
            owner=owner,
            approval_ref=approval.approval_ref,
            resolution=resolution,
            revoke=revoke,
            catalog=CATALOG,
            now=now,
        )


def test_durable_pending_exact_replay_and_member_b(approved_task, member_b_contract):
    first = submit(approved_task)
    assert first.decision == "APPROVAL_REQUIRED" and first.execution_status == "NOT_EXECUTED"
    assert first.approval_ref == row(approved_task).approval_ref
    assert submit(approved_task) == first
    parsed = member_b_contract.ToolResponse.model_validate_json(first.model_dump_json())
    assert parsed.request_id == first.request_id and parsed.approval_ref == first.approval_ref
    with approved_task[0]() as db:
        assert db.scalar(select(func.count()).select_from(PendingApproval)) == 1
        assert db.scalar(select(func.count()).select_from(GatewayOperation)) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"request_id": "req_other"},
        {"idempotency_key": "key_other"},
        {"arguments": {"resource_id": "other_resource"}},
        {"purpose": "answer_question"},
    ],
)
def test_pending_strict_identity(approved_task, changes):
    first = submit(approved_task)
    with pytest.raises(OperationError, match="IDEMPOTENCY_CONFLICT"):
        submit(approved_task, **changes)
    assert submit(approved_task) == first


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/api/control/v1/approvals", None),
        ("get", "/api/control/v1/approvals/{ref}", None),
        ("post", "/api/control/v1/approvals/{ref}/resolve", {"resolution": "APPROVE"}),
        ("post", "/api/control/v1/approvals/{ref}/resolve", {"resolution": "REJECT"}),
        ("post", "/api/control/v1/approvals/{ref}/revoke", {}),
    ],
)
def test_agent_cannot_use_owner_routes(approved_task, method, path, body):
    pending = submit(approved_task)
    response = approved_task[3].request(
        method,
        path.format(ref=pending.approval_ref),
        params={"task_ref": approved_task[1].task_ref} if path.endswith("approvals") else None,
        json=body,
        headers={"Authorization": "Bearer " + approved_task[2].token.get_secret_value()},
    )
    assert response.status_code in (401, 403)
    assert row(approved_task).status == "PENDING"


def test_owner_review_list_and_immutable_decision_body(approved_task):
    pending = submit(approved_task)
    client = approved_task[3]
    headers = {"Authorization": "Bearer synthetic-owner-token"}
    listing = client.get(
        "/api/control/v1/approvals", params={"task_ref": approved_task[1].task_ref}, headers=headers
    )
    assert listing.status_code == 200 and len(listing.json()["approvals"]) == 1
    review = client.get(f"/api/control/v1/approvals/{pending.approval_ref}", headers=headers)
    assert review.status_code == 200 and review.headers["cache-control"] == "no-store"
    assert review.json()["arguments"] == request_for(approved_task[1]).arguments.model_dump(
        mode="json"
    )
    changed = client.post(
        f"/api/control/v1/approvals/{pending.approval_ref}/resolve",
        headers=headers,
        json={"resolution": "APPROVE", "owner_id": "forged", "arguments": {}},
    )
    assert changed.status_code == 422 and row(approved_task).status == "PENDING"
    resolved = client.post(
        f"/api/control/v1/approvals/{pending.approval_ref}/resolve",
        headers=headers,
        json={"resolution": "APPROVE"},
    )
    assert resolved.status_code == 200 and resolved.json()["state"] == "APPROVED"


def test_wrong_owner_and_agent_context_rejected(approved_task):
    submit(approved_task)
    with pytest.raises(AgentIdentityError) as error:
        decide(approved_task, "APPROVE", owner=OwnerContext(owner_id="other-owner"))
    assert error.value.status_code == 404
    with approved_task[0]() as db:
        context = validate_agent_credential(
            db, token=approved_task[2].token, task_ref=approved_task[1].task_ref, now=NOW
        )
    with pytest.raises(AgentIdentityError) as error:
        decide(approved_task, "APPROVE", owner=context)
    assert error.value.status_code == 403 and row(approved_task).status == "PENDING"


def test_approved_consent_is_exact_and_ready_is_not_allow(approved_task):
    submit(approved_task)
    first = decide(approved_task, "APPROVE")
    assert decide(approved_task, "APPROVE") == first
    approval = row(approved_task)
    with approved_task[0]() as db:
        consent = db.get(ScopedConsent, approval.consent_ref)
        operation = db.get(GatewayOperation, approval.operation_ref)
        assert consent.bound_operation_ref == operation.operation_ref
        assert consent.expires_at == approval.expires_at
        assert operation.operation_status == "READY" and operation.decision == "APPROVAL_REQUIRED"
        assert operation.execution_started_at is None
        status = None
    with approved_task[0]() as db:
        status = get_operation_status(
            db,
            token=approved_task[2].token,
            request_id=approval.request_id,
            catalog=CATALOG,
            now=NOW,
        )
    assert status.resume_ref and status.approval_state == "APPROVED"
    assert status.execution_status == "NOT_EXECUTED"
    with pytest.raises(OperationError, match="RESUME_REQUIRED"):
        submit(approved_task)
    # One-use operation consent cannot authorize another identity.
    other = submit(
        approved_task,
        request_id="req_other",
        idempotency_key="key_other",
        action="tasks.list",
        arguments={},
    )
    assert other.decision == "APPROVAL_REQUIRED"


@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("terminal", ["REVOKED", "EXPIRED"])
def test_revocation_and_expiry_are_terminal(approved_task, approved, terminal):
    submit(approved_task)
    if approved:
        decide(approved_task, "APPROVE")
    if terminal == "REVOKED":
        assert decide(approved_task, revoke=True)["state"] == "REVOKED"
        assert decide(approved_task, revoke=True)["state"] == "REVOKED"
    else:
        with pytest.raises(OperationError) as error:
            decide(approved_task, "APPROVE", now=NOW + timedelta(minutes=10))
        assert error.value.status_code == 409
    approval = row(approved_task)
    assert approval.status == terminal and approval.resume_ref is None
    with pytest.raises(OperationError):
        decide(approved_task, "APPROVE")
    result = submit(approved_task)
    assert result.decision == "DENY" and result.reason_code == f"APPROVAL_{terminal}"
    assert result.approval_ref is None
    if approved:
        with approved_task[0]() as db:
            assert db.get(ScopedConsent, approval.consent_ref).revoked_at is not None


def test_rejected_cannot_be_reused_or_reactivated(approved_task):
    submit(approved_task)
    first = decide(approved_task, "REJECT")
    assert decide(approved_task, "REJECT") == first
    with pytest.raises(OperationError):
        decide(approved_task, "APPROVE")
    result = submit(approved_task)
    assert result.decision == "DENY" and result.reason_code == "APPROVAL_REJECTED"
    assert row(approved_task).consent_ref is None


@pytest.mark.parametrize("kind", ["credential", "task", "consent"])
def test_authority_revocation_invalidates_approvals(approved_task, kind):
    submit(approved_task)
    decide(approved_task, "APPROVE")
    approval = row(approved_task)
    factory, task, issued, _ = approved_task
    with factory() as db:
        if kind == "credential":
            revoke_agent_credential(
                db,
                owner=OWNER,
                task_ref=task.task_ref,
                credential_ref=issued.credential_ref,
                now=NOW,
            )
        elif kind == "task":
            revoke_trusted_task(db, owner=OWNER, task_ref=task.task_ref, now=NOW)
        else:
            revoke_scoped_consent(
                db, owner=OWNER, task_ref=task.task_ref, consent_ref=approval.consent_ref, now=NOW
            )
    assert row(approved_task).status == "REVOKED"
    with pytest.raises(OperationError):
        decide(approved_task, "APPROVE")


def test_concurrent_duplicate_and_owner_decisions(approved_task):
    barrier = Barrier(4)

    def duplicate(_):
        barrier.wait(5)
        return submit(approved_task).approval_ref

    with ThreadPoolExecutor(max_workers=4) as pool:
        refs = list(pool.map(duplicate, range(4)))
    assert len(set(refs)) == 1
    barrier = Barrier(2)

    def resolve(value):
        barrier.wait(5)
        try:
            return decide(approved_task, value)["state"]
        except OperationError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(resolve, ["APPROVE", "REJECT"]))
    assert outcomes.count("APPROVAL_ALREADY_RESOLVED") == 1
    assert row(approved_task).status in ("APPROVED", "REJECTED")


@pytest.mark.parametrize("kind", ["expiry", "task", "revocation"])
def test_ordered_race_invalidates_before_owner_decision(approved_task, monkeypatch, kind):
    from concurrent.futures import TimeoutError
    from threading import current_thread

    import app.services.agent_identity as identity
    import app.services.approvals as service

    submit(approved_task)
    entered, attempted, release = Event(), Event(), Event()
    module = identity if kind == "task" else service
    original = module._owned_task

    def hold(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(5)
        return result

    def observe(connection, cursor, statement, parameters, context, many):
        if current_thread().name.startswith("approval-reader") and statement == "BEGIN IMMEDIATE":
            attempted.set()

    def write():
        if kind == "task":
            with approved_task[0]() as db:
                return revoke_trusted_task(
                    db, owner=OWNER, task_ref=approved_task[1].task_ref, now=NOW
                )
        return decide(
            approved_task,
            revoke=kind == "revocation",
            now=NOW + timedelta(minutes=10) if kind == "expiry" else NOW,
        )

    monkeypatch.setattr(module, "_owned_task", hold)
    engine = approved_task[0].kw["bind"]
    event.listen(engine, "before_cursor_execute", observe)
    try:
        with (
            ThreadPoolExecutor(max_workers=1) as writers,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="approval-reader") as readers,
        ):
            writer = writers.submit(write)
            assert entered.wait(5)
            reader = readers.submit(decide, approved_task, "APPROVE")
            try:
                assert attempted.wait(5)
                with pytest.raises(TimeoutError):
                    reader.result(0.1)
            finally:
                release.set()
            writer.result(5)
            with pytest.raises(OperationError):
                reader.result(5)
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", observe)
    assert row(approved_task).status == ("EXPIRED" if kind == "expiry" else "REVOKED")


@pytest.mark.parametrize("phase", ["creation", "decision"])
def test_database_audit_failure_rolls_back(approved_task, monkeypatch, phase):
    if phase == "decision":
        submit(approved_task)

    def failed(*args, **kwargs):
        raise OperationalError("synthetic_failure", {}, Exception("synthetic"))

    monkeypatch.setattr("app.services.approvals.audit_approval", failed)
    with pytest.raises(AgentIdentityError, match="GATEWAY_UNAVAILABLE"):
        submit(approved_task) if phase == "creation" else decide(approved_task, "APPROVE")
    if phase == "creation":
        assert row(approved_task) is None
        with approved_task[0]() as db:
            assert db.scalar(select(func.count()).select_from(GatewayOperation)) == 0
    else:
        assert row(approved_task).status == "PENDING"
        with approved_task[0]() as db:
            assert list(db.scalars(select(ScopedConsent))) == []


def test_privacy_audit_and_no_execution(approved_task, monkeypatch):
    import builtins
    import smtplib
    import subprocess

    def forbidden(*args, **kwargs):
        pytest.fail("External operation attempted")

    monkeypatch.setattr(smtplib, "SMTP", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(builtins, "open", forbidden)
    pending = submit(approved_task)
    decide(approved_task)
    decide(approved_task, "APPROVE")
    decide(approved_task, revoke=True)
    with approved_task[0]() as db:
        approval = db.get(PendingApproval, pending.approval_ref)
        assert db.get(AuditEvent, approval.audit_event_id).outcome == "REVOKED"
        events = list(db.scalars(select(AuditEvent)))
        assert any(item.event_type == "gateway.approval.viewed" for item in events)
        values = repr(db.execute(text("SELECT * FROM pending_approvals")).all()) + repr(
            [item.detail for item in events]
        )
        assert approved_task[2].token.get_secret_value() not in values
        assert '"body"' not in values and '"arguments"' not in repr(
            [item.detail for item in events]
        )
        assert db.scalar(select(GatewayOperation)).execution_started_at is None


def test_persistence_across_new_engine_and_future_recheck(approved_task):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    submit(approved_task)
    decide(approved_task, "APPROVE")
    approval = row(approved_task)
    engine = approved_task[0].kw["bind"]
    url = engine.url
    engine.dispose()
    fresh = create_engine(url)
    factory = sessionmaker(fresh, expire_on_commit=False)
    with factory() as db:
        current = db.get(PendingApproval, approval.approval_ref)
        assert current.status == "APPROVED" and current.operation_ref == approval.operation_ref
    with approved_task[0]() as db:
        context = validate_agent_credential(
            db, token=approved_task[2].token, task_ref=approved_task[1].task_ref, now=NOW
        )
    with factory() as db:
        task = db.get(GatewayTask, approval.task_ref)
        operation = db.get(GatewayOperation, approval.operation_ref)
        grants = list(db.scalars(select(ScopedConsent)))
        assert (
            validate_future_dispatch(
                context,
                request_for(task),
                task,
                grants,
                operation,
                approval=current,
                catalog=CATALOG,
                now=NOW,
            ).decision
            == "ALLOW"
        )
        current.status = "REVOKED"
        assert (
            validate_future_dispatch(
                context,
                request_for(task),
                task,
                grants,
                operation,
                approval=current,
                catalog=CATALOG,
                now=NOW,
            ).decision
            == "DENY"
        )
    fresh.dispose()


@pytest.mark.parametrize(
    "action,args",
    [
        ("files.read", {"resource_id": "synthetic_report"}),
        ("files.list_authorized", {}),
        ("tasks.list", {}),
    ],
)
def test_three_nonemail_action_shapes(approved_task, action, args):
    from tests.test_scoped_consent import PIN

    if action == "files.read":
        args = {"resource_id": PIN.resource_id}
    result = submit(approved_task, action=action, arguments=args)
    assert result.decision == "APPROVAL_REQUIRED"


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"purpose": "answer_question"}, "PURPOSE_MISMATCH"),
        ({"arguments": {"resource_id": "not_owned"}}, "RESOURCE_NOT_AUTHORIZED"),
        (
            {
                "action": "email.send",
                "arguments": {
                    "recipient": "safe@example.test",
                    "subject": "synthetic",
                    "body": "SYNTHETIC_BODY_NEVER_PERSIST",
                },
            },
            "ACTION_DISABLED",
        ),
    ],
)
def test_ineligible_requests_do_not_create_approvals(approved_task, changes, reason):
    result = submit(approved_task, **changes)
    assert result.decision == "DENY" and result.reason_code == reason
    assert row(approved_task) is None


@pytest.mark.parametrize("corruption", ["request", "resources", "history"])
def test_corrupt_binding_or_history_fails_closed(approved_task, corruption):
    submit(approved_task)
    with approved_task[0]() as db, db.begin():
        approval = db.get(PendingApproval, row(approved_task).approval_ref)
        if corruption == "request":
            approval.request_id = "changed"
        elif corruption == "resources":
            approval.resource_versions = []
        else:
            db.get(AuditEvent, approval.audit_event_id).detail = {"status": "PENDING"}
    with pytest.raises(OperationError, match="GATEWAY_UNAVAILABLE"):
        decide(approved_task, "APPROVE")
    with approved_task[0]() as db:
        assert list(db.scalars(select(ScopedConsent))) == []


def test_agent_retry_racing_owner_approval(approved_task):
    first = submit(approved_task)
    barrier = Barrier(2)

    def resolve():
        barrier.wait(5)
        return decide(approved_task, "APPROVE")["state"]

    def retry():
        barrier.wait(5)
        try:
            return submit(approved_task).approval_ref
        except OperationError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        owner = pool.submit(resolve)
        agent = pool.submit(retry)
        assert owner.result(5) == "APPROVED"
        assert agent.result(5) in (first.approval_ref, "RESUME_REQUIRED")
    assert row(approved_task).status == "APPROVED"
    with approved_task[0]() as db:
        assert db.scalar(select(func.count()).select_from(PendingApproval)) == 1


def test_concurrent_approve_and_revoke_finishes_revoked(approved_task):
    submit(approved_task)
    barrier = Barrier(2)

    def decision(revoke):
        barrier.wait(5)
        try:
            return decide(approved_task, None if revoke else "APPROVE", revoke=revoke)
        except OperationError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(decision, [False, True]))
    assert row(approved_task).status == "REVOKED"
    assert submit(approved_task).decision == "DENY"


def test_migration_compiles_offline_and_keeps_history():
    import importlib.util
    import io
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).parents[1] / "migrations/versions/0005_durable_approvals.py"
    spec = importlib.util.spec_from_file_location("approval_revision", path)
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    assert revision.revision == "0005_durable_approvals"
    assert revision.down_revision == "0004_operation_ledger"
    buffer = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="mysql", opts={"as_sql": True, "output_buffer": buffer}
    )
    with Operations.context(context):
        revision.upgrade()
    sql = buffer.getvalue()
    assert "CREATE TABLE pending_approvals" in sql and "DROP TABLE" not in sql
    assert "PENDING_APPROVAL" in sql and "bound_operation_ref" in sql and "CANCELLED" not in sql
    with pytest.raises(RuntimeError, match="retention-aware"):
        revision.downgrade()


def test_five_active_approval_capacity_rolls_back_sixth_operation(approved_task):
    from app.agent_schemas import ResourceVersion, TaskScope
    from app.services.resource_catalog import CatalogResource, ResourceCatalog

    factory = approved_task[0]
    pins = tuple(
        ResourceVersion(resource_id=f"doc_{i}", version_ref="v_one", classification="SHAREABLE")
        for i in range(6)
    )
    catalog = ResourceCatalog(
        resources=tuple(
            CatalogResource(**pin.model_dump(), owner_id=OWNER.owner_id) for pin in pins
        )
    )
    scope = TaskScope(
        purpose=SCOPE.purpose,
        allowed_actions=("files.read",),
        resource_ids=tuple(pin.resource_id for pin in pins),
        resource_versions=pins,
        approval_enabled=True,
    )
    with factory() as db:
        task = create_trusted_task(
            db,
            owner=OWNER,
            scope=scope,
            catalog=catalog,
            now=NOW,
            expires_at=NOW + timedelta(hours=1),
        )
    with factory() as db:
        issued = issue_agent_credential(db, owner=OWNER, task_ref=task.task_ref, now=NOW)
    responses = []
    for index in range(6):
        with factory() as db:
            request = request_for(
                task,
                request_id=f"req_{index}",
                idempotency_key=f"key_{index}",
                arguments={"resource_id": f"doc_{index}"},
            )
            if index == 5:
                with pytest.raises(OperationError) as error:
                    admit_operation(
                        db, token=issued.token, request=request, catalog=catalog, now=NOW
                    )
                assert error.value.status_code == 429
            else:
                responses.append(
                    admit_operation(
                        db, token=issued.token, request=request, catalog=catalog, now=NOW
                    )
                )
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PendingApproval)) == 5
        assert db.scalar(select(func.count()).select_from(GatewayOperation)) == 5
    with factory() as db:
        owner_approval(
            db,
            owner=OWNER,
            approval_ref=responses[0].approval_ref,
            resolution="REJECT",
            catalog=catalog,
            now=NOW,
        )
    with factory() as db:
        assert (
            admit_operation(
                db, token=issued.token, request=request, catalog=catalog, now=NOW
            ).decision
            == "APPROVAL_REQUIRED"
        )


def test_policy_version_change_requires_fresh_review(approved_task):
    from app.gateway_contracts import ConsentCreate
    from app.services.scoped_consent import create_scoped_consent

    submit(approved_task)
    with approved_task[0]() as db:
        create_scoped_consent(
            db,
            owner=OWNER,
            task_ref=approved_task[1].task_ref,
            payload=ConsentCreate(
                action="tasks.list",
                purpose=SCOPE.purpose,
                resource_ids=(),
                expires_at=NOW + timedelta(minutes=5),
            ),
            catalog=CATALOG,
            now=NOW,
        )
    with pytest.raises(OperationError, match="APPROVAL_ALREADY_RESOLVED"):
        decide(approved_task, "APPROVE")
    assert row(approved_task).status == "REVOKED"


def test_approval_near_deadline_does_not_extend_it(approved_task):
    submit(approved_task)
    result = decide(approved_task, "APPROVE", now=NOW + timedelta(minutes=9, seconds=59))
    assert result["expires_at"] == NOW + timedelta(minutes=10)
    with approved_task[0]() as db:
        status = get_operation_status(
            db,
            token=approved_task[2].token,
            request_id="req_scoped",
            catalog=CATALOG,
            now=NOW + timedelta(minutes=10),
        )
    assert status.approval_state == "EXPIRED" and status.decision == "DENY"
    assert status.resume_ref is None and status.execution_status == "NOT_EXECUTED"


@pytest.mark.parametrize("decision", [False, True])
def test_commit_failure_never_returns_phantom_approval(approved_task, monkeypatch, decision):
    from sqlalchemy.orm import Session

    if decision:
        submit(approved_task)
    engine = approved_task[0].kw["bind"]

    def fail_commit(session):
        if session.get_bind() is engine and not session.in_nested_transaction():
            raise OperationalError("synthetic_commit_failure", {}, Exception("synthetic"))

    event.listen(Session, "before_commit", fail_commit)
    try:
        with pytest.raises(AgentIdentityError, match="GATEWAY_UNAVAILABLE"):
            decide(approved_task, "APPROVE") if decision else submit(approved_task)
    finally:
        event.remove(Session, "before_commit", fail_commit)
    assert (row(approved_task).status == "PENDING") if decision else row(approved_task) is None
    with approved_task[0]() as db:
        assert list(db.scalars(select(ScopedConsent))) == []
