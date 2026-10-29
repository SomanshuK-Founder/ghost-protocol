from uuid import uuid4

import pytest
from app.models import AuditEvent, ConsentRecord, ToolPermission
from app.services.policy import audit, authorize_tool, record_consent, set_tool_permission
from sqlalchemy import inspect, select, text
from tests.integration.conftest import EXPECTED_MIGRATION, EXPECTED_TABLES

pytestmark = pytest.mark.integration


def unique_user_id() -> str:
    return f"mysql-test-{uuid4().hex[:24]}"


def test_mysql_connectivity_and_migrated_schema(mysql_engine):
    with mysql_engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == EXPECTED_MIGRATION
        )

    tables = set(inspect(mysql_engine).get_table_names())
    assert EXPECTED_TABLES.issubset(tables)


def test_mysql_consent_grant_and_denial_persist(mysql_session):
    user_id = unique_user_id()
    granted = record_consent(mysql_session, user_id, "tools:execute", True)
    denied = record_consent(mysql_session, user_id, "reports:read", False)

    assert granted.granted is True
    assert denied.granted is False
    rows = mysql_session.scalars(
        select(ConsentRecord).where(ConsentRecord.user_id == user_id)
    ).all()
    assert {(row.scope, row.granted) for row in rows} == {
        ("tools:execute", True),
        ("reports:read", False),
    }


def test_mysql_revocation_overrides_earlier_grant(mysql_session):
    user_id = unique_user_id()
    record_consent(mysql_session, user_id, "tools:execute", True)
    record_consent(mysql_session, user_id, "tools:execute", False)
    set_tool_permission(mysql_session, user_id, "echo", True)

    assert authorize_tool(mysql_session, user_id, "echo") is False


def test_mysql_tool_authorization_and_audit_persistence(mysql_session):
    user_id = unique_user_id()
    record_consent(mysql_session, user_id, "tools:execute", True)
    set_tool_permission(mysql_session, user_id, "echo", True)

    assert authorize_tool(mysql_session, user_id, "echo") is True
    audit(mysql_session, user_id, "integration.test", "allowed", {"tool": "echo"})
    mysql_session.commit()

    event = mysql_session.scalar(
        select(AuditEvent)
        .where(AuditEvent.user_id == user_id, AuditEvent.event_type == "integration.test")
        .order_by(AuditEvent.id.desc())
    )
    permission = mysql_session.scalar(
        select(ToolPermission).where(
            ToolPermission.user_id == user_id, ToolPermission.tool_name == "echo"
        )
    )
    assert event is not None
    assert event.outcome == "allowed"
    assert event.detail == {"tool": "echo"}
    assert permission is not None and permission.allowed is True


def test_mysql_api_authentication_and_tool_gate(mysql_client, integration_auth):
    payload = {"tool_name": "echo", "arguments": {"message": "mysql"}}
    assert mysql_client.post("/api/tools/execute", json=payload).status_code == 401
    assert mysql_client.post(
        "/api/tools/execute", headers=integration_auth, json=payload
    ).status_code in {200, 403}
