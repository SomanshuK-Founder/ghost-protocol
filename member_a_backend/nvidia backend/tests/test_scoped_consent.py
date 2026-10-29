import ast
import importlib.util
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import pytest
from app.agent_schemas import OwnerContext, ResourceVersion, TaskScope
from app.config import get_settings
from app.database import Base, get_db
from app.gateway_contracts import ConsentCreate, ToolRequest
from app.main import app
from app.models import AuditEvent, GatewayOperation, GatewayTask, PendingApproval, ScopedConsent
from app.services.agent_identity import (
    AgentIdentityError,
    create_trusted_task,
    issue_agent_credential,
    revoke_trusted_task,
    validate_agent_credential,
)
from app.services.resource_catalog import CatalogResource, ResourceCatalog, get_resource_catalog
from app.services.scoped_consent import (
    authorize_request,
    create_scoped_consent,
    evaluate_authorization,
    revoke_scoped_consent,
)
from app.services.tools import TOOLS
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateTable

NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)
OWNER = OwnerContext(owner_id="local-user")
OTHER = OwnerContext(owner_id="other-owner")
PIN = ResourceVersion(
    resource_id="resource_one", version_ref="version_one", classification="SHAREABLE"
)
CATALOG = ResourceCatalog(resources=(CatalogResource(**PIN.model_dump(), owner_id=OWNER.owner_id),))
SCOPE = TaskScope(
    purpose="summarize_document",
    allowed_actions=(
        "files.read",
        "files.list_authorized",
        "tasks.list",
        "email.draft",
        "email.send",
    ),
    resource_ids=(PIN.resource_id,),
    resource_versions=(PIN,),
)


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'scoped.sqlite').as_posix()}", hide_parameters=True
    )

    @event.listens_for(engine, "connect")
    def configure(connection, record):
        connection.isolation_level = None
        connection.execute("PRAGMA foreign_keys=ON")

    @event.listens_for(engine, "begin")
    def begin(connection):
        # SQLite has no row locks; serialize offline transactions for ordering tests.
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        task = create_trusted_task(
            db,
            owner=OWNER,
            scope=SCOPE,
            catalog=CATALOG,
            now=NOW,
            expires_at=NOW + timedelta(hours=1),
        )
    with factory() as db:
        issued = issue_agent_credential(db, owner=OWNER, task_ref=task.task_ref, now=NOW)
    monkeypatch.setenv("API_BEARER_TOKEN", "synthetic-owner-token")
    get_settings.cache_clear()

    def db_override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_resource_catalog] = lambda: CATALOG
    # HTTP and trusted services use the same deterministic UTC clock.
    monkeypatch.setattr(
        "app.services.agent_identity._utc", lambda now: now if now is not None else NOW
    )
    monkeypatch.setattr(
        "app.services.scoped_consent._utc", lambda now: now if now is not None else NOW
    )
    monkeypatch.setattr(
        "app.services.operation_ledger._utc", lambda now: now if now is not None else NOW
    )
    monkeypatch.setattr("app.services.approvals._utc", lambda now: now if now is not None else NOW)

    def no_tool(*args, **kwargs):
        pytest.fail("A tool was executed during authorization")

    for name in TOOLS:
        monkeypatch.setitem(TOOLS, name, no_tool)
    with TestClient(app) as client:
        yield factory, task, issued, client
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    engine.dispose()


def request_for(task, **changes):
    return ToolRequest.model_validate_json(
        json.dumps(
            {
                "request_id": "req_scoped",
                "task_ref": task.task_ref,
                "action": "files.read",
                "purpose": SCOPE.purpose,
                "arguments": {"resource_id": PIN.resource_id},
                "idempotency_key": "idem_scoped",
                **changes,
            }
        )
    )


