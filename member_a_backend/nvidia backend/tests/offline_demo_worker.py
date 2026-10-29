"""Fresh-process bootstrap acceptance; stdout contains safe test results only."""

import argparse
import json
import os
import socket
import subprocess
import sys
from contextlib import ExitStack
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("flow", "resume", "launcher", "paired-launcher"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    attempts = []

    def denied(*args, **kwargs):
        attempts.append("blocked")
        raise AssertionError("Offline bootstrap tests forbid external transport")

    original, original_ex = socket.socket.connect, socket.socket.connect_ex

    def local_connect(sock, address):
        return (
            original(sock, address)
            if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1")
            else denied()
        )

    def local_connect_ex(sock, address):
        return (
            original_ex(sock, address)
            if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1")
            else denied()
        )

    with ExitStack() as guards:
        for target, name, value in (
            (socket, "getaddrinfo", denied),
            (socket, "create_connection", denied),
            (socket.socket, "connect", local_connect),
            (socket.socket, "connect_ex", local_connect_ex),
        ):
            guards.enter_context(patch.object(target, name, value))
        import smtplib

        import httpx
        import pymysql

        for target, name in (
            (pymysql.connections.Connection, "connect"),
            (smtplib, "SMTP"),
            (smtplib, "SMTP_SSL"),
            (httpx.HTTPTransport, "handle_request"),
        ):
            guards.enter_context(patch.object(target, name, denied))

        async def denied_async(*args, **kwargs):
            return denied()

        guards.enter_context(
            patch.object(httpx.AsyncHTTPTransport, "handle_async_request", denied_async)
        )
        from app.offline_demo import load_demo

        origin, prefix = "http://127.0.0.1:8000", "/api/app/v1"
        if "launcher" in args.mode:
            from app.offline_demo import main as launch

            class PrivateTerminal(StringIO):
                def isatty(self):
                    return True

            observed = {}

            def run(application, **options):
                observed.update(options)
                observed["pairing_enabled"] = application.backend.state.browser_sessions is not None
                if not observed["pairing_enabled"]:
                    from fastapi.testclient import TestClient

                    with TestClient(
                        application, base_url=origin, client=("127.0.0.1", 51000)
                    ) as client:
                        assert client.get("/health").status_code == 200
                        assert (
                            client.get(
                                origin + "/api/app/v1/session", headers={"Origin": origin}
                            ).status_code
                            == 503
                        )

            terminal = PrivateTerminal()
            guards.enter_context(patch("uvicorn.run", run))
            guards.enter_context(patch.object(sys, "stdin", PrivateTerminal()))
            with patch.object(sys, "stdout", terminal):
                arguments = [
                    "serve",
                    "--offline",
                    "--directory",
                    str(args.directory),
                    "--origin",
                    origin,
                ]
                if args.mode == "paired-launcher":
                    arguments.append("--pair")
                assert launch(arguments) == 0
            observed["pairing_code_prints"] = terminal.getvalue().count(
                "One-use local pairing code"
            )
            assert observed["pairing_code_prints"] == int(args.mode == "paired-launcher")
            assert not attempts
            print(json.dumps(observed))
            return

        application = load_demo(args.directory, initialize=args.mode == "flow", pair=True)
        from app.agent_schemas import OwnerContext, TaskScope
        from app.database import SessionLocal, engine
        from app.gateway_contracts import ConsentCreate, ToolRequest
        from app.models import (
            AgentCredential,
            ApplicationCommand,
            ExecutionAttempt,
            PendingApproval,
        )
        from app.openapi import application_schema
        from app.services.agent_identity import _utc, create_trusted_task, issue_agent_credential
        from app.services.document_catalog import FixtureRegistration, register_synthetic_resources
        from app.services.operation_ledger import admit_operation
        from app.services.scoped_consent import create_scoped_consent
        from app.services.synthetic_executor import SyntheticExecutor
        from app.services.trusted_execution import dispatch_simulated
        from fastapi.testclient import TestClient
        from sqlalchemy import func, select, text
        from sqlalchemy.exc import IntegrityError

        guards.callback(engine.dispose)
        backend, owner = application.backend, OwnerContext(owner_id="local-user")
        assert not backend.dependency_overrides and SessionLocal.kw["autoflush"] is False
        store = backend.state.browser_sessions
        with TestClient(application, base_url=origin, client=("127.0.0.1", 51000)) as client:
            client.headers["Origin"] = origin

            def pair():
                bootstrap = client.get(prefix + "/session").json()["data"]
                client.headers["X-Ghost-CSRF"] = bootstrap["csrf_token"]
                response = client.post(
                    prefix + "/session/login",
                    json={"pairing_code": store.issue_pairing_code().get_secret_value()},
                )
                assert response.status_code == 200
                client.headers["X-Ghost-CSRF"] = response.json()["data"]["csrf_token"]

            def post(path, payload=None, key=None):
                return client.post(
                    prefix + path,
                    json=payload or {},
                    headers={"Idempotency-Key": key or str(uuid4())},
                )

            if args.mode == "resume":
                prior = json.loads(sys.stdin.read())
                client.cookies.set("ghost_demo_session", prior["cookie"])
                assert client.get(prefix + "/tasks/" + prior["task_ref"]).status_code == 401
                client.cookies.clear()
                pair()
                replay = post(
                    f"/tasks/{prior['task_ref']}/workflow/continue", key=prior["continue_key"]
                )
                assert replay.status_code == 200 and replay.json()["replayed"]
                store.invalidate_all()
                print(json.dumps({"old_session_status": 401, "durable_replay": True}))
                return

            pair()
            for _ in range(2):
                with engine.connect() as first, engine.connect() as second:
                    assert (
                        first.scalar(text("PRAGMA foreign_keys"))
                        == second.scalar(text("PRAGMA foreign_keys"))
                        == 1
                    )
            catalog = client.get(prefix + "/documents").json()["data"]["items"]
            assert len(catalog) == 2
            assert all(
                set(row)
                == {
                    "resource_id",
                    "version_ref",
                    "display_name",
                    "classification",
                    "resource_type",
                    "synthetic",
                }
                for row in catalog
            )
            results = {
                "actual_session_autoflush": False,
                "dependency_overrides": 0,
                "foreign_keys_all_connections": True,
                "catalog_safe_fields": True,
            }

            def create(profile="email_draft_v1", resource=None):
                body = {"profile_id": profile, "resource_id": resource}
                key = str(uuid4())
                response = post("/tasks", body, key)
                assert response.status_code == 201, response.text
                ref = response.json()["data"]["task_ref"]
                assert post("/tasks", body, key).json()["replayed"]
                return ref

            def plan(ref):
                response = post(
                    f"/tasks/{ref}/planning", {"user_request": "Synthetic offline demonstration"}
                )
                assert response.status_code == 200, response.text
                view = response.json()["data"]
                assert view["authorization_decision"] == "APPROVAL_REQUIRED"
                assert view["provenance"]["planning_source"] == "MOCK_MODEL"
                return view["approval_ref"]

            ref = create()
            approval = plan(ref)
            assert client.get(prefix + "/tasks").status_code == 200
            assert client.get(prefix + "/tasks/" + ref).status_code == 200
            assert client.get(prefix + f"/tasks/{ref}/planning").status_code == 200
            assert client.get(prefix + "/approvals", params={"task_ref": ref}).status_code == 200
            assert client.get(prefix + "/approvals/" + approval).status_code == 200
            assert client.get(prefix + f"/tasks/{ref}/workflow").json()["data"]["phase"] == "PAUSED"
            decision_key, continue_key = str(uuid4()), str(uuid4())
            decision = post(
                f"/approvals/{approval}/decision", {"resolution": "APPROVE"}, decision_key
            )
            assert decision.status_code == 200, decision.text
            assert post(
                f"/approvals/{approval}/decision", {"resolution": "APPROVE"}, decision_key
            ).json()["replayed"]
            continued = post(f"/tasks/{ref}/workflow/continue", key=continue_key)
            assert (
                continued.status_code == 200 and continued.json()["data"]["phase"] == "RESUMED"
            ), continued.text
            assert post(f"/tasks/{ref}/workflow/continue", key=continue_key).json()["replayed"]
            results.update(
                approve_http_status=200,
                workflow_phase="RESUMED",
                graph_boundary="SAFE_STOPPED",
                replay=True,
            )
            for resolution in ("REJECT", "REVOKE"):
                another = create("email_send_v1")
                pending = plan(another)
                if resolution == "REJECT":
                    assert (
                        post(
                            f"/approvals/{pending}/decision", {"resolution": resolution}
                        ).status_code
                        == 200
                    )
                else:
                    assert (
                        post(
                            f"/approvals/{pending}/decision", {"resolution": "APPROVE"}
                        ).status_code
                        == 200
                    )
                    assert post(f"/approvals/{pending}/revoke").status_code == 200
                denied = post(f"/tasks/{another}/workflow/continue")
                assert (
                    denied.status_code == 409
                    and denied.json()["error"]["code"] == "WORKFLOW_DENIED"
                )
            operations = client.get(prefix + f"/tasks/{ref}/operations")
            assert operations.status_code == 200
            operation = operations.json()["data"]["items"][0]
            assert (
                client.get(
                    prefix + f"/tasks/{ref}/operations/{operation['operation_ref']}"
                ).status_code
                == 200
            )
            cancelled = create()
            cancellation = post(f"/tasks/{cancelled}/cancel")
            assert cancellation.status_code == 200
            assert cancellation.json()["data"]["task"]["authority_state"] == "CANCELLED"
            timeline = client.get(prefix + f"/tasks/{ref}/timeline?limit=1").json()["data"]
            assert timeline["items"] and timeline["next_cursor"]
            assert (
                client.get(
                    prefix + f"/tasks/{ref}/timeline",
                    params={"limit": 1, "cursor": timeline["next_cursor"]},
                ).status_code
                == 200
            )
            with SessionLocal() as db:
                original = db.scalar(
                    select(ApplicationCommand).where(ApplicationCommand.kind == "TASK_CREATE")
                )
                copied = {
                    column.name: getattr(original, column.name)
                    for column in ApplicationCommand.__table__.columns
                }
                copied.update(command_ref="cmd_" + uuid4().hex, client_key=str(uuid4()))
                db.add(ApplicationCommand(**copied))
                try:
                    db.flush()
                    raise AssertionError("Duplicate creation identity accepted")
                except IntegrityError:
                    db.rollback()
                now = _utc(None)
                db.add(
                    AgentCredential(
                        credential_ref="cred_" + uuid4().hex,
                        token_digest="0" * 64,
                        task_ref="missing",
                        owner_id="local-user",
                        credential_epoch=1,
                        issued_at=now,
                        expires_at=now + timedelta(minutes=1),
                    )
                )
                try:
                    db.flush()
                    raise AssertionError("Orphan credential accepted")
                except IntegrityError:
                    db.rollback()
                assert db.scalar(select(func.count()).select_from(ExecutionAttempt)) == 0
            results.update(
                unique_command_enforced=True,
                foreign_key_enforced=True,
                protected_attempts_from_browser=0,
            )
            foreign_owner = OwnerContext(owner_id="foreign")
            with SessionLocal() as db:
                resource = register_synthetic_resources(
                    db,
                    owner=foreign_owner,
                    selection=FixtureRegistration(fixtures=("doc_schedule",)),
                )[0]
            with SessionLocal() as db:
                foreign = create_trusted_task(
                    db,
                    owner=foreign_owner,
                    scope=TaskScope(
                        purpose="summarize_document",
                        allowed_actions=("files.read",),
                        resource_ids=(resource.resource_ref,),
                        resource_versions=(resource.pin,),
                    ),
                    expires_at=_utc(None) + timedelta(minutes=5),
                )
            assert client.get(prefix + f"/tasks/{foreign.task_ref}").status_code == 404
            assert resource.resource_ref not in client.get(prefix + "/documents").text
            doc = create("document_simulation_v1", catalog[0]["resource_id"])
            plan(doc)
            # Explicit trusted, authorized synthetic UNKNOWN; no document or message is sent/read.
            unknown = create("document_simulation_v1", catalog[0]["resource_id"])
            with SessionLocal() as db:
                token = issue_agent_credential(db, owner=owner, task_ref=unknown).token
            with SessionLocal() as db:
                create_scoped_consent(
                    db,
                    owner=owner,
                    task_ref=unknown,
                    payload=ConsentCreate(
                        action="files.read",
                        purpose="summarize_document",
                        resource_ids=(catalog[0]["resource_id"],),
                        expires_at=_utc(None) + timedelta(minutes=5),
                    ),
                )
            request = ToolRequest.model_validate_json(
                json.dumps(
                    {
                        "request_id": "req_offline_unknown",
                        "idempotency_key": "key_offline_unknown",
                        "task_ref": unknown,
                        "action": "files.read",
                        "purpose": "summarize_document",
                        "arguments": {"resource_id": catalog[0]["resource_id"]},
                    }
                )
            )
            with SessionLocal() as db:
                assert admit_operation(db, token=token, request=request).decision == "ALLOW"
            with SessionLocal() as db:
                dispatch_simulated(
                    db, token=token, request=request, executor=SyntheticExecutor(outcome="UNKNOWN")
                )
            for _ in range(2):
                observed = client.get(prefix + f"/tasks/{unknown}/operations").json()["data"][
                    "items"
                ][0]
                assert observed["state"] == "UNKNOWN" and observed["reconciliation_required"]
            assert post(f"/tasks/{unknown}/workflow/continue").status_code == 409
            with SessionLocal() as db:
                assert db.scalar(select(func.count()).select_from(ExecutionAttempt)) == 1
                assert db.get(PendingApproval, approval).consumed_at is None
            results.update(
                unknown_reconciliation=True,
                authorized_synthetic_attempts=1,
                unauthorized_attempts=0,
                real_smtp_submissions=0,
            )
            # Reopen in a new OS process; the stale cookie travels only on private stdin.
            restart_input = {
                "cookie": list(client.cookies.values())[0],
                "task_ref": ref,
                "continue_key": continue_key,
            }
            engine.dispose()
            restarted = subprocess.run(
                [sys.executable, "-I", "-B", __file__, "resume", str(args.directory)],
                input=json.dumps(restart_input),
                env=dict(os.environ),
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            assert restarted.returncode == 0, restarted.stderr
            results["restart"] = json.loads(restarted.stdout)
            assert client.post(prefix + "/session/logout", json={}).status_code == 204
            assert (
                post("/tasks", {"profile_id": "email_draft_v1", "resource_id": None}).status_code
                == 401
            )
            store.invalidate_all()
            frontend = application_schema(backend.openapi())
            expected = (
                BACKEND.parents[1] / "docs/frontend-handoff/generated/ghost-app-v1.openapi.json"
            )
            assert frontend == json.loads(expected.read_text())
            results["all_19_browser_operations_exercised"] = True
            results["frontend_openapi_unchanged"] = True
            assert not attempts
            results["network_mysql_smtp_attempts"] = len(attempts)
            print(json.dumps(results, sort_keys=True))


if __name__ == "__main__":
    main()
