"""Private test process: actual Member A app, SQLite, ASGI only; never a server.

Separate interpreter prevents Member A/B's identically named app packages colliding.
Credentials cross captured anonymous pipes only, never files or test diagnostics.
"""

import asyncio
import json
import os
import secrets
import smtplib
import socket
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[3] / "member_a_backend" / "nvidia backend"
    sys.path.insert(0, str(root))
    os.environ["DATABASE_URL"] = "sqlite:///unused.sqlite"
    owner_token = secrets.token_urlsafe(32)
    os.environ["API_BEARER_TOKEN"] = owner_token
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    forbidden = []

    def blocked(*args, **kwargs):
        forbidden.append(True)
        raise AssertionError("Forbidden side effect in ASGI test")

    socket.getaddrinfo = socket.create_connection = blocked
    original_connect = socket.socket.connect

    def connect(sock, address):
        # Windows asyncio's loopback self-pipe only; HTTP transports are blocked.
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return original_connect(sock, address)
        return blocked()

    socket.socket.connect = connect
    smtplib.SMTP = smtplib.SMTP_SSL = blocked
    import httpx
    import pymysql
    from sqlalchemy import create_engine, event, func, select
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    httpx.HTTPTransport.handle_request = blocked
    httpx.AsyncHTTPTransport.handle_async_request = blocked
    pymysql.connect = blocked
    from app.config import Settings

    Settings.model_config["env_file"] = None
    from app.agent_schemas import OwnerContext, ResourceVersion, TaskScope
    from app.database import Base, get_db
    from app.gateway_contracts import ConsentCreate
    from app.main import app
    from app.models import AuditEvent, ExecutionAttempt, GatewayOperation, PendingApproval
    from app.services import trusted_execution
    from app.services.agent_identity import create_trusted_task, issue_agent_credential
    from app.services.resource_catalog import CatalogResource, ResourceCatalog, get_resource_catalog
    from app.services.scoped_consent import create_scoped_consent
    from app.services.tools import TOOLS

    for name in TOOLS:
        TOOLS[name] = blocked
    for name in ("dispatch_simulated", "dispatch_document_read", "dispatch_email"):
        if hasattr(trusted_execution, name):
            setattr(trusted_execution, name, blocked)
    durable = os.environ.get("GHOST_TEST_DURABLE_WORKER") == "1"
    engine = create_engine(
        "sqlite:///step35-worker.sqlite" if durable else "sqlite://",
        poolclass=None if durable else StaticPool,
        connect_args={"check_same_thread": False},
        hide_parameters=True,
    )

    @event.listens_for(engine, "connect")
    def configure(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    pin = ResourceVersion(
        resource_id="resource_http", version_ref="version_http", classification="SHAREABLE"
    )
    catalog = ResourceCatalog(
        resources=(CatalogResource(**pin.model_dump(), owner_id="local-user"),)
    )

    def db_override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_resource_catalog] = lambda: catalog
    requests = []

    class FakeMailpit:
        calls = 0
        state = "ACCEPTED"
        verified_messages = 0

        def submit(self, recipient, message):
            from email import policy
            from email.parser import BytesParser

            from app.services.email_profile import BODY, SENDER, SUBJECT

            parsed = BytesParser(policy=policy.default).parsebytes(message)
            if (
                recipient == parsed["To"] == "teammate@example.test"
                and parsed["From"] == SENDER
                and parsed["Subject"] == SUBJECT
                and parsed.get_payload(decode=True) == BODY.encode("utf-8")
                and parsed["X-Ghost-Transport"] == "MAILPIT-TEST-ONLY"
            ):
                self.verified_messages += 1
            self.calls += 1
            return self.state

    fake_mailpit = FakeMailpit()

    async def handle(command):
        if command["command"] == "email_profile":
            from app.services.email_profile import arguments_for

            return arguments_for("teammate@example.test").model_dump(mode="json")
        if command["command"] == "enable_controlled":
            from app.services.controlled_execution import (
                ControlledExecution,
                get_controlled_execution,
            )

            fake_mailpit.state = command.get("smtp_state", "ACCEPTED")
            service = ControlledExecution(email_transport=fake_mailpit)
            app.dependency_overrides[get_controlled_execution] = lambda: service
            return {"enabled": True}
        if command["command"] == "owner":
            return {"token": owner_token}
        if command["command"] == "owner_decide":
            from app.services.approvals import owner_approval

            with factory() as db:
                owner_approval(
                    db,
                    owner=OwnerContext(owner_id="local-user"),
                    approval_ref=command["approval_ref"],
                    resolution=command.get("resolution"),
                    revoke=command.get("revoke", False),
                    catalog=catalog,
                )
            return {"decided": True}
        if command["command"] == "bootstrap":
            now = datetime.now(UTC)
            owner = OwnerContext(owner_id=command.get("owner", "local-user"))
            owned_catalog = ResourceCatalog(
                resources=(CatalogResource(**pin.model_dump(), owner_id=owner.owner_id),)
            )
            email_action = command.get("email_action")
            scope = TaskScope(
                purpose="prepare_email" if email_action else "summarize_document",
                allowed_actions=(email_action,) if email_action else ("files.read",),
                resource_ids=() if email_action else (pin.resource_id,),
                resource_versions=() if email_action else (pin,),
                recipient="teammate@example.test" if email_action else None,
                approval_enabled=command.get("approval", False),
            )
            with factory() as db:
                task = create_trusted_task(
                    db,
                    owner=owner,
                    scope=scope,
                    catalog=owned_catalog,
                    now=now,
                    expires_at=now + timedelta(minutes=50),
                )
            with factory() as db:
                issued = issue_agent_credential(db, owner=owner, task_ref=task.task_ref, now=now)
            if command.get("consent"):
                with factory() as db:
                    create_scoped_consent(
                        db,
                        owner=owner,
                        task_ref=task.task_ref,
                        catalog=catalog,
                        payload=ConsentCreate(
                            action="files.read",
                            purpose=scope.purpose,
                            resource_ids=(pin.resource_id,),
                            expires_at=now + timedelta(minutes=10),
                        ),
                    )
            if command.get("credential_state"):
                from app.models import AgentCredential

                with factory.begin() as db:
                    row = db.get(AgentCredential, issued.credential_ref)
                    if command["credential_state"] == "expired":
                        row.issued_at = now - timedelta(minutes=20)
                        row.expires_at = now - timedelta(seconds=1)
                    else:
                        row.revoked_at = now
            return {"task_ref": task.task_ref, "token": issued.token.get_secret_value()}
        if command["command"] == "http":
            payload = command["body"] or {}
            requests.append(
                {key: payload.get(key) for key in ("request_id", "idempotency_key", "task_ref")}
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://asgi.test"
            ) as client:
                response = await client.request(
                    command.get("method", "POST"),
                    command["path"],
                    json=payload,
                    headers=command["headers"],
                )
            return {"status": response.status_code, "body": response.json()}
        if command["command"] == "stats":
            with factory() as db:
                return {
                    "requests": requests,
                    "fake_smtp_calls": fake_mailpit.calls,
                    "forbidden": len(forbidden),
                    "attempts": db.scalar(select(func.count()).select_from(ExecutionAttempt)),
                    "operations": db.scalar(select(func.count()).select_from(GatewayOperation)),
                    "approvals": [r.approval_ref for r in db.scalars(select(PendingApproval))],
                    "audits": [r.id for r in db.scalars(select(AuditEvent))],
                }
        if command["command"] == "demo_inspect":
            import re

            from app.services.email_profile import BODY

            with factory() as db:
                # Return assertions and references only, never row payloads or message bytes.
                raw = " ".join(
                    str(getattr(row, column.name))
                    for model in (GatewayOperation, AuditEvent)
                    for row in db.scalars(select(model))
                    for column in model.__table__.columns
                )
                approvals = list(db.scalars(select(PendingApproval)))
                return {
                    "private_rows_clean": not (
                        BODY in raw
                        or owner_token in raw
                        or "STEP38_PRIVATE_PROMPT" in raw
                        or re.search(r"gpa_cred_[0-9a-f]{32}\.[A-Za-z0-9_-]{43}", raw)
                    ),
                    "verified_messages": fake_mailpit.verified_messages,
                    "approval_consumed": any(r.consumed_at is not None for r in approvals),
                    "consent_bound": all(r.consent_ref is not None for r in approvals)
                    if approvals
                    else False,
                    "operation_states": [
                        r.operation_status for r in db.scalars(select(GatewayOperation))
                    ],
                }
        raise AssertionError("Unknown test control command")

    for line in sys.stdin:
        try:
            result = asyncio.run(handle(json.loads(line)))
            print(json.dumps(result), flush=True)
        except Exception:
            print('{"worker_error":true}', flush=True)
    engine.dispose()


if __name__ == "__main__":
    main()