def grant(gateway, **changes):
    factory, task, _, _ = gateway
    payload = ConsentCreate.model_validate_json(
        json.dumps(
            {
                "action": "files.read",
                "purpose": SCOPE.purpose,
                "resource_ids": [PIN.resource_id],
                "expires_at": (NOW + timedelta(minutes=10)).isoformat(),
                **changes,
            }
        )
    )
    with factory() as db:
        return create_scoped_consent(
            db, owner=OWNER, task_ref=task.task_ref, payload=payload, catalog=CATALOG, now=NOW
        )


def authorize(gateway, now=NOW, **changes):
    factory, task, issued, _ = gateway
    with factory() as db:
        return authorize_request(
            db, token=issued.token, request=request_for(task, **changes), catalog=CATALOG, now=now
        )


def post(gateway, **changes):
    _, task, issued, client = gateway
    return client.post(
        "/api/gateway/v1/execute",
        json=request_for(task, **changes).model_dump(mode="json"),
        headers={"Authorization": f"Bearer {issued.token.get_secret_value()}"},
    )


def test_valid_scoped_consent_and_audit(gateway):
    grant(gateway)
    response = post(gateway)
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "ALLOW" and data["reason_code"] == "EXECUTION_NOT_STARTED"
    assert data["execution_status"] == "NOT_EXECUTED" and data["result"] is None
    assert data["approval_ref"] is None
    factory, task, issued, _ = gateway
    with factory() as db:
        audit = db.get(AuditEvent, int(data["audit_event_ref"].removeprefix("event_")))
        assert audit.detail == {
            "request_id": "req_scoped",
            "task_ref": task.task_ref,
            "action": "files.read",
            "decision": "ALLOW",
            "reason_code": "EXECUTION_NOT_STARTED",
            "timestamp": NOW.isoformat(),
            "operation_ref": db.scalar(select(GatewayOperation)).operation_ref,
            "operation_state": "ADMITTED",
            "revision": 0,
            "authorization_version": 1,
        }
        assert issued.token.get_secret_value() not in repr(audit.detail)
    assert set(data) == {
        "request_id",
        "decision",
        "execution_status",
        "reason_code",
        "approval_ref",
        "result",
        "audit_event_ref",
    }


def test_missing_consent_is_deny_without_pending_state(gateway):
    result = post(gateway).json()
    assert result["decision"] == "DENY" and result["reason_code"] == "APPROVAL_UNAVAILABLE"
    assert result["approval_ref"] is result["result"] is None
    assert result["execution_status"] == "NOT_EXECUTED"
    factory, _, _, _ = gateway
    with factory() as db:
        assert list(db.scalars(select(ScopedConsent))) == []
    with gateway[0]() as db:
        assert list(db.scalars(select(PendingApproval))) == []
    assert {path for path in app.openapi()["paths"] if "resume" in path} == {
        "/api/gateway/v1/operations/{request_id}/resume"
    }
    response = gateway[3].post(
        "/api/gateway/v1/operations/req_scoped/resume",
        json={"resume_ref": "not_authority"},
        headers={"Authorization": "Bearer " + gateway[2].token.get_secret_value()},
    )
    assert response.status_code == 403 and response.json()["error_code"] == "ACTION_DISABLED"


@pytest.mark.parametrize("delta,decision", [(-1, "ALLOW"), (0, "DENY"), (1, "DENY")])
def test_half_open_expiration(gateway, delta, decision):
    consent = grant(gateway)
    result = authorize(gateway, now=consent.expires_at + timedelta(microseconds=delta))
    assert result.decision == decision
    if decision == "DENY":
        assert result.reason_code == "CONSENT_EXPIRED"


def test_repeated_revocation_and_terminal_regrant(gateway):
    consent = grant(gateway)
    factory, task, _, _ = gateway
    for _ in range(2):
        with factory() as db:
            revoke_scoped_consent(
                db, owner=OWNER, task_ref=task.task_ref, consent_ref=consent.consent_ref, now=NOW
            )
    with factory() as db:
        assert db.get(ScopedConsent, consent.consent_ref).version == 2
        assert db.get(GatewayTask, task.task_ref).authorization_version == 2
    grant(gateway)
    assert authorize(gateway).reason_code == "CONSENT_REVOKED"


