"""B2.1 tests use isolated synthetic values; never load fixtures/ghost_demo or .env."""

import asyncio
import builtins
import json
import os
import smtplib
import socket
import subprocess
from contextvars import ContextVar
from pathlib import Path

import httpx
import pytest
from langchain_core.globals import set_debug, set_verbose
from pydantic import ValidationError

from app.agent.demo_plan import main as demo_main
from app.agent.graph import GRAPH_RECURSION_LIMIT, AgentPlanner, plan_task
from app.agent.mock_gateway import MockToolGateway
from app.agent.mock_model_provider import MockModelProvider, MockPlanningScenario
from app.agent.planning_contracts import (
    AgentPlanningResult,
    PlanIntent,
    PlanningInputError,
    PlanningOptions,
    PlanningOutcome,
    TaskPlan,
)
from app.agent.state import AgentTaskState, TaskStatus
from app.llm.config import InferenceMode, ModelTier, NebiusSettings
from app.llm.contracts import InferenceResponse, ModelProvider
from app.llm.errors import ErrorCategory
from app.llm.nebius_provider import NebiusModelProvider

TASK = "task-b21-synthetic"
REQUEST = "Summarize a synthetic project report and prepare an email."


@pytest.fixture(autouse=True)
def forbid_external_network(monkeypatch: pytest.MonkeyPatch):
    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("External network call forbidden in B2.1 tests")

    connect, connect_ex = socket.socket.connect, socket.socket.connect_ex

    def local_connect(self, address):
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return connect(self, address)
        return forbidden()

    def local_connect_ex(self, address):
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return connect_ex(self, address)
        return forbidden()

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", local_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", local_connect_ex)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    yield attempts
    assert not attempts


def payload(**overrides) -> dict:
    return {
        "task_ref": TASK,
        "intent": "summarize_and_prepare_email",
        "proposed_actions": ["files.list_authorized", "files.read", "email.draft"],
        "requires_external_action": True,
        "clarification_required": False,
        **overrides,
    }


def run(provider: ModelProvider | None = None, **kwargs) -> AgentPlanningResult:
    return asyncio.run(plan_task(TASK, REQUEST, provider or MockModelProvider(), **kwargs))


def assert_failed(result: AgentPlanningResult, category: ErrorCategory) -> None:
    assert result.task_state.status == TaskStatus.FAILED
    assert result.task_state.last_error == category.value
    assert result.error_code == category
    assert result.outcome == PlanningOutcome.FAILED
    assert result.structured_plan is None
    assert result.task_state.retry_count == 0
    assert result.task_state.pending_request_ref is None
    assert result.task_state.approval_ref is None


def test_graph_compiles_with_explicit_nodes_and_no_back_edges() -> None:
    graph = AgentPlanner(MockModelProvider())._graph.get_graph()
    assert set(graph.nodes) == {
        "__start__",
        "initialize",
        "interpret_task",
        "validate_plan",
        "completed",
        "failed",
        "__end__",
    }
    edges = {(edge.source, edge.target) for edge in graph.edges}
    assert edges == {
        ("__start__", "initialize"),
        ("initialize", "interpret_task"),
        ("interpret_task", "validate_plan"),
        ("interpret_task", "failed"),
        ("validate_plan", "completed"),
        ("validate_plan", "failed"),
        ("completed", "__end__"),
        ("failed", "__end__"),
    }
    assert sum(edge.conditional for edge in graph.edges) == 4
    assert GRAPH_RECURSION_LIMIT == 6


def test_initialization_and_terminal_result_keep_b0_state_compatible() -> None:
    planner = AgentPlanner(MockModelProvider())
    result = asyncio.run(planner.plan_task(TASK, REQUEST))
    assert isinstance(result.task_state, AgentTaskState)
    assert (
        AgentTaskState.model_validate_json(result.task_state.model_dump_json()) == result.task_state
    )
    assert AgentPlanningResult.model_validate_json(result.model_dump_json()) == result
    assert result.task_state.skill_id == "task-planning"
    assert result.task_state.status == TaskStatus.COMPLETED
    assert result.task_state.last_error is None
    assert result.task_state.pending_request_ref is None and result.task_state.approval_ref is None
    assert result.task_state.retry_count == 0
    assert result.structured_plan.task_ref == result.task_state.task_ref == TASK
    states = [
        item.checkpoint["channel_values"]
        for item in planner.checkpointer.list({"configurable": {"thread_id": f"b21-{TASK}"}})
    ]
    statuses = [state.get("task_status") for state in states]
    assert "CREATED" in statuses and "PLANNING" in statuses and "COMPLETED" in statuses
    assert "RUNNING" not in statuses and "AWAITING_APPROVAL" not in statuses


