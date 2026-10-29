"""Step 44C: synthetic, file-backed ASGI transactions and isolated mock B workers."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from app.agent_schemas import OwnerContext
from app.application_contracts import AppFailure, AppSuccess, PlanningView, TaskDetail
from app.browser_auth import BrowserSessions, LocalDemoConfig
from app.database import Base, get_db
from app.main import app
from app.models import ApplicationCommand, GatewayOperation, GatewayTask, WorkflowCheckpoint
from app.services.agent_identity import _utc
from app.services.application_host import ApplicationRuntime
from app.services.document_catalog import FixtureRegistration, register_synthetic_resources
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

ORIGIN = "http://127.0.0.1:8000"
TASKS = "/api/app/v1/tasks"
SESSION = "/api/app/v1/session"


@pytest.fixture
def demo(tmp_path, monkeypatch, request):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tasks.sqlite'}",
        poolclass=NullPool,
        connect_args={"check_same_thread": False, "timeout": 10},
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine, autoflush=getattr(request, "param", False), expire_on_commit=False
    )

    def database():
        with factory() as db:
            yield db

    store = BrowserSessions(LocalDemoConfig(ORIGIN))
    runtime = ApplicationRuntime(workflow_directory=tmp_path / "workflows")
    monkeypatch.setattr(app.state, "browser_sessions", store, raising=False)
    monkeypatch.setattr(app.state, "application_runtime", runtime)
    app.dependency_overrides[get_db] = database
    with TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 50000)) as client:
        client.headers["Origin"] = ORIGIN
        csrf = client.get(SESSION).json()["data"]["csrf_token"]
        code = store.issue_pairing_code().get_secret_value()
        paired = client.post(
            SESSION + "/login", json={"pairing_code": code}, headers={"X-Ghost-CSRF": csrf}
        )
        assert paired.status_code == 200
        client.headers["X-Ghost-CSRF"] = paired.json()["data"]["csrf_token"]
        yield client, factory, store, runtime
    app.dependency_overrides.clear()
    store.invalidate_all()
    engine.dispose()


def create(client, *, key=None, profile="email_draft_v1", resource=None, **extra):
    return client.post(
        TASKS,
        headers={"Idempotency-Key": key or str(uuid4())},
        json={"profile_id": profile, "resource_id": resource, **extra},
    )


def plan(client, ref, *, key=None, prompt="Prepare the synthetic task", **extra):
    return client.post(
        f"{TASKS}/{ref}/planning",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={"user_request": prompt, **extra},
    )


def task(client):
    result = create(client)
    assert result.status_code == 201, result.text
    return result.json()["data"]["task_ref"]


def error(response, status, code):
    assert response.status_code == status, response.text
    assert AppFailure.model_validate_json(response.content).error.code == code
    assert response.headers["cache-control"] == "no-store"


def test_create_detail_idempotency_and_restart(demo):
    client, factory, _, runtime = demo
    key = str(uuid4())
    first = create(client, key=key)
    assert first.status_code == 201, first.text
    parsed = AppSuccess[TaskDetail].model_validate_json(first.content)
    ref = parsed.data.task_ref
    assert parsed.data.authority_state == "OPEN" and parsed.data.planning_state == "NOT_STARTED"
    assert parsed.data.allowed_action == "email.draft"
    assert not parsed.data.in_flight and parsed.data.provenance.effect == "NONE"
    replay = create(client, key=key)
    assert replay.status_code == 200 and replay.json()["replayed"]
    assert replay.json()["data"] == first.json()["data"]
    error(create(client, key=key, profile="email_send_v1"), 409, "IDEMPOTENCY_CONFLICT")
    assert client.get(f"{TASKS}/{ref}").json()["data"] == parsed.data.model_dump(mode="json")
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(GatewayTask)) == 1
        record = db.scalar(select(GatewayTask))
        assert record.owner_id == "local-user"
        assert record.expires_at - record.created_at == timedelta(seconds=900)
    app.state.application_runtime = ApplicationRuntime(
        workflow_directory=runtime.workflow_directory
    )
    assert create(client, key=key).json()["data"]["task_ref"] == ref
    assert client.get(f"{TASKS}/{ref}/planning").json()["data"]["state"] == "NOT_STARTED"


@pytest.mark.parametrize("route", ["create", "planning", "list", "detail", "status"])
def test_anonymous_and_invalid_sessions(demo, route):
    client, _, _, _ = demo
    ref = task(client)
    calls = {
        "create": lambda: create(client),
        "planning": lambda: plan(client, ref),
        "list": lambda: client.get(TASKS),
        "detail": lambda: client.get(f"{TASKS}/{ref}"),
        "status": lambda: client.get(f"{TASKS}/{ref}/planning"),
    }
    client.cookies.clear()
    error(calls[route](), 401, "SESSION_REQUIRED")
    client.cookies.set("ghost_demo_session", "forged")
    error(calls[route](), 401, "SESSION_REQUIRED")


@pytest.mark.parametrize("target", ["create", "planning"])
def test_csrf_origin_forged_identity(demo, target):
    client, _, _, _ = demo
    ref = task(client)
    call = (
        (lambda **kw: create(client, **kw))
        if target == "create"
        else (lambda **kw: plan(client, ref, **kw))
    )
    csrf = client.headers.pop("X-Ghost-CSRF")
    error(call(), 403, "CSRF_INVALID")
    client.headers["X-Ghost-CSRF"] = csrf
    client.headers["Origin"] = "https://foreign.test"
    error(call(), 403, "ORIGIN_FORBIDDEN")
    client.headers["Origin"] = ORIGIN
    error(call(owner_id="someone-else"), 422, "INVALID_REQUEST")
    client.headers["Authorization"] = "Bearer trusted-service-forgery"
    error(call(), 403, "CREDENTIAL_HEADER_FORBIDDEN")


def test_missing_unknown_owner_and_unsupported_routes(demo):
    client, factory, _, _ = demo
    ref = task(client)
    with factory.begin() as db:
        from app.models import User

        db.add(User(id="other-owner"))
        db.flush()
        # An authoritative task of another owner remains indistinguishable from absence.
        source = db.get(GatewayTask, ref)
        db.add(
            GatewayTask(
                task_ref="task_other",
                owner_id="other-owner",
                created_at=source.created_at,
                expires_at=source.expires_at,
                status="OPEN",
                authorization_scope=source.authorization_scope,
                credential_epoch=0,
            )
        )
    for value in ("task_missing", "task_other"):
        error(client.get(f"{TASKS}/{value}"), 404, "NOT_FOUND")
        error(plan(client, value), 404, "NOT_FOUND")
    assert len(client.get(TASKS).json()["data"]["items"]) == 1
    for suffix in ("audit", "catalog", "dispatch", "workflows"):
        error(client.get("/api/app/v1/" + suffix), 404, "NOT_FOUND")


def test_concurrent_create_single_identity(demo):
    client, factory, _, _ = demo
    key = str(uuid4())
    barrier = Barrier(2)

    def invoke(_):
        barrier.wait()
        return create(client, key=key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(invoke, range(2)))
    assert sorted(item.status_code for item in responses) == [200, 201], [r.text for r in responses]
    assert len({r.json()["data"]["task_ref"] for r in responses}) == 1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(GatewayTask)) == 1


def test_pagination_order_cursor_and_snapshot(demo):
    client, _, _, _ = demo
    refs = [task(client) for _ in range(4)]
    page = client.get(TASKS + "?limit=2").json()["data"]
    assert [r["task_ref"] for r in page["items"]] == refs[::-1][:2]
    later = task(client)
    cursor = page["next_cursor"]
    second = client.get(TASKS, params={"limit": "2", "cursor": cursor}).json()["data"]
    assert [r["task_ref"] for r in second["items"]] == refs[::-1][2:]
    assert later not in str(second) and second["next_cursor"] is None
    error(client.get(TASKS, params={"limit": "1", "cursor": cursor}), 400, "INVALID_CURSOR")
    error(client.get(TASKS, params={"limit": "2", "cursor": cursor + "x"}), 400, "INVALID_CURSOR")
    for query in ("limit=0", "limit=51", "limit=01", "limit=2&limit=2", "owner_id=other"):
        error(client.get(TASKS + "?" + query), 422, "INVALID_REQUEST")


@pytest.mark.parametrize("profile", ["document_simulation_v1", "email_draft_v1", "email_send_v1"])
def test_real_graph_mock_planning_authorization_pause_only(demo, profile):
    client, factory, _, runtime = demo
    resource = None
    if profile == "document_simulation_v1":
        with factory() as db:
            registered = register_synthetic_resources(
                db,
                owner=OwnerContext(owner_id="local-user"),
                selection=FixtureRegistration(fixtures=("doc_project_report",)),
            )
            resource = registered[0].resource_ref
    created = create(client, profile=profile, resource=resource)
    assert created.status_code == 201, created.text
    ref = created.json()["data"]["task_ref"]
    key = str(uuid4())
    result = plan(client, ref, key=key)
    assert result.status_code == 200, result.text
    view = AppSuccess[PlanningView].model_validate_json(result.content).data
    assert view.state == "FINISHED" and view.outcome == "PLAN_READY"
    assert view.authorization_decision == "APPROVAL_REQUIRED" and view.approval_ref
    assert view.provenance.planning_source == "MOCK_MODEL" and view.provenance.effect == "NONE"
    replay = plan(client, ref, key=key)
    assert replay.json()["replayed"] and replay.json()["data"] == result.json()["data"]
    error(plan(client, ref, key=key, prompt="changed"), 409, "IDEMPOTENCY_CONFLICT")
    error(plan(client, ref), 409, "PLANNING_ALREADY_STARTED")
    with factory() as db:
        operations = list(db.scalars(select(GatewayOperation)))
        assert len(operations) == 1 and operations[0].operation_status == "PENDING_APPROVAL"
        assert db.scalar(select(WorkflowCheckpoint)).phase == "PAUSED"
        from app.models import ExecutionAttempt

        assert db.scalar(select(func.count()).select_from(ExecutionAttempt)) == 0
    assert (runtime.workflow_directory / f"{ref}.sqlite").is_file()
    for path in runtime.workflow_directory.glob("*"):
        if path.is_file():
            assert b"Prepare the synthetic task" not in path.read_bytes()
            assert b"gpa_" not in path.read_bytes()
    serialized = result.text + client.get(f"{TASKS}/{ref}").text
    assert (
        "gpa_" not in serialized
        and "pairing" not in serialized
        and "Prepare the synthetic task" not in serialized
    )


@pytest.mark.parametrize(
    "status,code,uncertain", [(504, "COMMAND_TIMEOUT", True), (503, "HOST_UNAVAILABLE", False)]
)
def test_host_failure_not_retried_and_durable(demo, monkeypatch, status, code, uncertain):
    from app.application_contracts import ApplicationError

    client, factory, _, runtime = demo
    ref, key, calls = task(client), str(uuid4()), []

    async def failed(**kwargs):
        calls.append(1)
        raise ApplicationError(status, code, uncertain=uncertain)

    monkeypatch.setattr(runtime, "run", failed)
    error(plan(client, ref, key=key), status, code)
    error(
        plan(client, ref, key=key),
        409 if uncertain else status,
        "COMMAND_UNCERTAIN" if uncertain else code,
    )
    assert len(calls) == 1
    app.state.application_runtime = ApplicationRuntime(
        workflow_directory=runtime.workflow_directory
    )
    state = client.get(f"{TASKS}/{ref}/planning").json()["data"]
    assert state["state"] == ("UNCERTAIN" if uncertain else "FAILED")
    assert "Prepare the synthetic task" not in json.dumps(state)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(GatewayOperation)) == 0


def test_interruption_no_replan_and_inactive_task(demo):
    from app.services.application_tasks import claim_planning

    client, factory, _, runtime = demo
    ref = task(client)
    command = "cmd_" + uuid4().hex
    runtime.reserve(command, ref)
    with factory() as db:
        claim_planning(
            db,
            OwnerContext(owner_id="local-user"),
            ref,
            ("a" * 64, str(uuid4()), "b" * 64),
            runtime,
            command,
        )
    runtime.release()
    app.state.application_runtime = ApplicationRuntime(
        workflow_directory=runtime.workflow_directory
    )
    assert client.get(f"{TASKS}/{ref}/planning").json()["data"]["state"] == "UNCERTAIN"
    error(plan(client, ref), 409, "PLANNING_ALREADY_STARTED")
    other = task(client)
    with factory.begin() as db:
        row = db.get(GatewayTask, other)
        row.revoked_at = _utc(None)
    error(plan(client, other), 409, "TASK_NOT_ACTIVE")


def test_capacity_and_bounded_host_timeout(demo):
    from app.application_contracts import ApplicationError

    client, _, _, runtime = demo
    first, second = task(client), task(client)
    runtime.reserve("cmd_active", first)
    error(plan(client, first), 409, "COMMAND_IN_PROGRESS")
    error(plan(client, second), 429, "CAPACITY_EXCEEDED")
    runtime.release()

    async def timeout():
        async def callback(data):
            await asyncio.sleep(2)

        from pydantic import SecretStr

        with pytest.raises(ApplicationError) as caught:
            await runtime.run(
                task_ref=first,
                user_request="Synthetic",
                action="email.draft",
                purpose="prepare_email",
                arguments={},
                credential=SecretStr("synthetic"),
                callback=callback,
                budget_seconds=0.001,
            )
        assert caught.value.code == "COMMAND_TIMEOUT" and caught.value.uncertain

    asyncio.run(timeout())


def test_schema_validation_failure_and_safe_ledger(demo, monkeypatch):
    client, factory, _, runtime = demo
    ref = task(client)

    async def malformed(**kwargs):
        from app.services.application_host import HostObservation

        return HostObservation.model_validate_json(
            json.dumps(
                {
                    "task_ref": ref,
                    "outcome": "PLAN_READY",
                    "plan": {
                        "task_ref": ref,
                        "intent": "prepare_email",
                        "proposed_actions": ["email.send"],
                        "requires_external_action": True,
                        "clarification_required": False,
                    },
                    "request_id": None,
                    "decision": "ALLOW",
                    "reason_code": "ALLOWED",
                    "approval_ref": None,
                    "binding_ref": None,
                    "error": None,
                }
            )
        )

    monkeypatch.setattr(runtime, "run", malformed)
    error(plan(client, ref, prompt="prompt-never-persist-me"), 503, "HOST_UNAVAILABLE")
    with factory() as db:
        rows = list(db.scalars(select(ApplicationCommand)))
        assert rows[-1].state == "UNCERTAIN"
        serialized = json.dumps([row.safe_result for row in rows])
        assert "prompt-never-persist-me" not in serialized and "gpa_" not in serialized
        assert db.scalar(select(func.count()).select_from(GatewayOperation)) == 0


def test_concurrent_planning_one_claim_and_no_reexecution(demo, monkeypatch):
    import threading

    client, factory, _, runtime = demo
    ref, key = task(client), str(uuid4())
    entered, release = threading.Event(), threading.Event()
    from app.application_contracts import ApplicationError

    async def paused(**kwargs):
        entered.set()
        await asyncio.to_thread(release.wait, 5)
        raise ApplicationError(503, "HOST_UNAVAILABLE")

    monkeypatch.setattr(runtime, "run", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(plan, client, ref, key=key)
        assert entered.wait(5)
        error(plan(client, ref, key=key), 409, "COMMAND_IN_PROGRESS")
        assert client.get(f"{TASKS}/{ref}/planning").json()["data"]["state"] == "RUNNING"
        release.set()
        error(future.result(), 503, "HOST_UNAVAILABLE")
    with factory() as db:
        assert (
            len(
                list(
                    db.scalars(
                        select(ApplicationCommand).where(ApplicationCommand.kind == "PLANNING")
                    )
                )
            )
            == 1
        )


def test_allow_decision_still_no_execution(demo):
    from app.models import ExecutionAttempt
    from app.services.scoped_consent import ConsentCreate, create_scoped_consent

    client, factory, _, _ = demo
    owner = OwnerContext(owner_id="local-user")
    with factory() as db:
        resource = register_synthetic_resources(
            db, owner=owner, selection=FixtureRegistration(fixtures=("doc_project_report",))
        )[0]
    ref = create(client, profile="document_simulation_v1", resource=resource.resource_ref).json()[
        "data"
    ]["task_ref"]
    with factory() as db:
        grant = ConsentCreate.model_validate_json(
            json.dumps(
                {
                    "action": "files.read",
                    "purpose": "summarize_document",
                    "resource_ids": [resource.resource_ref],
                    "expires_at": (_utc(None) + timedelta(minutes=5)).isoformat(),
                }
            )
        )
        create_scoped_consent(db, owner=owner, task_ref=ref, payload=grant)
    result = plan(client, ref)
    assert result.status_code == 200, result.text
    assert result.json()["data"]["authorization_decision"] == "ALLOW"
    assert result.json()["data"]["approval_ref"] is None
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ExecutionAttempt)) == 0
        assert db.scalar(select(func.count()).select_from(WorkflowCheckpoint)) == 0
        assert db.get(GatewayTask, ref).status == "OPEN"
    # A later external operator observation must never inherit the plan's NONE effect.
    with factory.begin() as db:
        operation = db.scalar(select(GatewayOperation))
        operation.operation_status = "UNKNOWN"
        operation.execution_started_at = _utc(None)
    detail = client.get(f"{TASKS}/{ref}").json()["data"]
    assert detail["provenance"]["effect"] == "UNCONFIRMED"
    assert detail["provenance"]["evidence"] == "UNATTESTED"
    assert detail["in_flight"] and detail["reconciliation_required"]


@pytest.mark.parametrize(
    "key", [None, "not-a-uuid", str(uuid4()).upper(), "00000000-0000-1000-8000-000000000000"]
)
def test_command_key_validation(demo, key):
    client, _, _, _ = demo
    headers = {} if key is None else {"Idempotency-Key": key}
    result = client.post(
        TASKS, json={"profile_id": "email_draft_v1", "resource_id": None}, headers=headers
    )
    error(result, 400, "IDEMPOTENCY_KEY_REQUIRED" if key is None else "IDEMPOTENCY_KEY_INVALID")


def test_session_expiry_and_bounded_request_validation(demo, monkeypatch):
    client, _, store, _ = demo
    ref = task(client)
    error(plan(client, ref, prompt=" " * 20), 422, "INVALID_REQUEST")
    error(plan(client, ref, prompt="x" * 4001), 422, "INVALID_REQUEST")
    error(plan(client, ref, provider="live"), 422, "INVALID_REQUEST")
    error(client.get(TASKS, params={"limit": "9" * 5000}), 422, "INVALID_REQUEST")
    monkeypatch.setattr(store, "_clock", lambda: _utc(None) + timedelta(hours=24))
    error(plan(client, ref), 401, "SESSION_EXPIRED")


@pytest.mark.parametrize("clarification", [False, True])
def test_definite_planning_result_is_persisted_and_replayed(demo, monkeypatch, clarification):
    from app.services.application_host import HostObservation

    client, _, _, runtime = demo
    ref, key = task(client), str(uuid4())

    async def observed(**kwargs):
        return HostObservation.model_validate_json(
            json.dumps(
                {
                    "task_ref": ref,
                    "outcome": "CLARIFICATION_REQUIRED" if clarification else "FAILED",
                    "plan": {
                        "task_ref": ref,
                        "intent": "clarify_request",
                        "proposed_actions": [],
                        "requires_external_action": False,
                        "clarification_required": True,
                    }
                    if clarification
                    else None,
                    "request_id": None,
                    "decision": None,
                    "reason_code": None,
                    "approval_ref": None,
                    "binding_ref": None,
                    "error": "CLARIFICATION_REQUIRED" if clarification else "PLANNING_FAILED",
                }
            )
        )

    monkeypatch.setattr(runtime, "run", observed)
    result = plan(client, ref, key=key)
    assert result.status_code == 200, result.text
    view = result.json()["data"]
    assert view["state"] == ("FINISHED" if clarification else "FAILED")
    assert view["error_code"] == (None if clarification else "PLANNING_FAILED")
    replay = plan(client, ref, key=key)
    assert replay.json()["replayed"] and replay.json()["data"] == view


def test_total_deadline_includes_credential_acquisition(demo, monkeypatch):
    from threading import Event

    from app.routes import application_tasks as routes

    client, _, _, runtime = demo
    ref, key = task(client), str(uuid4())
    release, done = Event(), Event()
    original = routes.issue_agent_credential

    def slow_issue(db, **kwargs):
        try:
            assert release.wait(2)
            return original(db, **kwargs)
        finally:
            done.set()

    monkeypatch.setattr(routes, "issue_agent_credential", slow_issue)
    monkeypatch.setattr(routes, "PLANNING_BUDGET_SECONDS", 0.1)
    try:
        error(plan(client, ref, key=key), 504, "COMMAND_TIMEOUT")
        assert runtime.quarantined
    finally:
        release.set()
        assert done.wait(2)
    assert client.get(f"{TASKS}/{ref}/planning").json()["data"]["state"] == "UNCERTAIN"
    error(plan(client, ref, key=key), 409, "COMMAND_UNCERTAIN")


def test_openapi_exact_interfaces(demo):
    client, _, _, _ = demo
    schema = app.openapi()
    for path in (TASKS, TASKS + "/{task_ref}", TASKS + "/{task_ref}/planning"):
        for method, operation in schema["paths"][path].items():
            assert operation["security"][0]["AppSession"] == []
            assert "responses" in operation and "200" in operation["responses"] or method == "post"
            if method == "post":
                assert "requestBody" in operation
                assert operation["security"][0]["CsrfHeader"] == []
                assert (
                    len([p for p in operation["parameters"] if p["name"] == "Idempotency-Key"]) == 1
                )
    assert client.get(TASKS).status_code == 200


def test_application_migration_compiles_offline():
    import importlib.util
    from io import StringIO
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy.dialects import mysql
    from sqlalchemy.schema import CreateTable

    path = Path(__file__).resolve().parents[1] / "migrations/versions/0012_application_commands.py"
    spec = importlib.util.spec_from_file_location("application_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "0011_controlled_execution"
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="mysql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        migration.upgrade()
    sql = output.getvalue()
    assert "CREATE TABLE application_commands" in sql and "DROP" not in sql and "ALTER" not in sql
    ddl = str(CreateTable(ApplicationCommand.__table__).compile(dialect=mysql.dialect()))
    for expected in (
        "ascii_bin",
        "DATETIME(6)",
        "InnoDB",
        "fk_app_command_task_owner",
        "uq_app_command_key",
        "uq_app_command_key",
    ):
        assert expected in sql and expected in ddl


def test_original_task_validation_precedes_transaction():
    from app.agent_schemas import TaskScope
    from app.services.agent_identity import AgentIdentityError, create_trusted_task

    now = _utc(None)
    scope = TaskScope(purpose="answer_question", allowed_actions=("tasks.list",))
    with pytest.raises(AgentIdentityError) as invalid_owner:
        create_trusted_task(
            object(), owner=object(), scope=scope, expires_at=now + timedelta(minutes=1), now=now
        )
    assert invalid_owner.value.code == "ROLE_FORBIDDEN"
    with pytest.raises(ValueError):
        create_trusted_task(
            object(),
            owner=OwnerContext(owner_id="local-user"),
            scope=scope,
            expires_at=now,
            now=now,
        )


def test_stable_tie_order_and_cursor_expiry_restart(demo, monkeypatch):
    from app.services import application_tasks as service

    client, factory, _, runtime = demo
    refs = [task(client) for _ in range(3)]
    stamp = _utc(None) - timedelta(seconds=1)
    with factory.begin() as db:
        for row in db.scalars(select(GatewayTask)):
            row.created_at = stamp
    first = client.get(TASKS + "?limit=1").json()["data"]
    assert first["items"][0]["task_ref"] == sorted(refs, reverse=True)[0]
    second = client.get(TASKS, params={"limit": 1, "cursor": first["next_cursor"]}).json()["data"]
    assert second["items"][0]["task_ref"] == sorted(refs, reverse=True)[1]
    assert first["snapshot_at"] == second["snapshot_at"]
    monkeypatch.setattr(service, "_utc", lambda now: stamp + timedelta(seconds=902))
    error(
        client.get(TASKS, params={"limit": 1, "cursor": first["next_cursor"]}),
        400,
        "INVALID_CURSOR",
    )
    app.state.application_runtime = ApplicationRuntime(
        workflow_directory=runtime.workflow_directory
    )
    error(
        client.get(TASKS, params={"limit": 1, "cursor": first["next_cursor"]}),
        400,
        "INVALID_CURSOR",
    )


def test_private_admission_rpc_deadline(demo, monkeypatch):
    from app.application_contracts import ApplicationError
    from app.services import application_host
    from app.services.email_profile import arguments_for
    from pydantic import SecretStr

    _, _, _, runtime = demo
    monkeypatch.setattr(application_host, "RPC_BUDGET_SECONDS", 0.02)

    async def stalled():
        async def callback(data):
            assert data["kind"] == "authorize"
            await asyncio.sleep(2)

        with pytest.raises(ApplicationError) as caught:
            await runtime.run(
                task_ref="task_rpc_timeout",
                user_request="Synthetic only",
                action="email.draft",
                purpose="prepare_email",
                arguments=arguments_for("teammate@example.test").model_dump(mode="json"),
                credential=SecretStr("gpa_cred_" + "0" * 32 + "." + "s" * 43),
                callback=callback,
            )
        assert caught.value.code == "COMMAND_TIMEOUT" and caught.value.uncertain

    asyncio.run(stalled())
