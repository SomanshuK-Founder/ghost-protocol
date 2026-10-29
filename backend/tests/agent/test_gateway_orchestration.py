"""B2.2a behavioral tests; local synthetic values only, never the official dataset."""

import asyncio
import builtins
import os
import smtplib
import socket
import subprocess
from pathlib import Path

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from app.agent.demo_execute import main as demo_main
from app.agent.demo_execute import run_scenarios
from app.agent.execution_contracts import (
    ActionBinding,
    ActionExecutionResult,
    AgentExecutionResult,
    ExecutionErrorCode,
    ExecutionInputError,
    ExecutionOptions,
    ExecutionOutcome,
)
from app.agent.gateway_protocol import (
    AuthorizationDecision,
    ExecutionStatus,
    ToolAction,
    ToolRequest,
    ToolResponse,
)
from app.agent.mock_gateway import MockToolGateway
from app.agent.mock_model_provider import MockModelProvider, MockPlanningScenario
from app.agent.orchestration import GatewayOrchestrator, build_tool_request
from app.agent.planning_contracts import PlanningOutcome
from app.agent.state import AgentTaskState, TaskStatus
from app.llm.config import ModelTier
from app.llm.nebius_provider import NebiusModelProvider

TASK = "task-b22a-synthetic"
USER_REQUEST = "Prepare a synthetic summary and email draft."


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("External networking is forbidden")

    connect, connect_ex = socket.socket.connect, socket.socket.connect_ex

    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return connect(sock, address)
        return forbidden()

    def local_connect_ex(sock, address):
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return connect_ex(sock, address)
        return forbidden()

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", local_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", local_connect_ex)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    yield
    assert not attempts


class RecordingGateway(MockToolGateway):
    def __init__(self, fixtures=()):
        super().__init__(fixtures)
        self.calls = []

    async def execute(self, request):
        self.calls.append(request)
        return await super().execute(request)


def binding(action="files.read", index=0, task_ref=TASK, **overrides):
    arguments = (
        {"resource_id": f"synthetic-resource-{index}"}
        if action == "files.read"
        else {
            "recipient": "teammate@example.test",
            "subject": "Synthetic subject",
            "body": f"Synthetic fixture {index}",
            "attachment_resource_ids": [],
        }
        if action in ("email.draft", "email.send")
        else {}
    )
    return ActionBinding(
        **{
            "task_ref": task_ref,
            "action": action,
            "purpose": "synthetic_workflow",
            "arguments": arguments,
            **overrides,
        }
    )


def plan_output(actions, task_ref=TASK, **overrides):
    return {
        "task_ref": task_ref,
        "intent": "summarize_and_prepare_email",
        "proposed_actions": list(actions),
        "requires_external_action": bool(actions),
        "clarification_required": False,
        **overrides,
    }


def setup(actions=("files.read",), outcomes=(), *, task_ref=TASK, options=None, bindings=None):
    bindings = tuple(
        bindings
        if bindings is not None
        else (binding(action, index, task_ref) for index, action in enumerate(actions))
    )
    fixtures = []
    for index, item in enumerate(bindings):
        request = build_tool_request(task_ref, index, item.action, item)
        decision, status = outcomes[index] if index < len(outcomes) else ("ALLOW", "SUCCEEDED")
        fixtures.append(
            (
                request,
                ToolResponse(
                    request_id=request.request_id,
                    decision=decision,
                    execution_status=status,
                    reason_code="EXPLICIT_SYNTHETIC_FIXTURE",
                    approval_ref="approval-synthetic-001"
                    if decision == "APPROVAL_REQUIRED"
                    else None,
                    result={"private_fixture_content": "SYNTHETIC_PRIVATE_RESULT_MARKER"}
                    if status == "SUCCEEDED"
                    else None,
                ),
            )
        )
    gateway = RecordingGateway(fixtures)
    model = MockModelProvider(output=plan_output(actions, task_ref))
    service = GatewayOrchestrator(model, gateway, execution_options=options)
    return service, model, gateway, bindings


def execute(service, bindings=(), task_ref=TASK):
    return asyncio.run(service.execute_task(task_ref, USER_REQUEST, bindings))