@pytest.mark.parametrize("tier", [ModelTier.SUPER, ModelTier.NANO])
def test_single_provider_call_carries_schema_task_request_and_explicit_tier(
    tier: ModelTier,
) -> None:
    provider = MockModelProvider(tier=tier)
    result = run(provider, model_tier=tier)
    assert result.model_tier == tier
    assert provider.requested_tiers == [tier]
    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.task_ref == TASK and request.input_data["user_request"] == REQUEST
    assert request.input_data["model_tier"] == tier.value
    assert request.output_schema == TaskPlan.model_json_schema()
    assert "never authorize or execute" in request.input_data["planning_instruction"]
    assert request.output_schema["additionalProperties"] is False
    assert set(request.output_schema["$defs"]["ToolAction"]["enum"]) == {
        "files.list_authorized",
        "files.read",
        "email.draft",
        "email.send",
        "tasks.list",
    }


def test_default_tier_is_super_and_no_live_telemetry_is_invented() -> None:
    provider = MockModelProvider()
    result = run(provider)
    assert result.model_tier == ModelTier.SUPER and provider.requested_tiers == [ModelTier.SUPER]
    assert result.correlation_ref == "mock-planning-1"
    assert provider.requests[0].input_data.keys() == {
        "planning_instruction",
        "user_request",
        "skill_id",
        "model_tier",
    }


def test_protocol_only_provider_requires_no_new_methods_or_tier_arguments() -> None:
    mock = MockModelProvider(tier=ModelTier.NANO)

    class ProtocolOnly:
        async def infer(self, request):
            return await mock.infer(request)

    result = run(ProtocolOnly(), model_tier=ModelTier.NANO)
    assert result.model_tier == ModelTier.NANO and len(mock.requests) == 1


@pytest.mark.parametrize(
    "mode", [InferenceMode.TEXT, InferenceMode.JSON_REQUEST, InferenceMode.TOOL_CALL]
)
def test_wrong_provider_mode_fails_before_inference(mode: InferenceMode) -> None:
    provider = MockModelProvider()
    provider.mode = mode
    assert_failed(run(provider), ErrorCategory.CONFIGURATION)
    assert provider.requests == []


def test_tier_mismatch_cannot_silently_substitute_nano_for_super() -> None:
    provider = MockModelProvider(tier=ModelTier.NANO)
    assert_failed(run(provider), ErrorCategory.CONFIGURATION)
    assert provider.requests == []


@pytest.mark.parametrize(
    "action", ["files.list_authorized", "files.read", "email.draft", "email.send", "tasks.list"]
)
def test_existing_action_identifiers_are_validated_proposals_only(action: str) -> None:
    result = run(MockModelProvider(output=payload(proposed_actions=[action])))
    assert result.outcome == PlanningOutcome.PLAN_READY
    assert result.structured_plan.proposed_actions == (action,)
    assert "decision" not in result.model_dump_json()
    assert "ALLOW" not in result.model_dump_json()


@pytest.mark.parametrize(
    "overrides",
    [
        {"proposed_actions": ["shell.exec"]},
        {"proposed_actions": ["smtp.send"]},
        {"proposed_actions": ["http.fetch"]},
        {"proposed_actions": [{"action": "email.send", "allow": True}]},
        {"allow": True},
        {"decision": "ALLOW"},
        {"authorization": "ALLOW"},
        {"policy_update": {}},
        {"requires_external_action": "true"},
        {"clarification_required": "false"},
        {"intent": "execute_shell"},
        {"task_ref": "another-task"},
        {"task_ref": 123},
        {"proposed_actions": "email.send"},
        {"proposed_actions": ["email.send"] * 11},
        {"proposed_actions": [], "requires_external_action": True},
        {"requires_external_action": False},
        {"clarification_required": True},
        {"intent": "unsupported_operation"},
        {"intent": "clarify_request"},
    ],
)
def test_invalid_plans_fail_closed_without_repair_or_repeated_inference(overrides: dict) -> None:
    provider = MockModelProvider(output=payload(**overrides))
    result = run(provider)
    assert_failed(result, ErrorCategory.SCHEMA_MISMATCH)
    assert len(provider.requests) == 1