def test_overlapping_grants_deny_regardless_of_order(gateway):
    grant(gateway)
    grant(gateway)
    assert authorize(gateway).reason_code == "CONSENT_AMBIGUOUS"


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"purpose": "answer_question"}, "PURPOSE_MISMATCH"),
        ({"arguments": {"resource_id": "resource_other"}}, "RESOURCE_NOT_AUTHORIZED"),
        (
            {
                "action": "email.send",
                "arguments": {
                    "recipient": "other@example.test",
                    "subject": "Synthetic",
                    "body": "Synthetic",
                },
            },
            "ACTION_DISABLED",
        ),
        (
            {
                "action": "email.draft",
                "arguments": {
                    "recipient": "safe@example.test",
                    "subject": "Synthetic",
                    "body": "Synthetic",
                },
            },
            "ACTION_DISABLED",
        ),
    ],
)
def test_mismatched_request_never_authorizes(gateway, changes, reason):
    grant(gateway)
    result = authorize(gateway, **changes)
    assert result.decision == "DENY" and result.reason_code == reason


def test_wrong_task_and_wrong_owner(gateway):
    factory, task, issued, _ = gateway
    with factory() as db, pytest.raises(AgentIdentityError) as failure:
        authorize_request(
            db,
            token=issued.token,
            request=request_for(task, task_ref="task_foreign"),
            catalog=CATALOG,
            now=NOW,
        )
    assert failure.value.code == "TASK_SCOPE_MISMATCH"
    with factory() as db:
        context = validate_agent_credential(db, token=issued.token, task_ref=task.task_ref, now=NOW)
    assert (
        evaluate_authorization(
            context.model_copy(update={"owner_id": "other-owner"}),
            request_for(task),
            task,
            [],
            catalog=CATALOG,
            now=NOW,
        ).reason_code
        == "TASK_SCOPE_MISMATCH"
    )
    with factory() as db, pytest.raises(AgentIdentityError):
        revoke_scoped_consent(
            db, owner=OTHER, task_ref=task.task_ref, consent_ref="consent_unknown", now=NOW
        )


@pytest.mark.parametrize("context", [None, OWNER])
def test_pure_evaluator_rejects_unauthenticated_context(gateway, context):
    _, task, _, _ = gateway
    assert (
        evaluate_authorization(
            context, request_for(task), task, [], catalog=CATALOG, now=NOW
        ).reason_code
        == "AUTH_INVALID"
    )