def test_execution_graph_reuses_planning_nodes_and_has_one_bounded_action_cycle():
    service, _, _, _ = setup()
    graph = service._graph.get_graph()
    assert set(graph.nodes) == {
        "__start__",
        "initialize",
        "interpret_task",
        "validate_plan",
        "failed",
        "__end__",
        "select_next_action",
        "validate_tool_request",
        "call_mock_gateway",
        "process_gateway_response",
        "finish_execution",
    }
    edges = {(edge.source, edge.target) for edge in graph.edges}
    assert ("validate_plan", "select_next_action") in edges
    assert ("process_gateway_response", "select_next_action") in edges
    assert not any(
        target == "interpret_task" and source != "initialize" for source, target in edges
    )
    assert service.recursion_limit == 28


@pytest.mark.parametrize("action", list(ToolAction))
def test_every_existing_action_can_succeed_only_through_the_gateway(action):
    service, model, gateway, bindings = setup((action,))
    result = execute(service, bindings)
    assert result.execution_outcome == ExecutionOutcome.ALL_ACTIONS_SUCCEEDED
    assert result.completed_action_count == result.total_action_count == 1
    assert len(gateway.calls) == len(model.requests) == 1
    assert isinstance(gateway.calls[0], ToolRequest)
    assert result.action_results[0].decision == AuthorizationDecision.ALLOW
    assert result.action_results[0].execution_status == ExecutionStatus.SUCCEEDED
    assert result.simulation and result.action_results[0].simulation
    assert result.task_state.status == TaskStatus.COMPLETED
    assert isinstance(result.task_state, AgentTaskState)
    assert AgentExecutionResult.model_validate_json(result.model_dump_json()) == result
    assert "SYNTHETIC_PRIVATE_RESULT_MARKER" not in result.model_dump_json()


def test_multiple_successes_are_in_plan_order_without_duplicate_requests():
    actions = ("files.list_authorized", "files.read", "email.draft", "email.send", "tasks.list")
    service, model, gateway, bindings = setup(actions)
    result = execute(service, bindings)
    assert result.completed_action_count == result.total_action_count == 5
    assert tuple(request.action for request in gateway.calls) == actions
    assert len({request.request_id for request in gateway.calls}) == 5
    assert len({request.idempotency_key for request in gateway.calls}) == 5
    assert len(model.requests) == 1
    assert all(
        record.execution_status == ExecutionStatus.SUCCEEDED for record in result.action_results
    )


@pytest.mark.parametrize(
    ("decision", "status", "outcome", "error", "task_status"),
    [
        (
            "ALLOW",
            "FAILED",
            ExecutionOutcome.EXECUTION_FAILED,
            ExecutionErrorCode.GATEWAY_EXECUTION_FAILED,
            TaskStatus.FAILED,
        ),
        (
            "ALLOW",
            "UNKNOWN",
            ExecutionOutcome.EXECUTION_UNKNOWN,
            ExecutionErrorCode.GATEWAY_EXECUTION_UNKNOWN,
            TaskStatus.FAILED,
        ),
        (
            "ALLOW",
            "NOT_EXECUTED",
            ExecutionOutcome.EXECUTION_FAILED,
            ExecutionErrorCode.GATEWAY_NOT_EXECUTED,
            TaskStatus.FAILED,
        ),
        (
            "DENY",
            "NOT_EXECUTED",
            ExecutionOutcome.DENIED,
            ExecutionErrorCode.GATEWAY_DENIED,
            TaskStatus.FAILED,
        ),
        (
            "APPROVAL_REQUIRED",
            "NOT_EXECUTED",
            ExecutionOutcome.APPROVAL_REQUIRED,
            None,
            TaskStatus.AWAITING_APPROVAL,
        ),
    ],
)
def test_first_non_success_stops_later_actions_without_replanning(
    decision, status, outcome, error, task_status
):
    service, model, gateway, bindings = setup(
        ("files.read", "email.send", "tasks.list"), (("ALLOW", "SUCCEEDED"), (decision, status))
    )
    result = execute(service, bindings)
    assert result.execution_outcome == outcome and result.error_code == error
    assert result.task_state.status == task_status
    assert result.completed_action_count == 1 and result.total_action_count == 3
    assert len(gateway.calls) == 2 and len(model.requests) == 1
    assert result.action_results[-1].execution_status == status
    assert result.action_results[-1].reason_code == "MOCK_EXPLICIT_SYNTHETIC_FIXTURE"
    assert result.action_results[-1].audit_event_ref == f"mock-event-{gateway.calls[-1].request_id}"
    assert result.planning_result.outcome == PlanningOutcome.PLAN_READY
    assert result.planning_result.task_state.status == TaskStatus.COMPLETED
    assert result.task_state.retry_count == 0
    if decision == "APPROVAL_REQUIRED":
        assert (
            result.pending_approval_ref
            == result.task_state.approval_ref
            == "approval-synthetic-001"
        )
        assert result.task_state.pending_request_ref == gateway.calls[-1].request_id
        checkpoint = service.checkpointer.get_tuple({"configurable": {"thread_id": f"b22a-{TASK}"}})
        assert not checkpoint.pending_writes or all(
            channel != "__interrupt__" for _, channel, _ in checkpoint.pending_writes
        )
        assert service._graph.get_state({"configurable": {"thread_id": f"b22a-{TASK}"}}).next == ()
    else:
        assert result.pending_approval_ref is None and result.task_state.approval_ref is None