@pytest.mark.parametrize("missing", list(payload()))
def test_all_plan_fields_are_required(missing: str) -> None:
    output = payload()
    del output[missing]
    assert_failed(run(MockModelProvider(output=output)), ErrorCategory.SCHEMA_MISMATCH)


@pytest.mark.parametrize(
    ("scenario", "outcome", "intent"),
    [
        (
            MockPlanningScenario.EMPTY_ACTIONS,
            PlanningOutcome.PLAN_READY,
            PlanIntent.ANSWER_QUESTION,
        ),
        (
            MockPlanningScenario.AMBIGUOUS,
            PlanningOutcome.CLARIFICATION_REQUIRED,
            PlanIntent.CLARIFY_REQUEST,
        ),
        (
            MockPlanningScenario.UNSUPPORTED_OPERATION,
            PlanningOutcome.UNSUPPORTED_OPERATION,
            PlanIntent.UNSUPPORTED_OPERATION,
        ),
    ],
)
def test_empty_ambiguous_and_unsupported_tasks_have_explicit_outcomes(scenario, outcome, intent):
    result = run(MockModelProvider(scenario=scenario))
    assert result.task_state.status == TaskStatus.COMPLETED  # The planning stage alone is complete.
    assert result.outcome == outcome and result.structured_plan.intent == intent
    assert result.structured_plan.proposed_actions == ()
    assert not result.structured_plan.requires_external_action
    assert result.structured_plan.clarification_required == (
        outcome == PlanningOutcome.CLARIFICATION_REQUIRED
    )


@pytest.mark.parametrize(
    ("scenario", "category"),
    [
        (MockPlanningScenario.MALFORMED_JSON, ErrorCategory.INVALID_JSON),
        (MockPlanningScenario.INVALID_SCHEMA, ErrorCategory.SCHEMA_MISMATCH),
        (MockPlanningScenario.UNKNOWN_ACTION, ErrorCategory.SCHEMA_MISMATCH),
        (MockPlanningScenario.TIMEOUT, ErrorCategory.TIMEOUT),
        (MockPlanningScenario.AUTHENTICATION, ErrorCategory.AUTHENTICATION),
    ],
)
def test_mock_failure_scenarios_are_structured_and_deterministic(scenario, category) -> None:
    provider = MockModelProvider(scenario=scenario)
    assert_failed(run(provider), category)
    assert len(provider.requests) == 1


@pytest.mark.parametrize("category", list(ErrorCategory))
def test_all_sanitized_b1_model_failures_propagate_without_graph_retries(category: ErrorCategory):
    provider = MockModelProvider(failure=category)
    assert_failed(run(provider), category)
    assert len(provider.requests) == 1


@pytest.mark.parametrize("failure", [TimeoutError, RuntimeError])
def test_raw_provider_failures_never_expose_error_text(failure) -> None:
    class FailingProvider:
        async def infer(self, request):
            raise failure("SYNTHETIC_SECRET_ERROR_CONTENT")

    result = run(FailingProvider())
    assert_failed(
        result, ErrorCategory.TIMEOUT if failure is TimeoutError else ErrorCategory.INTERNAL
    )
    assert "SYNTHETIC_SECRET_ERROR_CONTENT" not in result.model_dump_json()


def test_wrong_response_task_binding_is_rejected_even_when_plan_binding_is_correct() -> None:
    class WrongEnvelope(MockModelProvider):
        async def infer(self, request):
            return (await super().infer(request)).model_copy(update={"task_ref": "wrong-task"})

    assert_failed(run(WrongEnvelope()), ErrorCategory.SCHEMA_MISMATCH)


@pytest.mark.parametrize("output", ["malformed JSON", [], {"unexpected": True}])
def test_response_contract_bypasses_are_revalidated(output, recwarn) -> None:
    class BypassedProvider:
        async def infer(self, request):
            return InferenceResponse.model_construct(
                task_ref=TASK, output=output, correlation_ref="mock-bypass"
            )

    result = run(BypassedProvider())
    assert_failed(
        result,
        ErrorCategory.SCHEMA_MISMATCH
        if isinstance(output, dict)
        else ErrorCategory.MALFORMED_RESPONSE,
    )
    assert not recwarn  # Serializer warnings must not disclose raw provider values.