@pytest.mark.parametrize(
    "change",
    [
        {"action": "shell.exec"},
        {"action": "files.read", "arguments": {"path": "/private/secret"}},
        {"arguments": {"resource_id": "../private"}},
        {"arguments": {"resource_id": "*"}},
        {"arguments": {"resource_id": 17}},
        {"purpose": ""},
        {"purpose": None},
        {"user_id": "other-owner"},
        {"arguments": {"resource_id": PIN.resource_id, "allow": True}},
    ],
)
def test_malformed_requests_fail_before_decision_without_leaks(gateway, change):
    _, task, issued, client = gateway
    payload = {**request_for(task).model_dump(mode="json"), **change}
    response = client.post(
        "/api/gateway/v1/execute",
        json=payload,
        headers={"Authorization": f"Bearer {issued.token.get_secret_value()}"},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "INVALID_REQUEST"
    assert "arguments" not in response.text and "decision" not in response.json()


@pytest.mark.parametrize(
    "arguments",
    [
        {"recipient": "Bad <safe@example.test>", "subject": "S", "body": "B"},
        {"recipient": "safe@example.test,other@example.test", "subject": "S", "body": "B"},
        {"recipient": "safe@example.test", "subject": "S\nBcc: other@example.test", "body": "B"},
        {
            "recipient": "safe@example.test",
            "subject": "S",
            "body": "B",
            "attachment_resource_ids": ["x", "x"],
        },
        {"recipient": "safe@example.test", "subject": "S", "body": "B", "smtp_host": "localhost"},
    ],
)
def test_email_shape_validation(gateway, arguments):
    _, task, _, _ = gateway
    with pytest.raises(ValidationError):
        request_for(task, action="email.send", arguments=arguments)


@pytest.mark.parametrize(
    "authorization", [None, "Basic ignored", "Bearer bad", "Bearer synthetic-owner-token"]
)
def test_missing_invalid_owner_auth_cannot_access_gateway(gateway, authorization):
    _, task, _, client = gateway
    headers = {"Authorization": authorization} if authorization else {}
    response = client.post(
        "/api/gateway/v1/execute", json=request_for(task).model_dump(mode="json"), headers=headers
    )
    assert response.status_code == 401


def test_owner_only_grant_and_idempotent_revoke_http(gateway):
    _, task, issued, client = gateway
    path = f"/api/control/v1/tasks/{task.task_ref}/consents"
    payload = {
        "action": "files.read",
        "purpose": SCOPE.purpose,
        "resource_ids": [PIN.resource_id],
        "expires_at": (NOW + timedelta(minutes=5)).isoformat(),
    }
    assert (
        client.post(
            path,
            json=payload,
            headers={"Authorization": f"Bearer {issued.token.get_secret_value()}"},
        ).status_code
        == 401
    )
    response = client.post(
        path, json=payload, headers={"Authorization": "Bearer synthetic-owner-token"}
    )
    assert response.status_code == 201
    ref = response.json()["consent_ref"]
    for _ in range(2):
        response = client.post(
            f"{path}/{ref}/revoke",
            json={},
            headers={"Authorization": "Bearer synthetic-owner-token"},
        )
        assert response.json() == {"state": "REVOKED", "in_flight": False}
    assert post(gateway).json()["reason_code"] == "CONSENT_REVOKED"
    assert (
        client.post(
            "/api/control/v1/approvals/approval_unknown/resolve",
            json={"resolution": "APPROVE"},
            headers={"Authorization": f"Bearer {issued.token.get_secret_value()}"},
        ).status_code
        == 401
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"resource_ids": ["*"]},
        {"resource_ids": ["resource_other"]},
        {"action": "email.send"},
        {"purpose": "answer_question"},
        {"expires_at": (NOW + timedelta(hours=2)).isoformat()},
        {"expires_at": NOW.isoformat()},
        {"expires_at": "2026-10-24T13:00:00"},
        {"recipient": "safe@example.test"},
        {"owner_id": "other-owner"},
    ],
)
def test_invalid_owner_grants_rejected(gateway, changes):
    _, task, _, client = gateway
    payload = {
        "action": "files.read",
        "purpose": SCOPE.purpose,
        "resource_ids": [PIN.resource_id],
        "expires_at": (NOW + timedelta(minutes=5)).isoformat(),
        **changes,
    }
    assert (
        client.post(
            f"/api/control/v1/tasks/{task.task_ref}/consents",
            json=payload,
            headers={"Authorization": "Bearer synthetic-owner-token"},
        ).status_code
        == 422
    )


def test_concurrent_authorization_reads_have_real_distinct_audits(gateway):
    grant(gateway)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: authorize(gateway), range(8)))
    assert all(result.decision == "ALLOW" for result in results)
    assert len({result.audit_event_ref for result in results}) == 8


def test_revocation_wins_before_authorization_snapshot(gateway):
    consent = grant(gateway)
    factory, task, _, _ = gateway
    revoked = Event()

    def revoke():
        with factory() as db:
            revoke_scoped_consent(
                db, owner=OWNER, task_ref=task.task_ref, consent_ref=consent.consent_ref, now=NOW
            )
        revoked.set()

    def read():
        assert revoked.wait(5)
        return authorize(gateway)

    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(read)
        pool.submit(revoke).result(5)
        assert future.result(5).reason_code == "CONSENT_REVOKED"