def test_unconfigured_gateway_remains_default_deny_and_never_reports_an_email_sent():
    model = MockModelProvider(output=plan_output(["email.send", "tasks.list"]))
    gateway = RecordingGateway()
    service = GatewayOrchestrator(model, gateway)
    result = execute(service, (binding("email.send"), binding("tasks.list", 1)))
    assert result.execution_outcome == ExecutionOutcome.DENIED
    assert result.action_results[0].reason_code == "MOCK_NO_FIXTURE"
    assert result.action_results[0].execution_status == ExecutionStatus.NOT_EXECUTED
    assert len(gateway.calls) == 1 and result.completed_action_count == 0
    assert "sent" not in result.model_dump_json().lower()


@pytest.mark.parametrize(
    "changes",
    [
        {"arguments": {}},
        {"arguments": {"resource_id": "C:\\private\\tax.txt"}},
        {"arguments": {"resource_id": "../private"}},
        {"arguments": {"resource_id": "/private/tax.txt"}},
        {"arguments": {"resource_id": 42}},
        {"arguments": {"resource_id": "synthetic-001", "path": "secret"}},
        {"arguments": {"recipient": "teammate@example.test"}},
        {"task_ref": "wrong-task"},
        {"action": "tasks.list"},
    ],
)
def test_malformed_or_mismatched_bindings_fail_before_any_gateway_call(changes):
    model = MockModelProvider(output=plan_output(["files.read"]))
    gateway = RecordingGateway()
    service = GatewayOrchestrator(model, gateway)
    result = execute(service, (binding(**changes),))
    assert result.execution_outcome == ExecutionOutcome.INVALID_TOOL_REQUEST
    assert result.error_code == ExecutionErrorCode.INVALID_TOOL_REQUEST
    assert result.completed_action_count == 0 and gateway.calls == []
    assert result.planning_result.outcome == PlanningOutcome.PLAN_READY


@pytest.mark.parametrize(
    "arguments",
    [
        {"recipient": "no-email", "subject": "x", "body": "x"},
        {"recipient": "teammate@example.test", "subject": "bad\nheader", "body": "x"},
        {"recipient": "teammate@example.test", "subject": "x", "body": 42},
        {"recipient": "teammate@example.test", "subject": "x", "body": "x", "allow": True},
        {
            "recipient": "teammate@example.test",
            "subject": "x",
            "body": "x",
            "attachment_resource_ids": ["/private"],
        },
    ],
)
def test_email_arguments_use_unchanged_b0_validators(arguments):
    model = MockModelProvider(output=plan_output(["email.send"]))
    gateway = RecordingGateway()
    result = execute(
        GatewayOrchestrator(model, gateway), (binding("email.send", arguments=arguments),)
    )
    assert result.execution_outcome == ExecutionOutcome.INVALID_TOOL_REQUEST and not gateway.calls


