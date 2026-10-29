"""Actual-route contracts and public ingress, using synthetic offline ASGI only."""

import json
import os
import re
import subprocess
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.agent_schemas import OwnerContext
from app.config import get_settings
from app.main import app, public_app
from app.models import ExecutionAttempt, GatewayOperation, WorkflowCheckpoint
from app.openapi import application_schema, inventory, register
from app.services.agent_identity import issue_agent_credential
from fastapi.openapi.models import OpenAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from tests.test_application_interfaces import continue_task, decide, pending, post
from tests.test_application_interfaces import register as seed
from tests.test_application_tasks import ORIGIN, TASKS, create, error, plan, task
from tests.test_application_tasks import demo as demo
from tests.test_approvals import approved_task as approved_task
from tests.test_scoped_consent import NOW, request_for
from tests.test_scoped_consent import gateway as gateway

ROOT = Path(__file__).resolve().parents[3]
FRONTEND = ROOT / "docs/frontend-handoff/generated/ghost-app-v1.openapi.json"
SCHEMA = "/api/app/v1/openapi.json"


def validate_wire(tmp_path, schema, cases=()):
    spec, samples = tmp_path / "openapi.json", tmp_path / "cases.json"
    spec.write_text(json.dumps(schema), encoding="utf-8")
    samples.write_text(json.dumps(cases), encoding="utf-8")
    env = {
        key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP") if key in os.environ
    }
    result = subprocess.run(
        [
            str(ROOT / ".venv/Scripts/python.exe"),
            "-I",
            "-B",
            str(ROOT / "tools/validate_openapi.py"),
            str(spec),
            str(samples),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def record(cases, response, path, method="get", payload=None):
    assert response.status_code in (200, 201, 204, 400, 401, 403, 404, 409, 422, 429, 500, 503)
    cases.append(
        {
            "path": path,
            "method": method,
            "status": response.status_code,
            "body": response.json() if response.status_code != 204 else None,
            "request": payload if response.status_code < 400 else None,
        }
    )
    return response


def test_complete_schema_inventory_and_stable_identifiers(tmp_path):
    schema = app.openapi()
    OpenAPI.model_validate(schema)
    rows = inventory(app)
    pairs = [(method, row["path"]) for row in rows for method in row["methods"]]
    assert len(rows) == 44 and len(pairs) == 48 and len(set(pairs)) == 48
    assert sum(row["include_in_schema"] for row in rows) == 39
    assert {r["path"] for r in rows if not r["include_in_schema"]} == {
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
        "/openapi.json",
        SCHEMA,
    }
    baseline = json.loads(
        (ROOT / "docs/integration/step44d_option_a_logs/openapi.json").read_text()
    )
    assert set(schema["paths"]) == set(baseline["paths"])
    for path, item in baseline["paths"].items():
        for method, operation in item.items():
            current = schema["paths"][path][method]
            assert current["operationId"] == operation["operationId"]
            assert set(current["responses"]) >= set(operation["responses"])
    for name in (
        "ToolResponse",
        "OperationStatus",
        "WorkflowSnapshot",
        "ControlledExecutionResult",
    ):
        assert schema["components"]["schemas"][name] == baseline["components"]["schemas"][name]
    assert validate_wire(tmp_path, schema)["operations"] == 39


def test_frontend_artifact_security_and_pagination(tmp_path):
    schema = application_schema(app.openapi())
    assert schema == json.loads(FRONTEND.read_text())
    assert validate_wire(tmp_path, schema)["operations"] == 20
    assert set(schema["components"]["securitySchemes"]) == {"AppSession", "CsrfHeader"}
    assert not {"servers", "webhooks", "security"} & set(schema)
    private = {
        "owner_id",
        "owner_ref",
        "storage_reference",
        "content_digest",
        "checkpoint_path",
        "checkpoint_id",
        "thread_id",
        "resume_ref",
        "resume_hint",
        "dispatch_nonce",
        "result_json",
        "database_url",
        "api_bearer_token",
    }
    for definition in schema["components"]["schemas"].values():
        assert not private & set(definition.get("properties", {}))
    assert set(schema["components"]["schemas"]["DocumentMetadata"]["properties"]) == {
        "resource_id",
        "version_ref",
        "display_name",
        "classification",
        "resource_type",
        "synthetic",
    }
    pages = []
    for path, item in schema["paths"].items():
        assert path == "/health" or path.startswith("/api/app/v1/")
        for method, operation in item.items():
            expected = (
                []
                if path in ("/health", "/api/app/v1/session")
                else [{"AppSession": [], **({"CsrfHeader": []} if method == "post" else {})}]
            )
            assert operation["security"] == expected
            if path != "/health":
                assert (
                    "HttpOnly" in operation["description"] and "Origin" in operation["description"]
                )
            if (
                path in (TASKS, "/api/app/v1/documents", TASKS + "/{task_ref}/timeline")
                and method == "get"
            ):
                pages.append(
                    {p["name"]: p["schema"] for p in operation["parameters"] if p["in"] == "query"}
                )
    assert len(pages) == 3 and pages[0] == pages[1] == pages[2]


def test_schema_component_collision_rejected():
    with pytest.raises(ValueError, match="Conflicting OpenAPI component"):
        register({"Duplicate": {"type": "string"}}, "Duplicate", {"type": "integer"})


def test_all_browser_success_shapes_match_emitted_schemas(demo, tmp_path):
    client, factory, store, _ = demo
    cases = []
    client.cookies.clear()
    anonymous = record(cases, client.get("/api/app/v1/session"), "/api/app/v1/session")
    client.headers["X-Ghost-CSRF"] = anonymous.json()["data"]["csrf_token"]
    payload = {"pairing_code": store.issue_pairing_code().get_secret_value()}
    paired = record(
        cases,
        client.post("/api/app/v1/session/login", json=payload),
        "/api/app/v1/session/login",
        "post",
        payload,
    )
    client.headers["X-Ghost-CSRF"] = paired.json()["data"]["csrf_token"]
    record(cases, client.get("/health"), "/health")
    seed(factory)
    record(cases, client.get("/api/app/v1/documents?limit=1"), "/api/app/v1/documents")
    made = record(
        cases, create(client), TASKS, "post", {"profile_id": "email_draft_v1", "resource_id": None}
    )
    ref = made.json()["data"]["task_ref"]
    record(cases, client.get(TASKS), TASKS)
    record(cases, client.get(f"{TASKS}/{ref}"), TASKS + "/{task_ref}")
    planned = record(
        cases,
        plan(client, ref),
        TASKS + "/{task_ref}/planning",
        "post",
        {"user_request": "Prepare the synthetic task"},
    )
    record(cases, client.get(f"{TASKS}/{ref}/planning"), TASKS + "/{task_ref}/planning")
    approval = planned.json()["data"]["approval_ref"]
    operation = planned.json()["data"]["operation_ref"]
    record(
        cases,
        client.get("/api/app/v1/approvals", params={"task_ref": ref}),
        "/api/app/v1/approvals",
    )
    record(
        cases,
        client.get(f"/api/app/v1/approvals/{approval}"),
        "/api/app/v1/approvals/{approval_ref}",
    )
    record(
        cases,
        decide(client, approval),
        "/api/app/v1/approvals/{approval_ref}/decision",
        "post",
        {"resolution": "APPROVE"},
    )
    record(cases, client.get(f"{TASKS}/{ref}/workflow"), TASKS + "/{task_ref}/workflow")
    record(cases, continue_task(client, ref), TASKS + "/{task_ref}/workflow/continue", "post", {})
    record(cases, client.get(f"{TASKS}/{ref}/operations"), TASKS + "/{task_ref}/operations")
    record(
        cases,
        client.get(f"{TASKS}/{ref}/operations/{operation}"),
        TASKS + "/{task_ref}/operations/{operation_ref}",
    )
    record(cases, client.get(f"{TASKS}/{ref}/timeline?limit=1"), TASKS + "/{task_ref}/timeline")
    record(
        cases,
        post(client, f"/api/app/v1/approvals/{approval}/revoke"),
        "/api/app/v1/approvals/{approval_ref}/revoke",
        "post",
        {},
    )
    record(cases, post(client, f"{TASKS}/{ref}/cancel"), TASKS + "/{task_ref}/cancel", "post", {})
    record(
        cases,
        client.post("/api/app/v1/session/logout", json={}),
        "/api/app/v1/session/logout",
        "post",
        {},
    )
    assert len({(case["method"], case["path"]) for case in cases}) == 20
    assert all(case["status"] < 400 for case in cases)
    assert validate_wire(tmp_path, application_schema(app.openapi()), cases)["cases"] == 20
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ExecutionAttempt)) == 0
        assert db.scalar(select(WorkflowCheckpoint)).phase == "RESUMED"
    for case in cases:
        if isinstance(case["body"], dict) and "provenance" in case["body"].get("data", {}):
            assert case["body"]["data"]["provenance"]["environment"] == "OFFLINE_DEMO"