def test_catalog_unknown_changed_and_cross_owner_fail_closed(gateway):
    factory, task, issued, _ = gateway
    grant(gateway)
    for catalog in (
        ResourceCatalog(),
        ResourceCatalog(resources=(CatalogResource(**PIN.model_dump(), owner_id=OTHER.owner_id),)),
    ):
        with factory() as db:
            response = authorize_request(
                db, token=issued.token, request=request_for(task), catalog=catalog, now=NOW
            )
        assert response.reason_code == "RESOURCE_VERSION_CHANGED"
    with factory() as db, pytest.raises(ValueError, match="catalog"):
        create_trusted_task(
            db,
            owner=OTHER,
            scope=SCOPE,
            catalog=CATALOG,
            now=NOW,
            expires_at=NOW + timedelta(minutes=5),
        )


def test_no_partial_grant_union_and_no_global_consent_fallback(gateway):
    grant(gateway, action="tasks.list", resource_ids=[])
    assert authorize(gateway).reason_code == "APPROVAL_UNAVAILABLE"
    grant(gateway, action="files.list_authorized")
    assert authorize(gateway, action="files.list_authorized", arguments={}).decision == "ALLOW"
    assert authorize(gateway).reason_code == "APPROVAL_UNAVAILABLE"


def test_audit_failure_returns_no_allow_and_no_private_details(gateway, monkeypatch):
    grant(gateway)
    factory, task, issued, _ = gateway
    with factory() as db:

        def fail(*args, **kwargs):
            raise OperationalError(
                "PRIVATE_QUERY",
                {"token": issued.token.get_secret_value()},
                Exception("PRIVATE_PAYLOAD"),
            )

        monkeypatch.setattr(db, "flush", fail)
        with pytest.raises(AgentIdentityError) as error:
            authorize_request(
                db, token=issued.token, request=request_for(task), catalog=CATALOG, now=NOW
            )
    assert error.value.code == "GATEWAY_UNAVAILABLE"
    assert "PRIVATE" not in str(error.value)


def test_task_revocation_rejects_previous_authorization(gateway):
    grant(gateway)
    assert authorize(gateway).decision == "ALLOW"
    factory, task, _, _ = gateway
    with factory() as db:
        revoke_trusted_task(db, owner=OWNER, task_ref=task.task_ref, now=NOW)
    with pytest.raises(AgentIdentityError):
        authorize(gateway)