def test_later_missing_arguments_prevent_partial_execution_during_preflight():
    service, model, gateway, _ = setup(("files.read", "email.send"))
    result = execute(service, (binding(), binding("email.send", 1, arguments={})))
    assert result.execution_outcome == ExecutionOutcome.INVALID_TOOL_REQUEST
    assert result.total_action_count == 2 and result.completed_action_count == 0
    assert not gateway.calls and len(model.requests) == 1


@pytest.mark.parametrize("count", [0, 2])
def test_missing_and_excess_bindings_do_not_invent_arguments(count):
    service, _, gateway, _ = setup()
    result = execute(service, tuple(binding(index=index) for index in range(count)))
    assert result.execution_outcome == ExecutionOutcome.INVALID_TOOL_REQUEST and not gateway.calls


@pytest.mark.parametrize("action", ["files.read", "email.send"])
def test_unknown_resources_or_recipients_are_not_rewritten_to_permitted_values(action):
    service, _, gateway, bindings = setup((action,))
    values = dict(bindings[0].arguments)
    values["resource_id" if action == "files.read" else "recipient"] = (
        "unconfigured-resource" if action == "files.read" else "unauthorized@example.test"
    )
    result = execute(service, (binding(action, arguments=values),))
    assert result.execution_outcome == ExecutionOutcome.DENIED
    assert result.action_results[0].reason_code == "MOCK_NO_FIXTURE"
    assert gateway.calls[0].arguments.model_dump(mode="json") == build_tool_request(
        TASK, 0, ToolAction(action), binding(action, arguments=values)
    ).arguments.model_dump(mode="json")


@pytest.mark.parametrize(
    "scenario",
    [
        MockPlanningScenario.UNKNOWN_ACTION,
        MockPlanningScenario.INVALID_SCHEMA,
        MockPlanningScenario.MALFORMED_JSON,
        MockPlanningScenario.AUTHENTICATION,
        MockPlanningScenario.TIMEOUT,
    ],
)
def test_invalid_plans_and_model_failures_never_reach_the_gateway(scenario):
    model = MockModelProvider(scenario=scenario)
    gateway = RecordingGateway()
    result = execute(GatewayOrchestrator(model, gateway))
    assert result.execution_outcome == ExecutionOutcome.PLANNING_FAILED
    assert result.planning_result.outcome == PlanningOutcome.FAILED
    assert result.task_state.status == TaskStatus.FAILED
    assert not gateway.calls and result.total_action_count == 0
    assert len(model.requests) == 1


@pytest.mark.parametrize(
    ("scenario", "outcome"),
    [
        (MockPlanningScenario.EMPTY_ACTIONS, ExecutionOutcome.NO_ACTIONS),
        (MockPlanningScenario.AMBIGUOUS, ExecutionOutcome.CLARIFICATION_REQUIRED),
        (MockPlanningScenario.UNSUPPORTED_OPERATION, ExecutionOutcome.UNSUPPORTED_OPERATION),
    ],
)
def test_non_executable_planning_outcomes_do_not_call_gateway(scenario, outcome):
    gateway = RecordingGateway()
    result = execute(GatewayOrchestrator(MockModelProvider(scenario=scenario), gateway))
    assert result.execution_outcome == outcome and not gateway.calls
    assert result.total_action_count == result.completed_action_count == 0


def test_deterministic_ids_use_validated_canonical_arguments_and_task_binding():
    first = binding("email.send")
    reordered = binding("email.send", arguments=dict(reversed(list(first.arguments.items()))))
    a = build_tool_request(TASK, 0, first.action, first)
    b = build_tool_request(TASK, 0, reordered.action, reordered)
    assert a.request_id == b.request_id and a.idempotency_key == b.idempotency_key
    assert a == b and a.request_id != a.idempotency_key
    assert len(a.request_id) <= 128 and len(a.idempotency_key) <= 128
    next_index = build_tool_request(TASK, 1, first.action, first)
    assert next_index.request_id != a.request_id and next_index.idempotency_key != a.idempotency_key
    other_task = binding("email.send", task_ref="another-task")
    assert (
        build_tool_request("another-task", 0, other_task.action, other_task).request_id
        != a.request_id
    )
    changed = binding(
        "email.send", arguments={**first.arguments, "recipient": "other@example.test"}
    )
    assert build_tool_request(TASK, 0, changed.action, changed).idempotency_key != a.idempotency_key


