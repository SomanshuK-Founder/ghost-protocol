import pytest

from app.models import AuditEvent
from app.database import get_db


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_auth_required(client):
    assert client.post("/api/consents", json={"scope": "tools:execute", "granted": True}).status_code == 401


def test_consent_and_tool_permission_gate_tool(client, auth):
    execute = {"tool_name": "echo", "arguments": {"message": "hello"}}
    assert client.post("/api/tools/execute", headers=auth, json=execute).status_code == 403
    assert client.post("/api/consents", headers=auth, json={"scope": "tools:execute", "granted": True}).status_code == 200
    assert client.post("/api/tool-permissions", headers=auth, json={"tool_name": "echo", "allowed": True}).status_code == 200
    result = client.post("/api/tools/execute", headers=auth, json=execute)
    assert result.status_code == 200
    assert result.json() == {"result": {"message": "hello"}}


def test_revocation_denies_and_is_audited(client, auth):
    for granted in (True, False):
        response = client.post("/api/consents", headers=auth, json={"scope": "tools:execute", "granted": granted})
        assert response.status_code == 200
    client.post("/api/tool-permissions", headers=auth, json={"tool_name": "echo", "allowed": True})
    denied = client.post("/api/tools/execute", headers=auth, json={"tool_name": "echo", "arguments": {"message": "x"}})
    assert denied.status_code == 403
    events = client.get("/api/audit-events", headers=auth).json()
    assert any(event["event_type"] == "tool.execution" and event["outcome"] == "rejected" for event in events)


def test_allowlist_and_arguments(client, auth):
    unknown = client.post("/api/tools/execute", headers=auth, json={"tool_name": "shell", "arguments": {}})
    assert unknown.status_code == 404
    client.post("/api/consents", headers=auth, json={"scope": "tools:execute", "granted": True})
    client.post("/api/tool-permissions", headers=auth, json={"tool_name": "echo", "allowed": True})
    invalid = client.post("/api/tools/execute", headers=auth, json={"tool_name": "echo", "arguments": {"command": "whoami"}})
    assert invalid.status_code == 422


def authorize_text_stats(client, auth):
    assert client.post("/api/consents", headers=auth, json={"scope": "tools:execute", "granted": True}).status_code == 200
    assert client.post("/api/tool-permissions", headers=auth, json={"tool_name": "text_stats", "allowed": True}).status_code == 200


def test_text_stats_success(client, auth):
    authorize_text_stats(client, auth)
    response = client.post("/api/tools/execute", headers=auth, json={"tool_name": "text_stats", "arguments": {"text": "hello world"}})
    assert response.status_code == 200
    assert response.json() == {"result": {"character_count": 11, "word_count": 2, "line_count": 1, "is_empty": False}}


def test_text_stats_empty_and_multiline(client, auth):
    authorize_text_stats(client, auth)
    empty = client.post("/api/tools/execute", headers=auth, json={"tool_name": "text_stats", "arguments": {"text": ""}})
    multiline = client.post("/api/tools/execute", headers=auth, json={"tool_name": "text_stats", "arguments": {"text": "one\ntwo\nthree"}})
    assert empty.status_code == 200
    assert empty.json()["result"] == {"character_count": 0, "word_count": 0, "line_count": 0, "is_empty": True}
    assert multiline.status_code == 200
    assert multiline.json()["result"] == {"character_count": 13, "word_count": 3, "line_count": 3, "is_empty": False}


@pytest.mark.parametrize("arguments", [{}, {"text": 123}, {"text": "x", "extra": True}, {"text": "x" * 501}])
def test_text_stats_rejects_invalid_arguments(client, auth, arguments):
    authorize_text_stats(client, auth)
    response = client.post("/api/tools/execute", headers=auth, json={"tool_name": "text_stats", "arguments": arguments})
    assert response.status_code == 422


def test_text_stats_requires_consent_and_permission(client, auth):
    payload = {"tool_name": "text_stats", "arguments": {"text": "hello"}}
    assert client.post("/api/tools/execute", headers=auth, json=payload).status_code == 403
    assert client.post("/api/consents", headers=auth, json={"scope": "tools:execute", "granted": True}).status_code == 200
    assert client.post("/api/tools/execute", headers=auth, json=payload).status_code == 403


def test_text_stats_audits_allowed_and_rejected_execution(client, auth):
    payload = {"tool_name": "text_stats", "arguments": {"text": "hello"}}
    assert client.post("/api/tools/execute", headers=auth, json=payload).status_code == 403
    rejected_events = client.get("/api/audit-events", headers=auth).json()
    assert any(event["event_type"] == "tool.execution" and event["outcome"] == "rejected" and event["detail"]["tool"] == "text_stats" for event in rejected_events)
    authorize_text_stats(client, auth)
    assert client.post("/api/tools/execute", headers=auth, json=payload).status_code == 200
    allowed_events = client.get("/api/audit-events", headers=auth).json()
    assert any(event["event_type"] == "tool.execution" and event["outcome"] == "allowed" and event["detail"]["tool"] == "text_stats" for event in allowed_events)


def test_database_connectivity_via_api(client, auth):
    assert client.post("/api/consents", headers=auth, json={"scope": "tools:execute", "granted": True}).status_code == 200
    from app.database import get_db
    generator = get_db()
    next(generator)
    generator.close()