@pytest.fixture(scope="module")
def member_b_contract():
    path = Path(__file__).resolve().parents[3] / "backend/app/agent/gateway_protocol.py"
    spec = importlib.util.spec_from_file_location("member_b_wire_compatibility", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("has_consent", [False, True])
def test_actual_member_b_response_validator(gateway, member_b_contract, has_consent):
    if has_consent:
        grant(gateway)
    response = post(gateway).json()
    parsed = member_b_contract.ToolResponse.model_validate_json(json.dumps(response))
    assert parsed.execution_status.value == "NOT_EXECUTED"
    assert parsed.decision.value == ("ALLOW" if has_consent else "DENY")
    assert parsed.approval_ref is parsed.result is None


@pytest.mark.parametrize(
    "action,arguments",
    [
        ("files.read", {"resource_id": PIN.resource_id}),
        ("files.list_authorized", {}),
        ("tasks.list", {}),
        ("email.draft", {"recipient": "safe@example.test", "subject": "S", "body": "B"}),
        (
            "email.send",
            {
                "recipient": "safe@example.test",
                "subject": "S",
                "body": "B",
                "attachment_resource_ids": [],
            },
        ),
    ],
)
def test_actual_member_b_requests_roundtrip(gateway, member_b_contract, action, arguments):
    _, task, _, _ = gateway
    request = request_for(task, action=action, arguments=arguments)
    wire = member_b_contract.ToolRequest.model_validate_json(request.model_dump_json())
    assert ToolRequest.model_validate_json(wire.model_dump_json()) == request


def test_additive_migration_and_mysql_ddl_without_applying():
    revisions = {}
    for path in (Path(__file__).parents[1] / "migrations/versions").glob("*.py"):
        values = {
            n.targets[0].id: ast.literal_eval(n.value)
            for n in ast.parse(path.read_text()).body
            if isinstance(n, ast.Assign)
        }
        revisions[values["revision"]] = values["down_revision"]
    assert revisions == {
        "0001_initial": None,
        "0002_agent_identity": "0001_initial",
        "0003_scoped_consent": "0002_agent_identity",
        "0004_operation_ledger": "0003_scoped_consent",
        "0005_durable_approvals": "0004_operation_ledger",
        "0006_trusted_execution": "0005_durable_approvals",
        "0007_document_catalog": "0006_trusted_execution",
        "0008_secure_document_reading": "0007_document_catalog",
        "0009_mailpit_email": "0008_secure_document_reading",
        "0010_workflow_resume": "0009_mailpit_email",
        "0011_controlled_execution": "0010_workflow_resume",
        "0012_application_commands": "0011_controlled_execution",
        "0013_application_interfaces": "0012_application_commands",
    }
    ddl = str(CreateTable(ScopedConsent.__table__).compile(dialect=mysql.dialect()))
    assert "ascii_bin" in ddl and "DATETIME(6)" in ddl and "InnoDB" in ddl
    assert "fk_scoped_consent_task_owner" in ddl


def test_database_enforces_owner_pair_and_email_prohibition(gateway):
    consent = grant(gateway)
    factory, _, _, _ = gateway
    for field, value in (
        ("owner_id", OTHER.owner_id),
        ("action", "email.send"),
        ("recipient", "safe@example.test"),
    ):
        with factory() as db, pytest.raises(IntegrityError):
            with db.begin():
                setattr(db.get(ScopedConsent, consent.consent_ref), field, value)


@pytest.mark.parametrize(
    "content,status,code",
    [
        (b'{"request_id":"a","request_id":"b"}', 400, "DUPLICATE_JSON_FIELD"),
        (b'{"arguments":{"x":1,"x":2}}', 400, "DUPLICATE_JSON_FIELD"),
        (b"{broken", 400, "MALFORMED_JSON"),
        (b"\xff", 400, "MALFORMED_JSON"),
        (b'{"x":NaN}', 400, "MALFORMED_JSON"),
        (b'{"x":1e999}', 400, "MALFORMED_JSON"),
        (b"[" * 12 + b"0" + b"]" * 12, 422, "INVALID_REQUEST"),
        (b" " * (256 * 1024 + 1), 413, "PAYLOAD_TOO_LARGE"),
        (b"[]", 422, "INVALID_REQUEST"),
    ],
    ids=[
        "duplicate-top",
        "duplicate-nested",
        "malformed",
        "encoding",
        "nan",
        "infinity",
        "depth",
        "oversized-body",
        "not-object",
    ],
)
def test_raw_body_limits_and_json_privacy(gateway, content, status, code):
    _, _, issued, client = gateway
    response = client.post(
        "/api/gateway/v1/execute",
        content=content,
        headers={
            "Authorization": f"Bearer {issued.token.get_secret_value()}",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == status and response.json()["error_code"] == code
    assert response.json()["execution_uncertain"] is False
    assert response.json()["audit_event_ref"] is None


@pytest.mark.parametrize(
    "headers,status",
    [
        ({"Content-Type": "text/plain"}, 415),
        ({"Content-Encoding": "gzip"}, 415),
        ({"X-Oversized": "x" * 8192}, 413),
    ],
)
def test_header_limits(gateway, headers, status):
    _, task, issued, client = gateway
    response = client.post(
        "/api/gateway/v1/execute",
        content=request_for(task).model_dump_json(),
        headers={
            "Authorization": f"Bearer {issued.token.get_secret_value()}",
            "Content-Type": "application/json",
            **headers,
        },
    )
    assert response.status_code == status


def test_duplicate_authorization_is_rejected(gateway):
    _, task, issued, client = gateway
    token = f"Bearer {issued.token.get_secret_value()}"
    response = client.post(
        "/api/gateway/v1/execute",
        json=request_for(task).model_dump(mode="json"),
        headers=[("Authorization", token), ("Authorization", token)],
    )
    assert response.status_code == 401


def test_only_authorization_audit_changes_and_no_external_effects(gateway, monkeypatch, caplog):
    import builtins
    import logging
    import smtplib
    import subprocess

    factory, _, issued, _ = gateway

    def forbidden(*args, **kwargs):
        raise AssertionError("Filesystem, process, or SMTP operation during authorization")

    caplog.set_level(logging.DEBUG)
    for has_consent in (False, True):
        if has_consent:
            grant(gateway)
        with factory() as db:
            before = [
                (row.consent_ref, row.revoked_at, row.version)
                for row in db.scalars(select(ScopedConsent))
            ]
        with monkeypatch.context() as guards:
            guards.setattr(builtins, "open", forbidden)
            guards.setattr(Path, "open", forbidden)
            guards.setattr(smtplib, "SMTP", forbidden)
            guards.setattr(smtplib, "SMTP_SSL", forbidden)
            guards.setattr(subprocess, "Popen", forbidden)
            response = post(gateway)
        assert response.status_code == 200 and response.json()["execution_status"] == "NOT_EXECUTED"
        with factory() as db:
            after = [
                (row.consent_ref, row.revoked_at, row.version)
                for row in db.scalars(select(ScopedConsent))
            ]
        assert before == after
    assert issued.token.get_secret_value() not in caplog.text


def test_revocation_and_authorization_contend_on_same_transaction(gateway, monkeypatch):
    import app.services.scoped_consent as service

    consent = grant(gateway)
    factory, task, _, _ = gateway
    locked, reader_started, release = Event(), Event(), Event()
    original = service._owned_task

    def hold_revoke_lock(*args, **kwargs):
        result = original(*args, **kwargs)
        locked.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(service, "_owned_task", hold_revoke_lock)

    def revoke():
        with factory() as db:
            revoke_scoped_consent(
                db, owner=OWNER, task_ref=task.task_ref, consent_ref=consent.consent_ref, now=NOW
            )

    def read():
        reader_started.set()
        return authorize(gateway)

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(revoke)
        assert locked.wait(5)
        reader = pool.submit(read)
        assert reader_started.wait(5)
        release.set()
        writer.result(5)
        assert reader.result(5).reason_code == "CONSENT_REVOKED"


@pytest.mark.parametrize(
    "field,value,reason",
    [
        (
            "resource_versions",
            [{"resource_id": "*", "version_ref": "v", "classification": "SHAREABLE"}],
            "CONSENT_AMBIGUOUS",
        ),
        ("resource_versions", [PIN.model_dump(), PIN.model_dump()], "CONSENT_AMBIGUOUS"),
        (
            "resource_versions",
            [{**PIN.model_dump(), "version_ref": "changed_version"}],
            "RESOURCE_VERSION_CHANGED",
        ),
        ("purpose", "answer_question", "APPROVAL_UNAVAILABLE"),
        ("action", "tasks.list", "APPROVAL_UNAVAILABLE"),
    ],
)
def test_persisted_consent_mismatch_or_corruption_fails_closed(gateway, field, value, reason):
    consent = grant(gateway)
    factory, _, _, _ = gateway
    with factory() as db, db.begin():
        setattr(db.get(ScopedConsent, consent.consent_ref), field, value)
    assert authorize(gateway).reason_code == reason