def test_duplicate_semantic_actions_are_rejected_before_dispatch():
    repeated = (binding(), binding())
    model = MockModelProvider(output=plan_output(["files.read", "files.read"]))
    gateway = RecordingGateway()
    result = execute(GatewayOrchestrator(model, gateway), repeated)
    assert result.error_code == ExecutionErrorCode.DUPLICATE_ACTION
    assert not gateway.calls


@pytest.mark.parametrize("limit", [1, 5, 10])
def test_configurable_limit_allows_exactly_supported_actions_with_bounded_steps(limit):
    actions = ["files.read"] * limit
    service, _, gateway, bindings = setup(actions, options=ExecutionOptions(max_plan_actions=limit))
    result = execute(service, bindings)
    assert result.completed_action_count == limit and len(gateway.calls) == limit
    assert service.recursion_limit == 4 * limit + 8
    checkpoints = list(service.checkpointer.list({"configurable": {"thread_id": f"b22a-{TASK}"}}))
    assert len(checkpoints) <= service.recursion_limit + 2


def test_excess_plan_actions_fail_before_dispatch_and_are_not_truncated():
    service, _, gateway, bindings = setup(["files.read"] * 6)
    result = execute(service, bindings)
    assert result.execution_outcome == ExecutionOutcome.ACTION_LIMIT_EXCEEDED
    assert result.total_action_count == 6 and result.completed_action_count == 0
    assert len(result.planning_result.structured_plan.proposed_actions) == 6
    assert not gateway.calls


@pytest.mark.parametrize(
    "options",
    [
        {"max_plan_actions": 0},
        {"max_plan_actions": 11},
        {"max_plan_actions": True},
        {"gateway_timeout_seconds": 0},
        {"gateway_timeout_seconds": float("inf")},
        {"gateway_timeout_seconds": 31},
    ],
)
def test_execution_configuration_is_bounded(options):
    with pytest.raises(ValidationError):
        ExecutionOptions(**options)


@pytest.mark.parametrize("exception", [RuntimeError, ValueError, TimeoutError])
def test_gateway_exceptions_are_sanitized_uncertain_and_never_retried(exception):
    class BrokenGateway:
        def __init__(self):
            self.calls = []

        async def execute(self, request):
            self.calls.append(request)
            raise exception("SYNTHETIC_SECRET_EXCEPTION_MARKER")

    gateway = BrokenGateway()
    model = MockModelProvider(output=plan_output(["email.send", "tasks.list"]))
    service = GatewayOrchestrator(model, gateway)
    result = execute(service, (binding("email.send"), binding("tasks.list", 1)))
    assert result.execution_outcome == ExecutionOutcome.GATEWAY_UNAVAILABLE
    assert result.action_results[0].decision is None
    assert result.action_results[0].execution_status == ExecutionStatus.UNKNOWN
    assert result.error_code == (
        ExecutionErrorCode.GATEWAY_TIMEOUT
        if exception is TimeoutError
        else ExecutionErrorCode.GATEWAY_UNAVAILABLE
    )
    assert len(gateway.calls) == len(model.requests) == 1
    assert "SYNTHETIC_SECRET_EXCEPTION_MARKER" not in result.model_dump_json()
    assert "SYNTHETIC_SECRET_EXCEPTION_MARKER" not in repr(service.checkpointer.storage)


def test_gateway_deadline_is_used_without_timing_dependent_assertions(monkeypatch):
    original_timeout = asyncio.timeout
    limits = []

    class Deadline:
        async def __aenter__(self):
            raise TimeoutError()

        async def __aexit__(self, *args):
            pass

    def timeout(seconds):
        limits.append(seconds)
        return Deadline() if seconds == 7 else original_timeout(seconds)

    service, _, gateway, bindings = setup(options=ExecutionOptions(gateway_timeout_seconds=7))
    monkeypatch.setattr(asyncio, "timeout", timeout)
    result = execute(service, bindings)
    assert result.error_code == ExecutionErrorCode.GATEWAY_TIMEOUT
    assert result.action_results[0].execution_status == ExecutionStatus.NOT_EXECUTED
    assert not gateway.calls and limits == [110, 7]