@pytest.mark.parametrize(
    ("task_ref", "user_request"),
    [
        ("../secret", REQUEST),
        ("", REQUEST),
        ("x" * 129, REQUEST),
        (TASK, ""),
        (TASK, "  "),
        (TASK, "x" * 4001),
        (TASK, 4),
    ],
)
def test_invalid_caller_input_is_rejected_before_any_checkpoint_or_inference(
    task_ref, user_request
):
    provider = MockModelProvider()
    planner = AgentPlanner(provider)
    with pytest.raises(PlanningInputError, match="Invalid planning input"):
        asyncio.run(planner.plan_task(task_ref, user_request))
    assert provider.requests == [] and not planner.checkpointer.storage


def test_unknown_skill_and_model_tier_are_rejected() -> None:
    planner = AgentPlanner(MockModelProvider())
    with pytest.raises(PlanningInputError):
        asyncio.run(planner.plan_task(TASK, REQUEST, skill_id="unknown-skill"))
    with pytest.raises(PlanningInputError):
        AgentPlanner(MockModelProvider(), model_tier="ULTRA")


@pytest.mark.parametrize("seconds", [0, -1, float("inf"), 421])
def test_inference_deadline_is_configurable_and_bounded(seconds):
    with pytest.raises(ValidationError):
        PlanningOptions(inference_timeout_seconds=seconds)


def test_outer_deadline_is_used_without_flaky_clock_based_assertions(monkeypatch):
    configured = []

    class SyntheticDeadline:
        async def __aenter__(self):
            pass

        async def __aexit__(self, *args):
            raise TimeoutError("SYNTHETIC_TIMEOUT_DETAIL")

    def deadline(seconds):
        configured.append(seconds)
        return SyntheticDeadline()

    monkeypatch.setattr(asyncio, "timeout", deadline)
    provider = MockModelProvider()
    assert_failed(
        run(provider, options=PlanningOptions(inference_timeout_seconds=90)), ErrorCategory.TIMEOUT
    )
    assert configured == [90] and len(provider.requests) == 1


def test_checkpoint_threads_are_isolated_even_for_concurrent_tasks() -> None:
    provider = MockModelProvider()
    planner = AgentPlanner(provider)

    async def scenario():
        return await asyncio.gather(
            planner.plan_task("task-isolation-a", "Synthetic request A"),
            planner.plan_task("task-isolation-b", "Synthetic request B"),
        )

    results = asyncio.run(scenario())
    assert len(provider.requests) == 2
    assert set(planner.checkpointer.storage) == {"b21-task-isolation-a", "b21-task-isolation-b"}
    for result in results:
        reference = result.task_state.task_ref
        checkpoint = planner.checkpointer.get_tuple(
            {"configurable": {"thread_id": f"b21-{reference}"}}
        )
        assert checkpoint.checkpoint["channel_values"]["task_ref"] == reference
        assert checkpoint.checkpoint["channel_values"]["structured_plan"]["task_ref"] == reference


def test_reused_task_thread_resets_previous_plan_and_errors() -> None:
    provider = MockModelProvider()
    planner = AgentPlanner(provider)
    first = asyncio.run(planner.plan_task(TASK, REQUEST))
    provider.scenario = MockPlanningScenario.AUTHENTICATION
    second = asyncio.run(planner.plan_task(TASK, "Synthetic new request"))
    assert first.structured_plan is not None
    assert_failed(second, ErrorCategory.AUTHENTICATION)
    provider.scenario = MockPlanningScenario.VALID
    third = asyncio.run(planner.plan_task(TASK, REQUEST))
    assert third.structured_plan is not None and third.error_code is None
    assert len(provider.requests) == 3


def test_concurrent_same_reference_is_rejected_before_second_inference() -> None:
    started, release = None, None

    class PausingMock(MockModelProvider):
        async def infer(self, request):
            started.set()
            await release.wait()
            return await super().infer(request)

    provider = PausingMock()
    planner = AgentPlanner(provider)

    async def scenario():
        nonlocal started, release
        started, release = asyncio.Event(), asyncio.Event()
        active = asyncio.create_task(planner.plan_task(TASK, REQUEST))
        await started.wait()
        try:
            with pytest.raises(PlanningInputError, match="already being planned"):
                await planner.plan_task(TASK, REQUEST)
        finally:
            release.set()
        return await active

    result = asyncio.run(scenario())
    assert result.outcome == PlanningOutcome.PLAN_READY and len(provider.requests) == 1
    assert not planner._active_tasks


