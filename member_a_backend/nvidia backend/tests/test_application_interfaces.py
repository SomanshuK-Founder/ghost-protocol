"""A09-A19 use real services/graph, disposable SQLite and synthetic inputs only."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from app.agent_schemas import OwnerContext, TaskScope
from app.application_contracts import ApprovalDetail, AppSuccess, WorkflowView
from app.models import (
    AgentCredential,
    ApplicationCommand,
    AuditEvent,
    ExecutionAttempt,
    GatewayOperation,
    PendingApproval,
    ScopedConsent,
    WorkflowCheckpoint,
)
from app.services.agent_identity import _utc, create_trusted_task, issue_agent_credential
from app.services.document_catalog import (
    FixtureRegistration,
    deactivate_resource,
    register_synthetic_resources,
)
from sqlalchemy import func, select
from tests.test_application_tasks import TASKS, create, error, plan, task
from tests.test_application_tasks import demo as demo

OWNER = OwnerContext(owner_id="local-user")


def post(client, path, payload=None, key=None):
    return client.post(
        path,
        json={} if payload is None else payload,
        headers={"Idempotency-Key": key or str(uuid4())},
    )


def pending(demo):
    client, _, _, _ = demo
    ref = task(client)
    result = plan(client, ref)
    assert result.status_code == 200, result.text
    return ref, result.json()["data"]["approval_ref"]


def decide(client, ref, resolution="APPROVE", key=None):
    return post(client, f"/api/app/v1/approvals/{ref}/decision", {"resolution": resolution}, key)


def continue_task(client, ref, key=None):
    return post(client, f"{TASKS}/{ref}/workflow/continue", key=key)


def register(factory, owner=OWNER, names=("doc_project_report", "doc_tax_2026")):
    with factory() as db:
        return register_synthetic_resources(
            db, owner=owner, selection=FixtureRegistration(fixtures=names)
        )


def test_catalog_metadata_allowlist_without_consent(demo):
    client, factory, _, _ = demo
    owned = register(factory)
    other = register(factory, OwnerContext(owner_id="foreign"))
    result = client.get("/api/app/v1/documents")
    assert result.status_code == 200, result.text
    rows = result.json()["data"]["items"]
    assert {r["resource_id"] for r in rows} == {r.resource_ref for r in owned}
    assert not {r.resource_ref for r in other} & {r["resource_id"] for r in rows}
    for row in rows:
        assert set(row) == {
            "resource_id",
            "version_ref",
            "display_name",
            "classification",
            "resource_type",
            "synthetic",
        }
        assert row["resource_type"] == "SYNTHETIC_TEXT" and row["synthetic"]
    for value in (
        "storage_reference",
        "content_digest",
        "ghost_demo_v1_",
        "documents/private/",
        "gpa_",
        "restricted_financial",
    ):
        assert value not in result.text
    with factory() as db:
        for model in (ScopedConsent, PendingApproval, GatewayOperation, ExecutionAttempt):
            assert db.scalar(select(func.count()).select_from(model)) == 0
    error(
        create(client, profile="document_simulation_v1", resource=other[0].resource_ref),
        404,
        "NOT_FOUND",
    )
    assert result.headers["cache-control"] == "no-store"


def test_catalog_inactive_and_pagination(demo):
    client, factory, _, runtime = demo
    resources = register(factory, names=("doc_project_report", "doc_tax_2026", "doc_schedule"))
    with factory() as db:
        deactivate_resource(db, owner=OWNER, resource_ref=resources[0].resource_ref)
    first = client.get("/api/app/v1/documents?limit=1").json()["data"]
    second = client.get(
        "/api/app/v1/documents", params={"limit": 1, "cursor": first["next_cursor"]}
    ).json()["data"]
    assert first["items"][0]["resource_id"] < second["items"][0]["resource_id"]
    assert resources[0].resource_ref not in str(first) + str(second)
    error(
        client.get("/api/app/v1/documents", params={"limit": 2, "cursor": first["next_cursor"]}),
        400,
        "INVALID_CURSOR",
    )
    error(
        client.get("/api/app/v1/documents", params={"owner_id": "foreign"}), 422, "INVALID_REQUEST"
    )
    from app.services.application_host import ApplicationRuntime

    client.app.state.application_runtime = ApplicationRuntime(
        workflow_directory=runtime.workflow_directory
    )
    error(
        client.get("/api/app/v1/documents", params={"limit": 1, "cursor": first["next_cursor"]}),
        400,
        "INVALID_CURSOR",
    )


def test_approval_list_detail_decision_replay_revocation(demo):
    client, factory, _, _ = demo
    ref, approval = pending(demo)
    path = f"/api/app/v1/approvals/{approval}"
    listed = client.get("/api/app/v1/approvals", params={"task_ref": ref})
    assert listed.status_code == 200 and len(listed.json()["data"]["items"]) == 1
    detail = AppSuccess[ApprovalDetail].model_validate_json(client.get(path).content).data
    assert detail.task_ref == ref and detail.state == "PENDING" and not detail.consumed
    assert detail.arguments.recipient == "teammate@example.test"
    key = str(uuid4())
    first = decide(client, approval, key=key)
    assert first.status_code == 200, first.text
    assert first.json()["data"]["approval"]["state"] == "APPROVED"
    assert decide(client, approval, key=key).json()["replayed"]
    error(decide(client, approval, "REJECT", key), 409, "IDEMPOTENCY_CONFLICT")
    assert (
        client.get("/api/app/v1/approvals", params={"task_ref": ref}).json()["data"]["items"] == []
    )
    revoked = post(client, path + "/revoke")
    assert revoked.status_code == 200 and revoked.json()["data"]["approval"]["state"] == "REVOKED"
    replay = decide(client, approval, key=key)
    assert replay.json()["replayed"] and replay.json()["data"]["approval"]["state"] == "REVOKED"
    error(decide(client, approval), 409, "APPROVAL_STATE_CONFLICT")
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ScopedConsent)) == 1
        assert db.scalar(select(func.count()).select_from(ExecutionAttempt)) == 0


@pytest.mark.parametrize("resolution", ["APPROVE", "REJECT"])
def test_concurrent_identical_decisions(demo, resolution):
    client, factory, _, _ = demo
    _, approval = pending(demo)
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: decide(client, approval, resolution, key), range(2)))
    assert [r.status_code for r in responses] == [200, 200], [r.text for r in responses]
    assert sum(r.json()["replayed"] for r in responses) == 1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ScopedConsent)) == int(
            resolution == "APPROVE"
        )
    if resolution == "REJECT":
        error(decide(client, approval), 409, "APPROVAL_STATE_CONFLICT")


def test_concurrent_conflicting_decisions(demo):
    client, _, _, _ = demo
    _, approval = pending(demo)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda decision: decide(client, approval, decision), ("APPROVE", "REJECT"))
        )
    assert sorted(r.status_code for r in results) == [200, 409]


def test_expired_approval_no_reactivation(demo, monkeypatch):
    from app.services import application_interfaces, approvals

    client, _, _, _ = demo
    ref, approval = pending(demo)
    future = _utc(None) + timedelta(minutes=11)
    monkeypatch.setattr(application_interfaces, "_utc", lambda now: future if now is None else now)
    monkeypatch.setattr(approvals, "_utc", lambda now: future if now is None else now)
    result = client.get(f"/api/app/v1/approvals/{approval}")
    assert result.status_code == 200, result.text
    assert result.json()["data"]["state"] == "EXPIRED"
    error(decide(client, approval), 409, "APPROVAL_STATE_CONFLICT")
    error(continue_task(client, ref), 409, "WORKFLOW_DENIED")


@pytest.mark.parametrize(
    "field,value",
    [
        ("display_name", "private-unapproved-title"),
        ("classification", "SHAREABLE"),
        ("version_ref", "version_" + "z" * 32),
        ("content_digest", "z" * 64),
    ],
)
def test_catalog_rejects_invalid_registered_metadata(demo, field, value):
    from app.models import DocumentResource

    client, factory, _, _ = demo
    resource = register(factory, names=("doc_tax_2026",))[0]
    with factory.begin() as db:
        setattr(db.get(DocumentResource, resource.resource_ref), field, value)
    result = client.get("/api/app/v1/documents")
    error(result, 503, "BACKEND_UNAVAILABLE")
    assert value not in result.text


def test_continuation_rechecks_revocation_before_claim(demo, monkeypatch):
    from app.services import application_host
    from app.services.approvals import owner_approval

    client, factory, _, _ = demo
    ref, approval = pending(demo)
    assert decide(client, approval).status_code == 200
    original = application_host.workflow_checkpoint
    calls = []

    def revoke_before_claim(db, **kwargs):
        calls.append(kwargs["command"])
        if kwargs["command"] == "claim":
            with factory() as revocation:
                owner_approval(revocation, owner=OWNER, approval_ref=approval, revoke=True)
        return original(db, **kwargs)

    monkeypatch.setattr(application_host, "workflow_checkpoint", revoke_before_claim)
    key = str(uuid4())
    error(continue_task(client, ref, key), 409, "WORKFLOW_DENIED")
    assert calls == ["get", "admit", "claim"]
    error(continue_task(client, ref, key), 409, "WORKFLOW_DENIED")
    assert calls == ["get", "admit", "claim"]
    with factory() as db:
        assert db.scalar(select(WorkflowCheckpoint)).phase == "DENIED"
        assert db.get(PendingApproval, approval).status == "REVOKED"
        assert db.scalar(select(func.count()).select_from(ExecutionAttempt)) == 0


def test_real_continuation_safe_stop_and_restart_replay(demo):
    client, factory, _, runtime = demo
    ref, approval = pending(demo)
    before = client.get(f"{TASKS}/{ref}/workflow").json()["data"]
    assert before["phase"] == "PAUSED" and not before["continuation_available"]
    error(continue_task(client, ref), 409, "WORKFLOW_NOT_READY")
    assert decide(client, approval).status_code == 200
    status = client.get(f"{TASKS}/{ref}/workflow")
    assert status.json()["data"]["continuation_available"]
    key = str(uuid4())
    continued = continue_task(client, ref, key)
    assert continued.status_code == 200, continued.text
    view = AppSuccess[WorkflowView].model_validate_json(continued.content).data
    assert (
        view.phase == "RESUMED"
        and not view.continuation_available
        and not view.reconciliation_required
    )
    with factory() as db:
        assert db.scalar(select(WorkflowCheckpoint)).phase == "RESUMED"
        assert db.scalar(select(func.count()).select_from(AgentCredential)) == 1
        assert db.scalar(select(func.count()).select_from(ExecutionAttempt)) == 0
        assert db.get(PendingApproval, approval).consumed_at is None
    from app.services.application_host import ApplicationRuntime

    client.app.state.application_runtime = ApplicationRuntime(
        workflow_directory=runtime.workflow_directory
    )
    replay = continue_task(client, ref, key)
    assert replay.status_code == 200 and replay.json()["replayed"]
    error(continue_task(client, ref), 409, "WORKFLOW_NOT_READY")


@pytest.mark.parametrize("resolution", ["REJECT", "REVOKE"])
def test_denied_continuation(demo, resolution):
    client, _, _, _ = demo
    ref, approval = pending(demo)
    result = (
        post(client, f"/api/app/v1/approvals/{approval}/revoke")
        if resolution == "REVOKE"
        else decide(client, approval, "REJECT")
    )
    assert result.status_code == 200, result.text
    error(continue_task(client, ref), 409, "WORKFLOW_DENIED")


def test_stale_checkpoint_fails_and_no_retry(demo):
    client, factory, _, _ = demo
    ref, approval = pending(demo)
    assert decide(client, approval).status_code == 200
    with factory.begin() as db:
        db.scalar(select(WorkflowCheckpoint)).checkpoint_id = str(uuid4())
    key = str(uuid4())
    error(continue_task(client, ref, key), 409, "WORKFLOW_NOT_READY")
    error(continue_task(client, ref, key), 409, "WORKFLOW_NOT_READY")
    error(continue_task(client, ref), 409, "WORKFLOW_NOT_READY")


def test_unknown_continuation_never_retried(demo, monkeypatch):
    from app.application_contracts import ApplicationError

    client, _, _, runtime = demo
    ref, approval = pending(demo)
    assert decide(client, approval).status_code == 200
    calls = []

    async def timeout(**kwargs):
        calls.append(1)
        raise ApplicationError(504, "COMMAND_TIMEOUT", uncertain=True)

    monkeypatch.setattr(runtime, "run", timeout)
    key = str(uuid4())
    error(continue_task(client, ref, key), 504, "COMMAND_TIMEOUT")
    error(continue_task(client, ref, key), 409, "COMMAND_UNCERTAIN")
    assert client.get(f"{TASKS}/{ref}/workflow").json()["data"]["reconciliation_required"]
    assert len(calls) == 1


def test_operations_timeline_real_events_redacted_and_paginated(demo):
    client, factory, _, _ = demo
    ref, approval = pending(demo)
    assert decide(client, approval).status_code == 200
    history = client.get(f"{TASKS}/{ref}/operations")
    assert history.status_code == 200, history.text
    operation = history.json()["data"]["items"][0]
    assert operation["execution_status"] == "NOT_EXECUTED"
    assert (
        client.get(f"{TASKS}/{ref}/operations/{operation['operation_ref']}").json()["data"]
        == operation
    )
    with factory.begin() as db:
        db.add(
            AuditEvent(
                user_id=OWNER.owner_id,
                event_type="legacy.raw",
                outcome="SENSITIVE",
                detail={"task_ref": ref, "body": "private-marker"},
            )
        )
    page = client.get(f"{TASKS}/{ref}/timeline?limit=1")
    assert page.status_code == 200, page.text
    seen = []
    while True:
        data = page.json()["data"]
        seen.extend(data["items"])
        if data["next_cursor"] is None:
            break
        page = client.get(
            f"{TASKS}/{ref}/timeline", params={"limit": 1, "cursor": data["next_cursor"]}
        )
        assert page.status_code == 200, page.text
    ids = [int(event["event_ref"].removeprefix("event_")) for event in seen]
    assert ids == sorted(set(ids)) and ids
    with factory() as db:
        assert all(db.get(AuditEvent, value) is not None for value in ids)
    for marker in (
        "private-marker",
        "resume_",
        "gpa_",
        "canonical_request_digest",
        "body",
        "arguments",
        "storage_reference",
    ):
        assert marker not in json.dumps(seen) + history.text
    error(client.get(f"{TASKS}/{ref}/operations?cursor=bad"), 422, "INVALID_REQUEST")


def test_cancel_revokes_and_replays(demo):
    client, factory, _, _ = demo
    ref, approval = pending(demo)
    key = str(uuid4())
    cancelled = post(client, f"{TASKS}/{ref}/cancel", key=key)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["data"]["task"]["authority_state"] == "CANCELLED"
    assert post(client, f"{TASKS}/{ref}/cancel", key=key).json()["replayed"]
    error(continue_task(client, ref), 409, "TASK_NOT_ACTIVE")
    with factory() as db:
        assert db.get(PendingApproval, approval).status == "REVOKED"
        assert db.scalar(select(func.count()).select_from(ExecutionAttempt)) == 0


def test_all_routes_require_session_and_post_csrf(demo):
    client, _, _, _ = demo
    ref, approval = pending(demo)
    reads = [
        "/api/app/v1/documents",
        f"/api/app/v1/approvals?task_ref={ref}",
        f"/api/app/v1/approvals/{approval}",
        f"{TASKS}/{ref}/workflow",
        f"{TASKS}/{ref}/operations",
        f"{TASKS}/{ref}/operations/missing",
        f"{TASKS}/{ref}/timeline",
    ]
    writes = [
        f"/api/app/v1/approvals/{approval}/decision",
        f"/api/app/v1/approvals/{approval}/revoke",
        f"{TASKS}/{ref}/cancel",
        f"{TASKS}/{ref}/workflow/continue",
    ]
    csrf = client.headers.pop("X-Ghost-CSRF")
    for path in writes:
        error(post(client, path), 403, "CSRF_INVALID")
    client.headers["X-Ghost-CSRF"] = csrf
    client.headers["Origin"] = "https://foreign.test"
    for path in reads:
        error(client.get(path), 403, "ORIGIN_FORBIDDEN")
    for path in writes:
        error(post(client, path), 403, "ORIGIN_FORBIDDEN")
    client.headers["Origin"] = "http://127.0.0.1:8000"
    for headers, code in (
        ({"Host": "foreign.test"}, "ORIGIN_FORBIDDEN"),
        ({"X-Owner-Id": "foreign"}, "CREDENTIAL_HEADER_FORBIDDEN"),
        ({"Authorization": "Bearer forged"}, "CREDENTIAL_HEADER_FORBIDDEN"),
    ):
        for path in reads:
            error(client.get(path, headers=headers), 403, code)
        for path in writes:
            error(
                client.post(path, json={}, headers={**headers, "Idempotency-Key": str(uuid4())}),
                403,
                code,
            )
    for path in writes:
        error(post(client, path, {"owner_id": "foreign"}), 422, "INVALID_REQUEST")
    client.cookies.clear()
    for path in reads:
        error(client.get(path), 401, "SESSION_REQUIRED")
    for path in writes:
        error(post(client, path), 401, "SESSION_REQUIRED")


def test_cross_owner_references_fail_closed(demo):
    from app.gateway_contracts import ToolRequest
    from app.services.operation_ledger import admit_operation

    client, factory, _, _ = demo
    other = OwnerContext(owner_id="foreign")
    resource = register(factory, other, names=("doc_project_report",))[0]
    now = _utc(None)
    scope = TaskScope(
        purpose="summarize_document",
        allowed_actions=("files.read",),
        resource_ids=(resource.resource_ref,),
        resource_versions=(resource.pin,),
        approval_enabled=True,
    )
    with factory() as db:
        foreign = create_trusted_task(
            db, owner=other, scope=scope, now=now, expires_at=now + timedelta(minutes=10)
        )
    with factory() as db:
        token = issue_agent_credential(db, owner=other, task_ref=foreign.task_ref).token
    request = ToolRequest.model_validate_json(
        json.dumps(
            {
                "request_id": "req_foreign",
                "idempotency_key": "key_foreign",
                "task_ref": foreign.task_ref,
                "action": "files.read",
                "purpose": "summarize_document",
                "arguments": {"resource_id": resource.resource_ref},
            }
        )
    )
    with factory() as db:
        result = admit_operation(db, token=token, request=request)
    for suffix in ("workflow", "operations", "timeline"):
        error(client.get(f"{TASKS}/{foreign.task_ref}/{suffix}"), 404, "NOT_FOUND")
    error(client.get(f"/api/app/v1/approvals/{result.approval_ref}"), 404, "NOT_FOUND")
    error(decide(client, result.approval_ref), 404, "NOT_FOUND")
    error(post(client, f"/api/app/v1/approvals/{result.approval_ref}/revoke"), 404, "NOT_FOUND")
    error(
        client.get("/api/app/v1/approvals", params={"task_ref": foreign.task_ref}), 404, "NOT_FOUND"
    )

    from app.services.application_tasks import _command
    from sqlalchemy.exc import IntegrityError

    local_ref = task(client)
    with factory() as db:
        invalid = _command(
            OWNER,
            ("a" * 64, str(uuid4()), "b" * 64),
            "APPROVAL_REVOKE",
            _utc(None),
            task_ref=local_ref,
        )
        invalid.approval_ref = result.approval_ref
        db.add(invalid)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_metadata_is_not_content_authority(demo):
    from app.gateway_contracts import ToolRequest
    from app.services.operation_ledger import admit_operation

    client, factory, _, _ = demo
    resource = register(factory, names=("doc_tax_2026",))[0]
    assert client.get("/api/app/v1/documents").status_code == 200
    ref = create(client, profile="document_simulation_v1", resource=resource.resource_ref).json()[
        "data"
    ]["task_ref"]
    with factory() as db:
        token = issue_agent_credential(db, owner=OWNER, task_ref=ref).token
    request = ToolRequest.model_validate_json(
        json.dumps(
            {
                "request_id": "req_content",
                "idempotency_key": "key_content",
                "task_ref": ref,
                "action": "files.read",
                "purpose": "summarize_document",
                "arguments": {"resource_id": resource.resource_ref},
            }
        )
    )
    with factory() as db:
        result = admit_operation(db, token=token, request=request)
    assert result.decision == "APPROVAL_REQUIRED" and result.result is None
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ExecutionAttempt)) == 0


@pytest.mark.parametrize("revoked", [False, True])
def test_catalog_does_not_override_expired_revoked_consent(demo, revoked):
    from app.gateway_contracts import ConsentCreate, ToolRequest
    from app.services.operation_ledger import admit_operation
    from app.services.scoped_consent import create_scoped_consent, revoke_scoped_consent

    client, factory, _, _ = demo
    resource = register(factory, names=("doc_tax_2026",))[0]
    ref = create(client, profile="document_simulation_v1", resource=resource.resource_ref).json()[
        "data"
    ]["task_ref"]
    now = _utc(None)
    with factory() as db:
        token = issue_agent_credential(db, owner=OWNER, task_ref=ref).token
    with factory() as db:
        grant = create_scoped_consent(
            db,
            owner=OWNER,
            task_ref=ref,
            now=now,
            payload=ConsentCreate(
                action="files.read",
                purpose="summarize_document",
                resource_ids=(resource.resource_ref,),
                expires_at=now + timedelta(seconds=1),
            ),
        )
    if revoked:
        with factory() as db:
            revoke_scoped_consent(db, owner=OWNER, task_ref=ref, consent_ref=grant.consent_ref)
    request = ToolRequest.model_validate_json(
        json.dumps(
            {
                "request_id": "req_expiry",
                "idempotency_key": "key_expiry",
                "task_ref": ref,
                "action": "files.read",
                "purpose": "summarize_document",
                "arguments": {"resource_id": resource.resource_ref},
            }
        )
    )
    with factory() as db:
        result = admit_operation(db, token=token, request=request, now=now + timedelta(seconds=2))
    assert result.decision == "DENY"
    assert result.reason_code == ("CONSENT_REVOKED" if revoked else "CONSENT_EXPIRED")
    assert client.get("/api/app/v1/documents").status_code == 200
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ExecutionAttempt)) == 0


def test_resource_revocation_invalidates_approval(demo):
    client, factory, _, _ = demo
    resource = register(factory, names=("doc_project_report",))[0]
    ref = create(client, profile="document_simulation_v1", resource=resource.resource_ref).json()[
        "data"
    ]["task_ref"]
    planned = plan(client, ref)
    assert planned.status_code == 200, planned.text
    approval = planned.json()["data"]["approval_ref"]
    with factory() as db:
        deactivate_resource(db, owner=OWNER, resource_ref=resource.resource_ref)
    error(decide(client, approval), 409, "APPROVAL_STATE_CONFLICT")
    assert client.get("/api/app/v1/documents").json()["data"]["items"] == []
    error(continue_task(client, ref), 409, "WORKFLOW_DENIED")


def test_unknown_history_never_resends(demo):
    from app.gateway_contracts import ConsentCreate, ToolRequest
    from app.services.operation_ledger import admit_operation
    from app.services.scoped_consent import create_scoped_consent
    from app.services.synthetic_executor import SyntheticExecutor
    from app.services.trusted_execution import dispatch_simulated

    client, factory, _, _ = demo
    resource = register(factory, names=("doc_project_report",))[0]
    ref = create(client, profile="document_simulation_v1", resource=resource.resource_ref).json()[
        "data"
    ]["task_ref"]
    with factory() as db:
        token = issue_agent_credential(db, owner=OWNER, task_ref=ref).token
    with factory() as db:
        create_scoped_consent(
            db,
            owner=OWNER,
            task_ref=ref,
            payload=ConsentCreate(
                action="files.read",
                purpose="summarize_document",
                resource_ids=(resource.resource_ref,),
                expires_at=_utc(None) + timedelta(minutes=5),
            ),
        )
    request = ToolRequest.model_validate_json(
        json.dumps(
            {
                "request_id": "req_unknown",
                "idempotency_key": "key_unknown",
                "task_ref": ref,
                "action": "files.read",
                "purpose": "summarize_document",
                "arguments": {"resource_id": resource.resource_ref},
            }
        )
    )
    with factory() as db:
        assert admit_operation(db, token=token, request=request).decision == "ALLOW"
    # Explicit trusted test-only synthetic effect; no document is opened.
    executor = SyntheticExecutor(outcome="UNKNOWN")
    with factory() as db:
        dispatch_simulated(db, token=token, request=request, executor=executor)
    for _ in range(2):
        result = client.get(f"{TASKS}/{ref}/operations")
        assert result.status_code == 200, result.text
        observed = result.json()["data"]["items"][0]
        assert observed["state"] == "UNKNOWN" and observed["reconciliation_required"]
        assert observed["provenance"]["effect"] == "UNCONFIRMED"
    error(continue_task(client, ref), 409, "RECONCILIATION_REQUIRED")
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ExecutionAttempt)) == 1


def test_concurrent_continuation_one_claim(demo, monkeypatch):
    from threading import Event

    from app.application_contracts import ApplicationError

    client, factory, _, runtime = demo
    ref, approval = pending(demo)
    assert decide(client, approval).status_code == 200
    entered, release = Event(), Event()

    async def blocked(**kwargs):
        import asyncio

        entered.set()
        await asyncio.to_thread(release.wait, 3)
        raise ApplicationError(503, "HOST_UNAVAILABLE")

    monkeypatch.setattr(runtime, "run", blocked)
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(continue_task, client, ref, key)
        assert entered.wait(3)
        error(continue_task(client, ref, key), 409, "COMMAND_IN_PROGRESS")
        release.set()
        error(future.result(), 503, "HOST_UNAVAILABLE")
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(ApplicationCommand)
                .where(ApplicationCommand.kind == "CONTINUE")
            )
            == 1
        )


def test_timeline_cursor_task_binding(demo):
    client, _, _, _ = demo
    first, _ = pending(demo)
    second, _ = pending(demo)
    page = client.get(f"{TASKS}/{first}/timeline?limit=1").json()["data"]
    assert page["next_cursor"]
    error(
        client.get(
            f"{TASKS}/{second}/timeline", params={"limit": 1, "cursor": page["next_cursor"]}
        ),
        400,
        "INVALID_CURSOR",
    )


def test_migration_0013_compiles_preserving_historical_data():
    import importlib.util
    from io import StringIO
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = (
        Path(__file__).resolve().parents[1] / "migrations/versions/0013_application_interfaces.py"
    )
    spec = importlib.util.spec_from_file_location("application_interfaces_migration", path)
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    assert revision.down_revision == "0012_application_commands"
    output = StringIO()
    with Operations.context(
        MigrationContext.configure(
            dialect_name="mysql", opts={"as_sql": True, "output_buffer": output}
        )
    ):
        revision.upgrade()
    ddl = output.getvalue()
    assert "UPDATE application_commands SET planning_task_ref=task_ref" in ddl
    for name in (
        "uq_app_planning_task",
        "uq_app_creation_task",
        "uq_app_continuation_binding",
        "fk_app_approval_owner",
        "fk_app_workflow_owner",
    ):
        assert name in ddl
    assert "DROP TABLE" not in ddl and "DELETE" not in ddl