@pytest.mark.parametrize(
    "corruption", ["wrong_id", "deny_success", "missing_approval", "bad_type", "unknown_decision"]
)
def test_invalid_gateway_response_cannot_fabricate_success_or_authority(corruption, recwarn):
    class InvalidGateway:
        async def execute(self, request):
            if corruption == "bad_type":
                return {"decision": "ALLOW"}
            data = {
                "request_id": request.request_id,
                "decision": "ALLOW",
                "execution_status": "SUCCEEDED",
                "reason_code": "SYNTHETIC_RESULT",
                "approval_ref": None,
                "audit_event_ref": None,
                "result": {"private_content": "SYNTHETIC_PRIVATE_TOOL_MARKER"},
            }
            if corruption == "wrong_id":
                data["request_id"] = "wrong-id"
            elif corruption == "deny_success":
                data["decision"] = "DENY"
            elif corruption == "missing_approval":
                data.update(
                    decision="APPROVAL_REQUIRED", execution_status="NOT_EXECUTED", result=None
                )
            else:
                data["decision"] = "UNTRUSTED_ALLOW"
            return ToolResponse.model_construct(**data)

    model = MockModelProvider(output=plan_output(["files.read", "tasks.list"]))
    service = GatewayOrchestrator(model, InvalidGateway())
    result = execute(service, (binding(), binding("tasks.list", 1)))
    assert result.execution_outcome == ExecutionOutcome.EXECUTION_UNKNOWN
    assert result.error_code == ExecutionErrorCode.INVALID_GATEWAY_RESPONSE
    assert result.completed_action_count == 0 and len(result.action_results) == 1
    assert result.action_results[0].decision is None and not recwarn
    assert "SYNTHETIC_PRIVATE_TOOL_MARKER" not in result.model_dump_json()


@pytest.mark.parametrize(
    "outcome",
    [
        ("ALLOW", "SUCCEEDED"),
        ("DENY", "NOT_EXECUTED"),
        ("APPROVAL_REQUIRED", "NOT_EXECUTED"),
        ("ALLOW", "UNKNOWN"),
    ],
)
def test_processed_tasks_are_single_use_including_failed_and_pending_tasks(outcome):
    service, model, gateway, bindings = setup(outcomes=(outcome,))
    execute(service, bindings)
    with pytest.raises(ExecutionInputError, match="cannot be repeated"):
        execute(service, bindings)
    assert len(gateway.calls) == len(model.requests) == 1


def test_existing_checkpoints_reject_replay_across_service_instances():
    service, model, gateway, bindings = setup()
    execute(service, bindings)
    recreated = GatewayOrchestrator(model, gateway, checkpointer=service.checkpointer)
    service.checkpointer.__dict__["_ghost_b22a_reserved_threads"].clear()
    with pytest.raises(ExecutionInputError):
        execute(recreated, bindings)
    assert len(gateway.calls) == len(model.requests) == 1


def test_preflight_failure_is_also_single_use_and_cannot_silently_replan():
    service, model, gateway, bindings = setup()
    result = execute(service, (binding(arguments={}),))
    assert result.execution_outcome == ExecutionOutcome.INVALID_TOOL_REQUEST
    with pytest.raises(ExecutionInputError):
        execute(service, bindings)
    assert not gateway.calls and len(model.requests) == 1


def test_wrong_model_plan_task_reference_fails_before_dispatch():
    model = MockModelProvider(output=plan_output(["files.read"], "wrong-task"))
    gateway = RecordingGateway()
    result = execute(GatewayOrchestrator(model, gateway), (binding(),))
    assert result.execution_outcome == ExecutionOutcome.PLANNING_FAILED and not gateway.calls