def test_checkpoint_storage_contains_no_provider_credentials_requests_or_invalid_output() -> None:
    marker = "SYNTHETIC_PRIVATE_CHECKPOINT_MARKER"
    provider = MockModelProvider(output=payload(api_key=marker))
    provider.private_credential = marker  # Simulates a configured provider, never graph state.
    planner = AgentPlanner(provider)
    result = asyncio.run(planner.plan_task(TASK, marker))
    assert_failed(result, ErrorCategory.SCHEMA_MISMATCH)
    for container in (
        planner.checkpointer.storage,
        planner.checkpointer.writes,
        planner.checkpointer.blobs,
    ):
        assert marker not in repr(container)
        assert "private_credential" not in repr(container)
    for item in planner.checkpointer.list(None):
        # Channel-version metadata can contain field names, never their raw values.
        values = item.checkpoint["channel_values"]
        assert "user_request" not in values and "candidate_output" not in values
        assert all(
            channel not in ("user_request", "candidate_output")
            for _, channel, _ in item.pending_writes
        )
    assert marker not in result.model_dump_json()


def test_new_planner_has_no_previous_instance_checkpoints() -> None:
    first = AgentPlanner(MockModelProvider())
    asyncio.run(first.plan_task(TASK, REQUEST))
    second = AgentPlanner(MockModelProvider())
    assert first.checkpointer.storage and not second.checkpointer.storage


def test_raw_exception_text_is_absent_from_all_checkpoint_storage() -> None:
    class FailingProvider:
        async def infer(self, request):
            raise RuntimeError("SYNTHETIC_PRIVATE_EXCEPTION_MARKER")

    planner = AgentPlanner(FailingProvider())
    assert_failed(asyncio.run(planner.plan_task(TASK, REQUEST)), ErrorCategory.INTERNAL)
    for container in (
        planner.checkpointer.storage,
        planner.checkpointer.writes,
        planner.checkpointer.blobs,
    ):
        assert "SYNTHETIC_PRIVATE_EXCEPTION_MARKER" not in repr(container)


def test_provider_cancellation_is_a_safe_failure_without_retry() -> None:
    class CancelledProvider:
        async def infer(self, request):
            raise asyncio.CancelledError()

    planner = AgentPlanner(CancelledProvider())
    assert_failed(asyncio.run(planner.plan_task(TASK, REQUEST)), ErrorCategory.CANCELLED)
    assert not planner._active_tasks


def test_caller_cancellation_propagates_and_releases_task_reservation() -> None:
    class WaitingProvider:
        async def infer(self, request):
            started.set()
            await asyncio.Event().wait()

    planner = AgentPlanner(WaitingProvider())

    async def scenario():
        nonlocal started
        started = asyncio.Event()
        active = asyncio.create_task(planner.plan_task(TASK, REQUEST))
        await started.wait()
        active.cancel()
        with pytest.raises(asyncio.CancelledError):
            await active

    started = None
    asyncio.run(scenario())
    assert not planner._active_tasks


def test_langsmith_client_is_never_constructed(monkeypatch) -> None:
    import langsmith

    def forbidden(*args, **kwargs):
        raise AssertionError("LangSmith service/client use is not authorized")

    monkeypatch.setattr(langsmith.Client, "__init__", forbidden)
    assert run().outcome == PlanningOutcome.PLAN_READY


def test_cached_or_global_tracing_is_refused_before_checkpoints_or_model_calls(monkeypatch) -> None:
    # Simulate the dependency's detection predicate; never enable a real tracer.
    monkeypatch.setattr("app.agent.graph._tracing_v2_is_enabled", lambda: True)
    provider = MockModelProvider()
    planner = AgentPlanner(provider)
    with pytest.raises(PlanningInputError, match="External tracing"):
        asyncio.run(planner.plan_task(TASK, REQUEST))
    assert not provider.requests and not planner.checkpointer.storage