def test_public_surface_denies_every_private_route_even_with_valid_credentials(demo, monkeypatch):
    client, factory, _, _ = demo
    monkeypatch.setenv("API_BEARER_TOKEN", "schema-owner-only")
    get_settings.cache_clear()
    ref = task(client)
    with factory() as db:
        token = issue_agent_credential(
            db,
            owner=OwnerContext(owner_id="local-user"),
            task_ref=ref,
        ).token.get_secret_value()
    try:
        with TestClient(public_app, base_url=ORIGIN, client=("127.0.0.1", 51000)) as edge:
            for row in inventory(app):
                if row["path"] == "/health" or row["path"].startswith("/api/app/v1/"):
                    continue
                path = re.sub(r"{[^}]+}", "missing", row["path"])
                for bearer in ("schema-owner-only", token):
                    for method in row["methods"]:
                        result = edge.request(
                            method,
                            path,
                            headers={"Authorization": "Bearer " + bearer},
                            json={} if method == "POST" else None,
                        )
                        assert result.status_code == 404
            assert edge.get("/health").json() == {"status": "ok"}
        # Private listener still enforces its original owner authentication and works.
        assert (
            client.get(
                "/api/audit-events", headers={"Authorization": "Bearer schema-owner-only"}
            ).status_code
            == 200
        )
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(ExecutionAttempt)) == 0
            assert db.scalar(select(func.count()).select_from(GatewayOperation)) == 0
    finally:
        get_settings.cache_clear()