def test_concurrent_replay_is_rejected_before_first_checkpoint_across_instances():
    ready, release = None, None

    class PausingModel(MockModelProvider):
        async def infer(self, request):
            ready.set()
            await release.wait()
            return await super().infer(request)

    shared = InMemorySaver()
    model = PausingModel(output=plan_output(["files.read"]))
    request = build_tool_request(TASK, 0, ToolAction.FILES_READ, binding())
    gateway = RecordingGateway(
        (
            (
                request,
                ToolResponse(
                    request_id=request.request_id,
                    decision="ALLOW",
                    execution_status="SUCCEEDED",
                    reason_code="SYNTHETIC_SUCCESS",
                ),
            ),
        )
    )
    first = GatewayOrchestrator(model, gateway, checkpointer=shared)
    second = GatewayOrchestrator(model, gateway, checkpointer=shared)

    async def scenario():
        nonlocal ready, release
        ready, release = asyncio.Event(), asyncio.Event()
        active = asyncio.create_task(first.execute_task(TASK, USER_REQUEST, (binding(),)))
        await ready.wait()
        try:
            with pytest.raises(ExecutionInputError):
                await second.execute_task(TASK, USER_REQUEST, (binding(),))
        finally:
            release.set()
        return await active

    result = asyncio.run(scenario())
    assert result.completed_action_count == 1 and len(gateway.calls) == len(model.requests) == 1


def test_different_tasks_have_isolated_histories_and_requests():
    gateway = RecordingGateway()
    model = MockModelProvider()
    service = GatewayOrchestrator(model, gateway)
    for reference in ("task-isolation-a", "task-isolation-b"):
        model._output = plan_output(["files.read"], reference)
        request = build_tool_request(
            reference, 0, ToolAction.FILES_READ, binding(task_ref=reference)
        )
        fixture = ToolResponse(
            request_id=request.request_id,
            decision="ALLOW",
            execution_status="SUCCEEDED",
            reason_code="SYNTHETIC_SUCCESS",
        )
        # New strict gateway fixture set; no allow-all behavior.
        service._gateway = RecordingGateway(((request, fixture),))
        result = execute(service, (binding(task_ref=reference),), reference)
        assert (
            result.task_ref == reference
            and result.action_results[0].request_ref == request.request_id
        )
    assert set(service.checkpointer.storage) == {"b22a-task-isolation-a", "b22a-task-isolation-b"}
    for reference in ("task-isolation-a", "task-isolation-b"):
        state = service.checkpointer.get_tuple(
            {"configurable": {"thread_id": f"b22a-{reference}"}}
        ).checkpoint["channel_values"]
        assert state["task_ref"] == reference and len(state["execution_history"]) == 1


def test_gateway_dispatch_is_serialized_even_for_concurrent_independent_tasks():
    class SchedulingProbe(RecordingGateway):
        def __init__(self, fixtures):
            super().__init__(fixtures)
            self.active = self.max_active = 0

        async def execute(self, request):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            try:
                await asyncio.sleep(0)  # Scheduling yield only, no timing assertion.
                return await super().execute(request)
            finally:
                self.active -= 1

    actions = ("files.list_authorized", "files.read", "email.draft")
    references = ("task-concurrent-a", "task-concurrent-b")
    inputs, fixtures = {}, []
    for reference in references:
        inputs[reference] = tuple(
            binding(action, index, reference) for index, action in enumerate(actions)
        )
        for index, item in enumerate(inputs[reference]):
            request = build_tool_request(reference, index, item.action, item)
            fixtures.append(
                (
                    request,
                    ToolResponse(
                        request_id=request.request_id,
                        decision="ALLOW",
                        execution_status="SUCCEEDED",
                        reason_code="SYNTHETIC_SUCCESS",
                    ),
                )
            )
    gateway = SchedulingProbe(fixtures)
    model = MockModelProvider()
    service = GatewayOrchestrator(model, gateway)

    async def scenario():
        return await asyncio.gather(
            *(
                service.execute_task(reference, USER_REQUEST, inputs[reference])
                for reference in references
            )
        )

    results = asyncio.run(scenario())
    assert gateway.max_active == 1 and gateway.active == 0
    assert len(gateway.calls) == 6 and len(model.requests) == 2
    assert all(result.completed_action_count == 3 for result in results)
    for reference in references:
        assert (
            tuple(request.action for request in gateway.calls if request.task_ref == reference)
            == actions
        )