def test_non_memory_checkpointer_is_refused() -> None:
    with pytest.raises(PlanningInputError, match="in-memory"):
        AgentPlanner(MockModelProvider(), checkpointer=object())


def test_no_files_shell_smtp_gateway_or_new_model_client_are_used(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("Planning must not execute protected operations")

    # Compile before guards; the graph owns no executor or SDK client.
    planner = AgentPlanner(MockModelProvider())
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(os, "open", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(smtplib, "SMTP", forbidden)
    monkeypatch.setattr(MockToolGateway, "execute", forbidden)
    monkeypatch.setattr(NebiusModelProvider, "__init__", forbidden)
    assert asyncio.run(planner.plan_task(TASK, REQUEST)).outcome == PlanningOutcome.PLAN_READY


def test_tracing_flags_are_forced_false_and_caller_context_is_not_inherited(monkeypatch) -> None:
    marker = ContextVar("synthetic-caller-context", default=False)

    class ObservingMock(MockModelProvider):
        async def infer(self, request):
            assert not marker.get()
            assert os.environ["LANGSMITH_TRACING"] == "false"
            assert os.environ["LANGCHAIN_TRACING_V2"] == "false"
            return await super().infer(request)

    for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING_V2"):
        monkeypatch.setenv(name, "true")
    token = marker.set(True)
    try:
        result = run(ObservingMock())
    finally:
        marker.reset(token)
    assert result.outcome == PlanningOutcome.PLAN_READY


@pytest.mark.parametrize("setter", [set_debug, set_verbose])
def test_framework_debug_and_verbose_are_refused_before_inference(setter) -> None:
    provider = MockModelProvider()
    setter(True)
    try:
        with pytest.raises(PlanningInputError, match="debug and verbose"):
            run(provider)
    finally:
        setter(False)
    assert not provider.requests


def test_existing_nebius_provider_native_schema_integration_uses_mock_http_only() -> None:
    calls = []

    def handler(request):
        wire = json.loads(request.content)
        calls.append(wire)
        return httpx.Response(
            200,
            json={
                "id": "mock-nebius-planning",
                "object": "chat.completion",
                "created": 1,
                "model": "synthetic-super",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(payload())},
                    }
                ],
            },
        )

    config = NebiusSettings(
        api_key="synthetic-offline-credential",
        base_url="https://inference.example.test/v1/",
        model_super="synthetic-super",
        max_attempts=1,
        max_tokens=512,
    )

    async def scenario():
        async with NebiusModelProvider(
            config,
            mode=InferenceMode.JSON_SCHEMA,
            response_model=TaskPlan,
            transport=httpx.MockTransport(handler),
        ) as provider:
            return await plan_task(TASK, REQUEST, provider)

    result = asyncio.run(scenario())
    assert result.outcome == PlanningOutcome.PLAN_READY and len(calls) == 1
    assert calls[0]["response_format"]["type"] == "json_schema"
    assert calls[0]["response_format"]["json_schema"]["strict"] is True
    assert calls[0]["response_format"]["json_schema"]["schema"] == TaskPlan.model_json_schema()
    assert (
        calls[0]["max_tokens"] == 512 and NebiusSettings.model_fields["max_tokens"].default == 256
    )


def test_mock_fixtures_are_copied_and_outputs_do_not_mutate_subsequent_calls() -> None:
    source = payload()
    provider = MockModelProvider(output=source)
    source["proposed_actions"].append("shell.exec")
    first = run(provider)
    second = run(provider)
    assert first.structured_plan == second.structured_plan
    assert len(provider.requests) == 2


def test_plan_and_result_contracts_reject_mutation_and_authority_fields() -> None:
    plan = TaskPlan.model_validate_json(json.dumps(payload()), strict=True)
    with pytest.raises(ValidationError):
        plan.intent = PlanIntent.UNSUPPORTED_OPERATION
    with pytest.raises(ValidationError):
        AgentPlanningResult(**run().model_dump(), allow=True)


def test_offline_demo_is_explicitly_simulated_and_uses_one_mock_call(capsys) -> None:
    asyncio.run(demo_main())
    output = capsys.readouterr().out
    assert "SIMULATED PLANNING — NO ACTIONS EXECUTED" in output
    assert "Mock inference calls: 1; tools executed: 0" in output
    assert "files.list_authorized, files.read, email.draft" in output
    assert "teammate" not in output and REQUEST not in output
