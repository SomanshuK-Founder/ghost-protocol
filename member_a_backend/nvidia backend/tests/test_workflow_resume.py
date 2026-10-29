"""Offline workflow-only admission. SQLite does not prove MySQL row locking."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from app.agent_schemas import OwnerContext
from app.gateway_contracts import Authorization
from app.models import (
    AuditEvent,
    ExecutionAttempt,
    PendingApproval,
    ScopedConsent,
    WorkflowCheckpoint,
)
from app.services.agent_identity import (
    AgentIdentityError,
    revoke_agent_credential,
    revoke_trusted_task,
)
from app.services.operation_ledger import OperationError
from app.services.resource_catalog import EMPTY_CATALOG
from app.services.scoped_consent import revoke_scoped_consent
from app.services.workflow_resume import workflow_checkpoint
from app.workflow_contracts import WorkflowIdentity, WorkflowPause, WorkflowPrepare
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from tests.test_approvals import approved_task as _approved_task
from tests.test_approvals import decide, submit
from tests.test_approvals import row as approval_row
from tests.test_scoped_consent import CATALOG, NOW, OWNER
from tests.test_scoped_consent import gateway as _gateway

gateway = _gateway
approved_task = _approved_task


def call(bound, command, payload=None, binding=None, owner=OWNER, now=NOW, catalog=CATALOG):
    with bound[0]() as db:
        return workflow_checkpoint(
            db,
            owner=owner,
            command=command,
            payload=payload,
            binding_ref=binding.binding_ref if binding else None,
            catalog=catalog,
            now=now,
        )


def paused(bound):
    pending = submit(bound)
    payload = WorkflowPrepare(
        task_ref=bound[1].task_ref,
        approval_ref=pending.approval_ref,
        request_id=pending.request_id,
        idempotency_key="idem_scoped",
    )
    binding = call(bound, "prepare", payload)
    assert call(bound, "prepare", payload) == binding
    return call(bound, "pause", WorkflowPause(checkpoint_id=str(uuid4())), binding)


def identity(bound, binding):
    snapshot = call(bound, "get", binding=binding)
    keys = (
        "task_ref",
        "operation_ref",
        "approval_ref",
        "request_id",
        "idempotency_key",
        "thread_id",
        "checkpoint_id",
        "workflow_version",
    )
    return WorkflowIdentity(
        **{key: getattr(snapshot, key) for key in keys},
        expected_authorization_version=snapshot.authorization_version,
    )


def test_owner_resume_and_separate_consumption(approved_task):
    bound = approved_task
    binding = paused(bound)
    decide(bound, "APPROVE")
    payload = identity(bound, binding)
    for command, phase in [("admit", "ADMITTED"), ("claim", "RESUMING"), ("complete", "RESUMED")]:
        result = call(bound, command, payload, binding)
        assert result.phase == phase and result.operation_ref == binding.operation_ref
    assert call(bound, "complete", payload, binding) == result
    with bound[0]() as db:
        assert db.scalar(select(func.count()).select_from(ExecutionAttempt)) == 0
        assert db.scalar(select(func.count()).select_from(WorkflowCheckpoint)) == 1
        approval = db.scalar(select(PendingApproval))
        assert approval.consumed_at is None and approval.resume_ref is not None
        assert db.get(AuditEvent, int(result.audit_event_ref.removeprefix("event_"))) is not None
        assert "Synthetic" not in str(
            db.scalar(select(AuditEvent).order_by(AuditEvent.id.desc())).detail
        )


@pytest.mark.parametrize(
    "field",
    [
        "task_ref",
        "operation_ref",
        "approval_ref",
        "request_id",
        "idempotency_key",
        "thread_id",
        "checkpoint_id",
        "expected_authorization_version",
    ],
)
def test_identity_conflicts(approved_task, field):
    binding = paused(approved_task)
    decide(approved_task, "APPROVE")
    payload = identity(approved_task, binding)
    changed = payload.model_copy(
        update={
            field: payload.expected_authorization_version + 1
            if field == "expected_authorization_version"
            else str(uuid4())
            if field == "checkpoint_id"
            else "foreign_ref"
        }
    )
    with pytest.raises(OperationError):
        call(approved_task, "admit", changed, binding)
    assert call(approved_task, "get", binding=binding).phase == "PAUSED"


@pytest.mark.parametrize("role", ["wrong_owner", "agent"])
def test_owner_role_required(approved_task, role):
    binding = paused(approved_task)
    owner = OwnerContext(owner_id="other-owner") if role == "wrong_owner" else approved_task[2]
    with pytest.raises(OperationError):
        call(approved_task, "get", binding=binding, owner=owner)


@pytest.mark.parametrize(
    "change",
    [
        "pending",
        "rejected",
        "revoked",
        "expired",
        "credential",
        "task",
        "consent_revoked",
        "consent_expired",
        "missing_consent",
        "resource",
        "recipient",
        "version",
    ],
)
def test_current_authorization_required(approved_task, change, monkeypatch):
    bound = approved_task
    binding = paused(bound)
    if change == "rejected":
        decide(bound, "REJECT")
    elif change != "pending":
        decide(bound, "APPROVE")
    payload = identity(bound, binding)
    timestamp = NOW
    catalog = CATALOG
    if change == "revoked":
        decide(bound, revoke=True)
    elif change == "expired":
        timestamp = NOW + timedelta(minutes=11)
    elif change == "credential":
        with bound[0]() as db:
            revoke_agent_credential(
                db,
                owner=OWNER,
                task_ref=bound[1].task_ref,
                credential_ref=bound[2].credential_ref,
                now=NOW,
            )
    elif change == "task":
        with bound[0]() as db:
            revoke_trusted_task(db, owner=OWNER, task_ref=bound[1].task_ref, now=NOW)
    elif change == "consent_revoked":
        approval = approval_row(bound)
        with bound[0]() as db:
            revoke_scoped_consent(
                db,
                owner=OWNER,
                task_ref=bound[1].task_ref,
                consent_ref=approval.consent_ref,
                now=NOW,
            )
    elif change == "consent_expired":
        with bound[0].begin() as db:
            db.scalar(select(ScopedConsent)).expires_at = NOW + timedelta(minutes=1)
        timestamp = NOW + timedelta(minutes=2)
    elif change == "missing_consent":
        monkeypatch.setattr(
            "app.services.workflow_resume.evaluate_locked_authorization",
            lambda *a, **kw: Authorization(decision="DENY", reason_code="APPROVAL_UNAVAILABLE"),
        )
    elif change == "resource":
        catalog = EMPTY_CATALOG
    elif change in ("version", "recipient"):
        from app.models import GatewayTask

        with bound[0].begin() as db:
            task = db.get(GatewayTask, bound[1].task_ref)
            if change == "version":
                task.authorization_version += 1
            else:
                task.authorization_scope = {
                    **task.authorization_scope,
                    "recipient": "other@example.test",
                }
    with pytest.raises(OperationError):
        call(bound, "admit", payload, binding, now=timestamp, catalog=catalog)
    with bound[0]() as db:
        assert db.scalar(select(func.count()).select_from(ExecutionAttempt)) == 0


def test_duplicates_and_restart_are_conservative(approved_task):
    binding = paused(approved_task)
    decide(approved_task, "APPROVE")
    payload = identity(approved_task, binding)
    call(approved_task, "admit", payload, binding)
    with pytest.raises(OperationError, match="WORKFLOW_ALREADY_ADMITTED"):
        call(approved_task, "admit", payload, binding)
    call(approved_task, "claim", payload, binding)
    # Each call opens a new session; a lost acknowledgment cannot reclaim RESUMING.
    with pytest.raises(OperationError, match="WORKFLOW_ALREADY_CLAIMED"):
        call(approved_task, "claim", payload, binding)
    assert call(approved_task, "get", binding=binding).phase == "RESUMING"


def test_admission_expiry_and_revocation_before_claim(approved_task):
    binding = paused(approved_task)
    decide(approved_task, "APPROVE")
    payload = identity(approved_task, binding)
    call(approved_task, "admit", payload, binding)
    with pytest.raises(OperationError, match="WORKFLOW_EXPIRED"):
        call(approved_task, "claim", payload, binding, now=NOW + timedelta(seconds=60))
    decide(approved_task, revoke=True)
    with pytest.raises(OperationError):
        call(approved_task, "claim", payload, binding)


@pytest.mark.parametrize("command", ["admit", "claim"])
def test_concurrent_admission(approved_task, command):
    binding = paused(approved_task)
    decide(approved_task, "APPROVE")
    payload = identity(approved_task, binding)
    if command == "claim":
        call(approved_task, "admit", payload, binding)
    barrier = Barrier(8)

    def compete(_):
        barrier.wait()
        try:
            call(approved_task, command, payload, binding)
            return True
        except OperationError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(compete, range(8)))
    assert sum(results) == 1


def test_database_failure_rolls_back(approved_task, monkeypatch):
    binding = paused(approved_task)
    decide(approved_task, "APPROVE")
    payload = identity(approved_task, binding)

    def fail(*args):
        raise OperationalError("synthetic", {}, Exception("private marker"))

    monkeypatch.setattr("app.services.workflow_resume._audit", fail)
    with pytest.raises(AgentIdentityError):
        call(approved_task, "admit", payload, binding)
    assert call(approved_task, "get", binding=binding).phase == "PAUSED"


@pytest.mark.parametrize(
    "path",
    ["", "/unknown", "/unknown/pause", "/unknown/admit", "/unknown/claim", "/unknown/complete"],
)
def test_agent_cannot_use_workflow_routes(approved_task, path):
    client = approved_task[3]
    method = "GET" if path == "/unknown" else "POST"
    response = client.request(
        method,
        "/api/control/v1/workflow-checkpoints" + path,
        json={},
        headers={"Authorization": "Bearer " + approved_task[2].token.get_secret_value()},
    )
    assert response.status_code in (401, 403)


def test_duplicate_prepare_event_and_paused_checkpoint_cannot_rebind(approved_task):
    binding = paused(approved_task)
    payload = WorkflowPrepare(
        task_ref=binding.task_ref,
        approval_ref=binding.approval_ref,
        request_id=binding.request_id,
        idempotency_key=binding.idempotency_key,
    )
    barrier = Barrier(8)

    def compete(_):
        barrier.wait()
        return call(approved_task, "prepare", payload).binding_ref

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert set(pool.map(compete, range(8))) == {binding.binding_ref}
    with pytest.raises(OperationError, match="WORKFLOW_CONFLICT"):
        call(approved_task, "pause", WorkflowPause(checkpoint_id=str(uuid4())), binding)


def test_no_transferable_grant_or_client_owner_field(approved_task):
    binding = paused(approved_task)
    response = approved_task[3].post(
        f"/api/control/v1/workflow-checkpoints/{binding.binding_ref}/admit",
        headers={"Authorization": "Bearer synthetic-owner-token"},
        json={"grant": "not-authority", "owner_ref": OWNER.owner_id},
    )
    assert response.status_code == 422


def test_migration_0010_is_additive_mysql_sql_only():
    import importlib.util
    from io import StringIO
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).resolve().parents[1] / "migrations/versions/0010_workflow_resume.py"
    spec = importlib.util.spec_from_file_location("workflow_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "0009_mailpit_email"
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="mysql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        migration.upgrade()
    sql = output.getvalue()
    assert "CREATE TABLE workflow_checkpoints" in sql and "DATETIME(6)" in sql
    assert "uq_workflow_operation" in sql and "uq_workflow_checkpoint" in sql
    assert "fk_workflow_operation_binding" in sql and "ALTER TABLE" not in sql


def test_actual_catalog_deactivation_blocks_resume_without_file_access(gateway):
    from app.agent_schemas import ResourceVersion, TaskScope
    from app.gateway_contracts import ToolRequest
    from app.models import DocumentResource
    from app.services.agent_identity import create_trusted_task, issue_agent_credential
    from app.services.document_catalog import deactivate_resource
    from app.services.operation_ledger import admit_operation
    from tests.test_approvals import decide

    resource_ref, version_ref = "resource_" + uuid4().hex, "version_" + uuid4().hex
    with gateway[0].begin() as db:
        db.add(
            DocumentResource(
                resource_ref=resource_ref,
                owner_ref=OWNER.owner_id,
                resource_type="SYNTHETIC_TEXT",
                display_name="Metadata-only test resource",
                classification="SHAREABLE",
                storage_reference="ghost_demo_v1_doc_project_report",
                content_digest="a" * 64,
                version_ref=version_ref,
                active=True,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    pin = ResourceVersion(
        resource_id=resource_ref, version_ref=version_ref, classification="SHAREABLE"
    )
    with gateway[0]() as db:
        task = create_trusted_task(
            db,
            owner=OWNER,
            scope=TaskScope(
                purpose="summarize_document",
                allowed_actions=("files.read",),
                resource_ids=(resource_ref,),
                resource_versions=(pin,),
                approval_enabled=True,
            ),
            expires_at=NOW + timedelta(hours=1),
            now=NOW,
        )
    with gateway[0]() as db:
        issued = issue_agent_credential(db, owner=OWNER, task_ref=task.task_ref, now=NOW)
    bound = (gateway[0], task, issued, gateway[3])
    request = ToolRequest(
        request_id="resource_resume",
        task_ref=task.task_ref,
        idempotency_key="resource_key",
        action="files.read",
        purpose="summarize_document",
        arguments={"resource_id": resource_ref},
    )
    with gateway[0]() as db:
        pending = admit_operation(db, token=issued.token, request=request, now=NOW)
    binding = call(
        bound,
        "prepare",
        WorkflowPrepare(
            task_ref=task.task_ref,
            approval_ref=pending.approval_ref,
            request_id=request.request_id,
            idempotency_key=request.idempotency_key,
        ),
    )
    binding = call(bound, "pause", WorkflowPause(checkpoint_id=str(uuid4())), binding)
    decide(bound, "APPROVE")
    payload = identity(bound, binding)
    with gateway[0]() as db:
        deactivate_resource(db, owner=OWNER, resource_ref=resource_ref, now=NOW)
    with pytest.raises(OperationError):
        call(bound, "admit", payload, binding)


def test_email_recipient_change_blocks_workflow_without_smtp(gateway):
    from app.models import GatewayTask
    from tests.test_mailpit_email import binding as email_binding
    from tests.test_mailpit_email import decide as email_decide
    from tests.test_mailpit_email import submit as email_submit

    email = email_binding(gateway)
    email.pending = email_submit(email)
    bound = (email.factory, email.task, email.issued, email.client)
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
    with email.factory.begin() as db:
        task = db.get(GatewayTask, email.task.task_ref)
        task.authorization_scope = {
            **task.authorization_scope,
            "recipient": "reviewer@example.test",
        }
    with pytest.raises(OperationError):
        call(bound, "admit", payload, binding)
    assert email.smtp.calls == 0
