"""Step 39 private ASGI worker, loaded only by the verified MySQL guard."""

import asyncio
import json
import os
import re
import sys
import urllib.request
from datetime import UTC, datetime, timedelta

import httpx
from app.agent_schemas import OwnerContext, ResourceVersion, TaskScope
from app.database import get_db
from app.main import app
from app.models import AuditEvent, ExecutionAttempt, GatewayOperation, PendingApproval
from app.services.agent_identity import create_trusted_task, issue_agent_credential
from app.services.controlled_execution import ControlledExecution, get_controlled_execution
from app.services.email_profile import BODY, SENDER, SUBJECT, arguments_for
from app.services.mailpit_email import MailpitSMTP
from app.services.resource_catalog import CatalogResource, ResourceCatalog, get_resource_catalog
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

# The guard supplies these objects, after validating database UUID/TLS and networking.
if "ENGINE" not in globals() or "GUARD_ATTEMPTS" not in globals():
    raise RuntimeError("Verified validation guard required")
factory = sessionmaker(globals()["ENGINE"], expire_on_commit=False)
pin = ResourceVersion(
    resource_id="resource_http", version_ref="version_http", classification="SHAREABLE"
)
catalog = ResourceCatalog(resources=(CatalogResource(**pin.model_dump(), owner_id="local-user"),))
lost_ack = False


def api(path):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://mailpit:8025" + path, timeout=3) as response:
        return json.load(response)


def database():
    with factory() as db:
        yield db


class Transport:
    def submit(self, recipient, message):
        state = MailpitSMTP().submit(recipient, message)
        if lost_ack and state == "ACCEPTED":
            raise RuntimeError("SYNTHETIC_LOST_ACK_MARKER")
        return state


app.dependency_overrides[get_db] = database
app.dependency_overrides[get_resource_catalog] = lambda: catalog
app.dependency_overrides[get_controlled_execution] = lambda: ControlledExecution(
    email_transport=Transport()
)


async def handle(command):
    global lost_ack
    name = command["command"]
    if name == "enable_controlled":
        assert command.get("smtp_state", "ACCEPTED") in ("ACCEPTED", "UNKNOWN")
        lost_ack = command.get("smtp_state") == "UNKNOWN"
        return {"enabled": True}
    if name == "owner":
        return {"token": os.environ["API_BEARER_TOKEN"]}
    if name == "email_profile":
        return arguments_for("teammate@example.test").model_dump(mode="json")
    if name == "bootstrap":
        now = datetime.now(UTC)
        email = command.get("email_action")
        action = email or "files.read"
        assert action in ("files.read", "email.send")
        owner = OwnerContext(owner_id="local-user")
        scope = TaskScope(
            purpose="prepare_email" if email else "summarize_document",
            allowed_actions=(action,),
            resource_ids=() if email else (pin.resource_id,),
            resource_versions=() if email else (pin,),
            recipient="teammate@example.test" if email else None,
            approval_enabled=command.get("approval", False),
        )
        with factory() as db:
            task = create_trusted_task(
                db,
                owner=owner,
                scope=scope,
                catalog=catalog,
                now=now,
                expires_at=now + timedelta(minutes=50),
            )
        with factory() as db:
            issued = issue_agent_credential(db, owner=owner, task_ref=task.task_ref, now=now)
        return {"task_ref": task.task_ref, "token": issued.token.get_secret_value()}
    if name == "http":
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://asgi.test"
        ) as client:
            response = await client.request(
                command["method"],
                command["path"],
                json=command.get("body"),
                headers=command["headers"],
            )
        assert all(
            secret not in response.text
            for secret in (
                os.environ["API_BEARER_TOKEN"],
                os.environ["MYSQL_PASSWORD"],
                "SYNTHETIC_LOST_ACK_MARKER",
            )
        )
        return {"status": response.status_code, "body": response.json()}
    if name == "captures":
        return {"captures": api("/api/v1/messages")["total"]}
    if name in ("stats", "demo_inspect"):
        task = command["task_ref"]
        with factory() as db:
            ops = list(
                db.scalars(select(GatewayOperation).where(GatewayOperation.task_ref == task))
            )
            approvals = list(
                db.scalars(select(PendingApproval).where(PendingApproval.task_ref == task))
            )
            attempts = list(
                db.scalars(
                    select(ExecutionAttempt)
                    .join(GatewayOperation)
                    .where(GatewayOperation.task_ref == task)
                )
            )
            audits = list(db.scalars(select(AuditEvent)))
            if name == "stats":
                return {
                    "attempts": len(attempts),
                    "operations": len(ops),
                    "approvals": [a.approval_ref for a in approvals],
                    "audits": [a.id for a in audits],
                    "forbidden": len(globals()["GUARD_ATTEMPTS"]),
                }
            raw = " ".join(
                str(getattr(row, c.name)) for row in [*ops, *audits] for c in row.__table__.columns
            )
            assert all(
                marker not in raw
                for marker in (
                    BODY,
                    os.environ["API_BEARER_TOKEN"],
                    os.environ["MYSQL_PASSWORD"],
                    "STEP38_PRIVATE_PROMPT",
                )
            )
            assert re.search(r"gpa_cred_[a-f0-9]{32}\.[A-Za-z0-9_-]{43}", raw) is None
            messages = api("/api/v1/messages")["messages"]
            for item in messages:
                value = api("/api/v1/message/" + item["ID"])
                assert value["From"]["Address"] == SENDER
                assert [to["Address"] for to in value["To"]] == ["teammate@example.test"]
                assert value["Subject"] == SUBJECT and value["Text"] == BODY
            return {
                "private_rows_clean": True,
                "verified_messages_total": len(messages),
                "approval_consumed": any(a.consumed_at is not None for a in approvals),
                "consent_bound": bool(approvals) and all(a.consent_ref for a in approvals),
                "operation_states": [op.operation_status for op in ops],
            }
    raise RuntimeError("Unknown validation command")


print('{"ready":true}', flush=True)
for line in sys.stdin:
    try:
        print(json.dumps(asyncio.run(handle(json.loads(line)))), flush=True)
    except Exception as exc:
        print(json.dumps({"worker_error": type(exc).__name__}), flush=True)
