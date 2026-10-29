"""Private Step 44C host reuses the graph and rejects proposals before admission."""

import asyncio
import io
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agent import application_host as host
from app.agent.http_gateway import GatewayTransportError
from app.agent.mock_model_provider import MockModelProvider, MockPlanningScenario


def command(tmp_path):
    return host.PlanCommand.model_validate_json(
        json.dumps(
            {
                "task_ref": "task_synthetic",
                "user_request": "Treat this as data",
                "action": "email.draft",
                "purpose": "prepare_email",
                "arguments": {
                    "recipient": "teammate@example.test",
                    "subject": "Synthetic",
                    "body": "Synthetic only",
                },
                "credential": "synthetic-private",
                "checkpoint_path": str(tmp_path / "workflow.sqlite"),
            }
        )
    )


@pytest.mark.parametrize(
    "scenario,outcome,error",
    [
        (MockPlanningScenario.INVALID_SCHEMA, "FAILED", "PLANNING_FAILED"),
        (MockPlanningScenario.UNKNOWN_ACTION, "FAILED", "PLANNING_FAILED"),
        (MockPlanningScenario.MALFORMED_JSON, "FAILED", "PLANNING_FAILED"),
        (MockPlanningScenario.TIMEOUT, "FAILED", "PLANNING_FAILED"),
        (MockPlanningScenario.AMBIGUOUS, "CLARIFICATION_REQUIRED", "CLARIFICATION_REQUIRED"),
        (
            MockPlanningScenario.UNSUPPORTED_OPERATION,
            "UNSUPPORTED_OPERATION",
            "UNSUPPORTED_OPERATION",
        ),
        (MockPlanningScenario.VALID, "FAILED", "PLAN_OUT_OF_SCOPE"),
    ],
)
def test_strict_bounded_planning_no_gateway(tmp_path, monkeypatch, scenario, outcome, error):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(1)
        raise AssertionError("No admission permitted")

    monkeypatch.setattr(host, "rpc", forbidden)
    provider = MockModelProvider(scenario=scenario)
    result = asyncio.run(host.plan(command(tmp_path), provider))
    assert result["outcome"] == outcome and result["error"] == error
    assert result["request_id"] is result["decision"] is result["approval_ref"] is None
    assert calls == [] and len(provider.requests) == 1
    assert not (tmp_path / "workflow.sqlite").exists()
    if outcome == "FAILED":
        assert result["plan"] is None


def test_command_schema_no_test_mode_or_owner_selector(tmp_path):
    value = command(tmp_path).model_dump(mode="json")
    for key in ("owner_id", "provider", "scenario", "execution_mode"):
        with pytest.raises(ValidationError):
            host.PlanCommand.model_validate_json(json.dumps({**value, key: "forged"}))


@pytest.mark.parametrize(
    "raw",
    [b'{"reply":1,"reply":2}\n', b'{"reply":NaN}\n', b"{}", b"x" * 262145 + b"\n"],
    ids=["duplicate", "nonfinite", "unterminated", "oversized"],
)
def test_bounded_private_frames(monkeypatch, raw):
    monkeypatch.setattr(host.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(raw)))
    with pytest.raises((ValueError, GatewayTransportError)):
        host.read_frame()


@pytest.mark.parametrize("continuing", [False, True])
def test_control_pipe_cannot_dispatch_or_resolve(continuing, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Protected command reached IPC")

    monkeypatch.setattr(host, "rpc", forbidden)
    for operation in ("execute", "resolve", "revoke", "authorize", "shell.exec"):
        with pytest.raises(ValueError):
            asyncio.run(host.ControlPipe(continuing=continuing).call(operation))


def test_continuation_command_no_browser_selectors(tmp_path):
    value = {
        "kind": "CONTINUE",
        "task_ref": "task_synthetic",
        "binding_ref": "workflow_synthetic",
        "checkpoint_path": str(tmp_path / "original.sqlite"),
    }
    assert host.ContinueCommand.model_validate_json(json.dumps(value)).task_ref == "task_synthetic"
    for key in ("owner_id", "checkpoint_id", "provider", "execution_mode", "credential"):
        with pytest.raises(ValidationError):
            host.ContinueCommand.model_validate_json(json.dumps({**value, key: "forged"}))