def test_schema_resource_no_login_and_ingress_rejections(demo):
    client, _, _, _ = demo
    client.cookies.clear()
    result = client.get(SCHEMA)
    assert result.status_code == 200 and result.json() == json.loads(FRONTEND.read_text())
    assert "set-cookie" not in result.headers and result.headers["cache-control"] == "no-store"
    error(client.get(SCHEMA + "?owner_id=foreign"), 422, "INVALID_REQUEST")
    error(client.get(SCHEMA, headers={"Origin": "https://foreign.test"}), 403, "ORIGIN_FORBIDDEN")
    error(
        client.get(SCHEMA, headers={"Authorization": "Bearer forged"}),
        403,
        "CREDENTIAL_HEADER_FORBIDDEN",
    )
    app.state.browser_sessions = None
    error(client.get(SCHEMA), 503, "AUTH_NOT_CONFIGURED")


def test_browser_error_schemas_and_extra_enum_rules(demo, tmp_path, monkeypatch):
    from app.services import application_interfaces

    client, _, store, runtime = demo
    ref, approval = pending(demo)
    cases = []
    path = "/api/app/v1/approvals/{approval_ref}/decision"
    malformed = client.post(
        f"/api/app/v1/approvals/{approval}/decision",
        content=b"{",
        headers={"Content-Type": "application/json", "Idempotency-Key": str(uuid4())},
    )
    record(cases, malformed, path, "post")
    assert malformed.status_code == 400
    record(cases, decide(client, approval, "INVALID"), path, "post")
    cases[-1].update(request={"resolution": "INVALID"}, request_valid=False)
    invalid_profile = {"profile_id": "email_draft_v1", "resource_id": "resource_synthetic"}
    record(cases, create(client, resource="resource_synthetic"), TASKS, "post")
    cases[-1].update(request=invalid_profile, request_valid=False)
    record(
        cases,
        post(
            client,
            f"/api/app/v1/approvals/{approval}/decision",
            {"resolution": "APPROVE", "owner_id": "foreign"},
        ),
        path,
        "post",
    )
    csrf = client.headers.pop("X-Ghost-CSRF")
    record(cases, decide(client, approval), path, "post")
    client.headers["X-Ghost-CSRF"] = csrf
    key = str(uuid4())
    record(cases, decide(client, approval, key=key), path, "post", {"resolution": "APPROVE"})
    record(cases, decide(client, approval, "REJECT", key=key), path, "post")
    runtime.reserve("cmd_schema_busy", "task_else")
    try:
        busy = record(
            cases, continue_task(client, ref), TASKS + "/{task_ref}/workflow/continue", "post"
        )
        assert busy.status_code == 429
    finally:
        runtime.release()
    record(cases, client.get(f"{TASKS}/missing"), TASKS + "/{task_ref}")

    def failure(*args, **kwargs):
        raise RuntimeError("private-path-token-marker")

    monkeypatch.setattr(application_interfaces, "documents", failure)
    failed = record(cases, client.get("/api/app/v1/documents"), "/api/app/v1/documents")
    assert failed.status_code == 500 and "private-path-token-marker" not in failed.text
    monkeypatch.setattr(application_interfaces, "mutate", failure)
    failed_post = record(cases, decide(client, approval), path, "post")
    assert failed_post.status_code == 500
    assert failed_post.json()["error"]["command_uncertain"]
    assert failed_post.json()["error"]["reconciliation_required"]
    future = store._clock() + timedelta(seconds=901)
    monkeypatch.setattr(store, "_clock", lambda: future)
    expired = record(cases, client.get(f"{TASKS}/{ref}"), TASKS + "/{task_ref}")
    assert expired.json()["error"]["code"] == "SESSION_EXPIRED"
    client.cookies.clear()
    record(cases, client.get(f"{TASKS}/{ref}"), TASKS + "/{task_ref}")
    monkeypatch.setattr(app.state, "browser_sessions", None)
    record(cases, client.get(f"{TASKS}/{ref}"), TASKS + "/{task_ref}")
    assert validate_wire(tmp_path, application_schema(app.openapi()), cases)["cases"] == len(cases)


