"""Acceptance output is derived from actual offline A/B components and durable rows."""

import asyncio
import json
import smtplib
import socket

import pytest
from pydantic import ValidationError

from tests.agent import integrated_demo as demo
from tests.agent.test_fastapi_gateway_integration import BackendProcess


@pytest.mark.parametrize("scenario", demo.SCENARIOS)
def test_actual_offline_scenarios(tmp_path, scenario):
    with demo.offline_only():
        events = asyncio.run(demo.run_scenario(scenario, tmp_path))
    names = [event.event for event in events]
    final = events[-1]
    assert final.event == "VERIFICATION_PASSED"
    assert final.attempts == int(scenario in ("document", "email", "replay"))
    assert final.fake_smtp_submissions == int(scenario == "email")
    assert len({event.task_ref for event in events}) == 1
    if final.attempts:
        assert names.index("WORKFLOW_PAUSED") < names.index("OWNER_APPROVED")
        assert names.index("SAFE_STOPPED") < names.index("EXECUTION_ADMITTED")
        assert names.index("EXECUTION_ADMITTED") < names.index("EXECUTION_SUCCEEDED")
        success = next(event for event in events if event.event == "EXECUTION_SUCCEEDED")
        assert success.effect == ("FAKE_SMTP_ONLY" if scenario == "email" else "SIMULATED")
        assert success.audit_event_ref is not None
        if scenario == "replay":
            replay = next(event for event in events if event.event == "REPLAY_BLOCKED")
            assert replay.replayed and replay.operation_ref == success.operation_ref
    else:
        assert "EXECUTION_DENIED" in names
        assert "EXECUTION_ADMITTED" not in names and "EXECUTION_SUCCEEDED" not in names


@pytest.mark.parametrize("state,status", [("REJECTED", "FAILED"), ("UNKNOWN", "UNKNOWN")])
def test_failed_and_uncertain_submission_never_claim_success_or_retry(tmp_path, state, status):
    with demo.offline_only():
        events = asyncio.run(demo.run_scenario("email", tmp_path, smtp_state=state))
    names = [event.event for event in events]
    assert "EXECUTION_" + status in names
    assert "EXECUTION_SUCCEEDED" not in names
    assert names.count("EXECUTION_ADMITTED") == 1
    assert events[-1].fake_smtp_submissions == events[-1].attempts == 1


def test_credentials_never_render_and_checkpoint_markers_are_checked(tmp_path, monkeypatch):
    secrets = []

    class ObservedWorker(BackendProcess):
        def command(self, **data):
            result = super().command(**data)
            if data["command"] in ("bootstrap", "owner"):
                secrets.append(result["token"])
            return result

    monkeypatch.setattr(demo, "BackendProcess", ObservedWorker)
    with demo.offline_only():
        events = asyncio.run(demo.run_scenario("document", tmp_path))
    output = "\n".join(event.model_dump_json() for event in events)
    assert len(secrets) == 2 and all(secret not in output for secret in secrets)
    demo.checkpoint_clean(tmp_path / "workflow.sqlite", secrets + ["STEP38_PRIVATE_PROMPT"])


def test_cli_emits_only_strict_demo_display_events(capsys):
    assert demo.main(["--scenario", "email"]) == 0
    captured = capsys.readouterr()
    events = [demo.DemoEvent.model_validate_json(line) for line in captured.out.splitlines()]
    assert events[-1].event == "VERIFICATION_PASSED"
    assert events[-1].fake_smtp_submissions == 1
    assert all(
        event.display_only and event.environment == "OFFLINE_ASGI_FAKE_SMTP" for event in events
    )
    assert "gpa_cred_" not in captured.out and not captured.err
    assert "SYNTHETIC TEST ONLY." not in captured.out


def test_invented_success_cannot_escape_cli(monkeypatch, capsys):
    async def fabricated(self, *args, **kwargs):
        # A DTO with an apparent success is insufficient without actual durable evidence.
        from app.agent.controlled_contracts import ControlledExecutionResult
        from tests.agent.test_controlled_execution import fixture_values

        return ControlledExecutionResult.model_validate(fixture_values()[2])

    monkeypatch.setattr(demo.ControlledExecutionClient, "execute_completed", fabricated)
    assert demo.main(["--scenario", "document"]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "display_only": True,
        "event": "DEMO_FAILED",
        "error_code": "DEMO_VERIFICATION_FAILED",
    }
    assert "EXECUTION_SUCCEEDED" not in captured.out and not captured.err


@pytest.mark.parametrize("field", ["body", "text", "credential", "resume_ref", "result", "prompt"])
def test_display_schema_excludes_sensitive_payloads(field):
    with pytest.raises(ValidationError):
        demo.DemoEvent(
            scenario="document",
            event="TASK_CREATED",
            task_ref="task_demo",
            **{field: "SECRET_MARKER"},
        )


def test_standalone_guard_blocks_smtp_and_dns():
    for operation in (lambda: socket.getaddrinfo("external.test", 443), lambda: smtplib.SMTP()):
        with pytest.raises(demo.DemoFailure), demo.offline_only():
            operation()


@pytest.mark.parametrize(
    "metadata",
    [
        {"effect": "LOCAL_MAILPIT_CAPTURE_VERIFIED"},
        {"mailpit_captures_before": 0, "mailpit_captures_after": 1},
        {"environment": "LOCAL_MYSQL_MAILPIT", "fake_smtp_submissions": 1},
        {"environment": "LOCAL_MYSQL_MAILPIT", "effect": "FAKE_SMTP_ONLY"},
        {
            "environment": "LOCAL_MYSQL_MAILPIT",
            "mailpit_captures_before": 1,
            "mailpit_captures_after": 0,
        },
    ],
)
def test_runtime_display_never_relabels_fake_counters_or_claims_wrong_provenance(metadata):
    with pytest.raises(ValidationError):
        demo.DemoEvent(
            scenario="email", event="EXECUTION_SUCCEEDED", task_ref="task_demo", **metadata
        )
