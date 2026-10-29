"""The same mutation boundaries under shipped and legacy-test session configurations."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from app.application_contracts import ApplicationError
from app.models import (
    ApplicationCommand,
    AuditEvent,
    ExecutionAttempt,
    GatewayOperation,
    GatewayTask,
    PendingApproval,
    ScopedConsent,
)
from app.services import application_interfaces, approvals
from app.services.agent_identity import _utc
from sqlalchemy import func, select
from tests.test_application_interfaces import continue_task, decide, pending, post
from tests.test_application_tasks import TASKS, error, task
from tests.test_application_tasks import demo as demo

pytestmark = pytest.mark.parametrize(
    "demo", [False, True], indirect=True, ids=["shipped-autoflush-false", "autoflush-true"]
)


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_approve_replay_then_real_continuation(demo):
    client, factory, _, _ = demo
    ref, approval = pending(demo)
    key = str(uuid4())
    first = decide(client, approval, key=key)
    assert first.status_code == 200, first.text
    assert first.json()["data"]["approval"]["state"] == "APPROVED"
    assert decide(client, approval, key=key).json()["replayed"]
    assert decide(client, approval).status_code == 200
    continued = continue_task(client, ref)
    assert continued.status_code == 200 and continued.json()["data"]["phase"] == "RESUMED"
    with factory() as db:
        row = db.get(PendingApproval, approval)
        assert row.revision == 1 and row.consumed_at is None
        assert count(db, ScopedConsent) == 1
        assert count(db, ExecutionAttempt) == 0


@pytest.mark.parametrize("resolution", ["REJECT", "REVOKE"])
def test_reject_and_revoke_do_not_dispatch(demo, resolution):
    client, factory, _, _ = demo
    ref, approval = pending(demo)
    key = str(uuid4())
    if resolution == "REJECT":
        result = decide(client, approval, "REJECT", key)
        replay = decide(client, approval, "REJECT", key)
    else:
        assert decide(client, approval).status_code == 200
        result = post(client, f"/api/app/v1/approvals/{approval}/revoke", key=key)
        replay = post(client, f"/api/app/v1/approvals/{approval}/revoke", key=key)
    assert result.status_code == 200 and replay.status_code == 200
    assert replay.json()["replayed"]
    error(continue_task(client, ref), 409, "WORKFLOW_DENIED")
    with factory() as db:
        assert db.get(PendingApproval, approval).consumed_at is None
        assert count(db, ExecutionAttempt) == 0


@pytest.mark.parametrize("expired", [True, False], ids=["expiry", "authorization-version"])
def test_reconciliation_before_refresh(demo, monkeypatch, expired):
    client, factory, _, _ = demo
    ref, approval = pending(demo)
    if expired:
        future = _utc(None) + timedelta(minutes=11)
        for module in (application_interfaces, approvals):
            monkeypatch.setattr(module, "_utc", lambda now: future if now is None else now)
    else:
        with factory.begin() as db:
            db.get(GatewayTask, ref).authorization_version += 1
    detail = client.get(f"/api/app/v1/approvals/{approval}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["state"] == ("EXPIRED" if expired else "REVOKED")
    error(decide(client, approval), 409, "APPROVAL_STATE_CONFLICT")
    with factory() as db:
        assert count(db, ScopedConsent) == count(db, ExecutionAttempt) == 0


@pytest.mark.parametrize("conflicting", [False, True])
def test_concurrent_decision_is_one_transition(demo, conflicting):
    client, factory, _, _ = demo
    _, approval = pending(demo)
    key = str(uuid4())
    decisions = ("APPROVE", "REJECT") if conflicting else ("APPROVE", "APPROVE")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda resolution: decide(client, approval, resolution, key), decisions)
        )
    assert sorted(response.status_code for response in results) == (
        [200, 409] if conflicting else [200, 200]
    )
    with factory() as db:
        row = db.get(PendingApproval, approval)
        assert row.revision == 1 and row.consumed_at is None
        assert count(db, ScopedConsent) == int(row.status == "APPROVED")
        assert count(db, ExecutionAttempt) == 0


def test_projection_failure_rolls_back_transition_and_command(demo, monkeypatch):
    client, factory, _, _ = demo
    ref, approval = pending(demo)
    with factory() as db:
        audit_count = count(db, AuditEvent)
        version = db.get(GatewayTask, ref).authorization_version

    def fail(*args, **kwargs):
        raise ApplicationError(503, "BACKEND_UNAVAILABLE")

    key = str(uuid4())
    with monkeypatch.context() as fault:
        fault.setattr(application_interfaces, "mutation_view", fail)
        error(decide(client, approval, key=key), 503, "BACKEND_UNAVAILABLE")
    with factory() as db:
        row = db.get(PendingApproval, approval)
        assert row.status == "PENDING" and row.revision == 0 and row.consumed_at is None
        assert db.get(GatewayTask, ref).authorization_version == version
        assert db.scalar(select(GatewayOperation)).operation_status == "PENDING_APPROVAL"
        assert count(db, AuditEvent) == audit_count
        assert count(db, ScopedConsent) == count(db, ExecutionAttempt) == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(ApplicationCommand)
                .where(ApplicationCommand.kind == "APPROVAL_DECISION")
            )
            == 0
        )
    assert decide(client, approval, key=key).status_code == 200


def test_cancel_unplanned_task_is_persisted_before_projection(demo):
    client, factory, _, _ = demo
    ref, key = task(client), str(uuid4())
    result = post(client, f"{TASKS}/{ref}/cancel", key=key)
    assert result.status_code == 200, result.text
    assert result.json()["data"]["task"]["authority_state"] == "CANCELLED"
    assert post(client, f"{TASKS}/{ref}/cancel", key=key).json()["replayed"]
    assert client.get(f"{TASKS}/{ref}").json()["data"]["authority_state"] == "CANCELLED"
    with factory() as db:
        assert db.get(GatewayTask, ref).revoked_at is not None
        assert count(db, ExecutionAttempt) == 0


def test_cross_owner_approval_is_rejected(demo):
    import json

    from app.agent_schemas import OwnerContext, TaskScope
    from app.gateway_contracts import ToolRequest
    from app.services.agent_identity import create_trusted_task, issue_agent_credential
    from app.services.operation_ledger import admit_operation
    from tests.test_application_interfaces import register

    client, factory, _, _ = demo
    owner = OwnerContext(owner_id="foreign")
    resource = register(factory, owner=owner, names=("doc_schedule",))[0]
    with factory() as db:
        foreign = create_trusted_task(
            db,
            owner=owner,
            scope=TaskScope(
                purpose="summarize_document",
                allowed_actions=("files.read",),
                resource_ids=(resource.resource_ref,),
                resource_versions=(resource.pin,),
                approval_enabled=True,
            ),
            expires_at=_utc(None) + timedelta(minutes=5),
        )
    with factory() as db:
        credential = issue_agent_credential(db, owner=owner, task_ref=foreign.task_ref).token
    request = ToolRequest.model_validate_json(
        json.dumps(
            {
                "request_id": "req_foreign_flush",
                "task_ref": foreign.task_ref,
                "action": "files.read",
                "purpose": "summarize_document",
                "arguments": {"resource_id": resource.resource_ref},
                "idempotency_key": "key_foreign_flush",
            }
        )
    )
    with factory() as db:
        approval = admit_operation(db, token=credential, request=request).approval_ref
    error(decide(client, approval), 404, "NOT_FOUND")
    error(post(client, f"/api/app/v1/approvals/{approval}/revoke"), 404, "NOT_FOUND")
    with factory() as db:
        assert db.get(PendingApproval, approval).status == "PENDING"
        assert count(db, ExecutionAttempt) == 0