def test_all_trusted_routes_wire_schemas(approved_task, tmp_path, monkeypatch):
    factory, owned, issued, client = approved_task
    monkeypatch.setattr("app.services.workflow_resume._utc", lambda now: now or NOW)
    owner = {"Authorization": "Bearer synthetic-owner-token"}
    agent = {"Authorization": "Bearer " + issued.token.get_secret_value()}
    cases = []

    def call(method, path, template=None, payload=None, headers=owner, expected=200):
        result = client.request(method, path, headers=headers, json=payload)
        assert result.status_code == expected, result.text
        return record(cases, result, template or path, method.lower(), payload)

    call("GET", "/health")
    call("POST", "/api/consents", payload={"scope": "tools:execute", "granted": True})
    call("POST", "/api/tool-permissions", payload={"tool_name": "echo", "allowed": True})
    call(
        "POST",
        "/api/tools/execute",
        payload={"tool_name": "unknown", "arguments": {}},
        expected=404,
    )
    call("GET", "/api/audit-events")
    consent_path = f"/api/control/v1/tasks/{owned.task_ref}/consents"
    granted = call(
        "POST",
        consent_path,
        "/api/control/v1/tasks/{task_ref}/consents",
        {
            "action": "tasks.list",
            "purpose": "summarize_document",
            "resource_ids": [],
            "expires_at": (NOW + timedelta(minutes=5)).isoformat(),
        },
        expected=201,
    ).json()
    assert granted["expires_at"] == (NOW + timedelta(minutes=5)).isoformat()
    consent = granted["consent_ref"]
    call(
        "POST",
        consent_path + f"/{consent}/revoke",
        "/api/control/v1/tasks/{task_ref}/consents/{consent_ref}/revoke",
        {},
    )
    request = request_for(owned).model_dump(mode="json")
    admission = call("POST", "/api/gateway/v1/execute", payload=request, headers=agent).json()
    mismatched = {**request, "arguments": {}}
    call("POST", "/api/gateway/v1/execute", payload=mismatched, headers=agent, expected=422)
    cases[-1].update(request=mismatched, request_valid=False)
    assert admission["decision"] == "APPROVAL_REQUIRED" and admission["result"] is None
    status = f"/api/gateway/v1/operations/{request['request_id']}"
    call("GET", status, "/api/gateway/v1/operations/{request_id}", headers=agent)
    call(
        "POST",
        status + "/resume",
        "/api/gateway/v1/operations/{request_id}/resume",
        {"resume_ref": "synthetic-only-hint"},
        headers=agent,
        expected=403,
    )
    call("GET", "/api/control/v1/approvals?task_ref=" + owned.task_ref, "/api/control/v1/approvals")
    approval = "/api/control/v1/approvals/" + admission["approval_ref"]
    call("GET", approval, "/api/control/v1/approvals/{approval_ref}")
    workflow = "/api/control/v1/workflow-checkpoints"
    prepared = call(
        "POST",
        workflow,
        payload={
            "task_ref": owned.task_ref,
            "approval_ref": admission["approval_ref"],
            "request_id": request["request_id"],
            "idempotency_key": request["idempotency_key"],
        },
    ).json()
    binding = workflow + "/" + prepared["binding_ref"]
    checkpoint = {"checkpoint_id": str(uuid4())}
    call("POST", binding + "/pause", workflow + "/{binding_ref}/pause", checkpoint)
    call(
        "POST",
        approval + "/resolve",
        "/api/control/v1/approvals/{approval_ref}/resolve",
        {"resolution": "APPROVE"},
    )
    snapshot = call("GET", binding, workflow + "/{binding_ref}").json()
    identity = {
        key: snapshot[key]
        for key in (
            "task_ref",
            "approval_ref",
            "request_id",
            "idempotency_key",
            "workflow_version",
            "checkpoint_id",
            "operation_ref",
            "thread_id",
        )
    }
    identity["expected_authorization_version"] = snapshot["authorization_version"]
    for command in ("admit", "claim", "complete"):
        call("POST", binding + "/" + command, workflow + "/{binding_ref}/" + command, identity)
    call("POST", approval + "/revoke", "/api/control/v1/approvals/{approval_ref}/revoke", {})
    assert len({(case["method"], case["path"]) for case in cases}) == 20
    # All original operations are observed; protected resume remains disabled, not executed.
    assert validate_wire(tmp_path, app.openapi(), cases)["cases"] == len(cases)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ExecutionAttempt)) == 0


def test_legacy_result_schema_and_original_coercion(client, auth, tmp_path):
    cases = []
    granted = client.post(
        "/api/consents",
        headers=auth,
        json={
            "scope": "tools:execute",
            "granted": "true",
            "extra": "ignored-by-existing-model",
        },
    )
    assert granted.status_code == 200
    client.post("/api/tool-permissions", headers=auth, json={"tool_name": "echo", "allowed": True})
    payload = {"tool_name": "echo", "arguments": {"message": "Synthetic only"}}
    result = client.post("/api/tools/execute", headers=auth, json=payload)
    assert result.json() == {"result": {"message": "Synthetic only"}}
    record(cases, result, "/api/tools/execute", "post", payload)
    assert validate_wire(tmp_path, app.openapi(), cases)["cases"] == 1