def test_checkpoint_and_public_results_exclude_raw_args_prompts_results_and_credentials():
    marker = "SYNTHETIC_PRIVATE_INPUT_MARKER"
    private_binding = binding(
        "email.send",
        arguments={"recipient": "teammate@example.test", "subject": "Synthetic", "body": marker},
    )
    service, model, _, bindings = setup(("email.send",), bindings=(private_binding,))
    model.private_credential = marker
    result = asyncio.run(service.execute_task(TASK, marker, bindings))
    for container in (
        service.checkpointer.storage,
        service.checkpointer.writes,
        service.checkpointer.blobs,
    ):
        assert marker not in repr(container)
        assert "SYNTHETIC_PRIVATE_RESULT_MARKER" not in repr(container)
    assert marker not in result.model_dump_json()
    for checkpoint in service.checkpointer.list(None):
        values = checkpoint.checkpoint["channel_values"]
        assert all(
            name not in values
            for name in (
                "user_request",
                "candidate_output",
                "pending_tool_request",
                "gateway_response",
            )
        )
        assert all(
            channel not in ("pending_tool_request", "gateway_response")
            for _, channel, _ in checkpoint.pending_writes
        )


def test_execution_uses_no_direct_files_smtp_shell_model_client_or_hosted_telemetry(monkeypatch):
    import langsmith

    service, _, gateway, bindings = setup(("files.read", "email.send"))

    def forbidden(*args, **kwargs):
        raise AssertionError("Direct protected execution is forbidden")

    for owner, name in (
        (builtins, "open"),
        (Path, "read_text"),
        (Path, "read_bytes"),
        (os, "open"),
        (os, "system"),
        (subprocess, "run"),
        (subprocess, "Popen"),
        (smtplib, "SMTP"),
        (NebiusModelProvider, "__init__"),
        (langsmith.Client, "__init__"),
    ):
        monkeypatch.setattr(owner, name, forbidden)
    result = execute(service, bindings)
    assert result.completed_action_count == len(gateway.calls) == 2
    assert os.environ["LANGSMITH_TRACING"] == os.environ["LANGCHAIN_TRACING_V2"] == "false"


def test_explicit_nano_provider_selection_remains_supported_without_model_routing():
    gateway = RecordingGateway()
    model = MockModelProvider(tier=ModelTier.NANO, output=plan_output(["tasks.list"]))
    service = GatewayOrchestrator(model, gateway, model_tier=ModelTier.NANO)
    result = execute(service, (binding("tasks.list"),))
    assert model.requested_tiers == [ModelTier.NANO]
    assert result.planning_result.model_tier == ModelTier.NANO


def test_result_contract_cannot_claim_success_after_denial():
    service, _, _, bindings = setup(outcomes=(("DENY", "NOT_EXECUTED"),))
    result = execute(service, bindings)
    with pytest.raises(ValidationError):
        AgentExecutionResult.model_validate(
            {**result.model_dump(), "execution_outcome": "ALL_ACTIONS_SUCCEEDED"}
        )
    row = result.action_results[0]
    with pytest.raises(ValidationError):
        ActionExecutionResult.model_validate({**row.model_dump(), "execution_status": "SUCCEEDED"})


def test_three_offline_demo_scenarios_and_simulation_labels(capsys):
    results = asyncio.run(run_scenarios())
    assert tuple(result.execution_outcome for result in results) == (
        ExecutionOutcome.ALL_ACTIONS_SUCCEEDED,
        ExecutionOutcome.DENIED,
        ExecutionOutcome.APPROVAL_REQUIRED,
    )
    asyncio.run(demo_main())
    output = capsys.readouterr().out
    assert "SIMULATED GATEWAY EXECUTION — NO REAL SIDE EFFECTS" in output
    assert "Scenario A: ALL_ACTIONS_SUCCEEDED" in output
    assert "Scenario B: DENIED" in output and "Scenario C: APPROVAL_REQUIRED" in output
    assert "No approval resume performed" in output
    assert "unauthorized@example.test" not in output
