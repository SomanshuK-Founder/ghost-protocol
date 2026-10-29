"""Sequential gateway orchestration; explicit opt-in trusted authorization-only transport."""

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Annotated

from langgraph.channels import UntrackedValue
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END
from langgraph.runtime import Runtime
from pydantic import ValidationError

from app.agent.execution_contracts import (
    ActionBinding,
    ActionExecutionResult,
    AgentExecutionResult,
    AuthorizationActionResult,
    AuthorizationAgentResult,
    ExecutionErrorCode,
    ExecutionInputError,
    ExecutionOptions,
    ExecutionOutcome,
    ExecutionProvenance,
)
from app.agent.gateway_protocol import (
    AuthorizationDecision,
    ExecutionStatus,
    ToolAction,
    ToolGateway,
    ToolRequest,
    ToolResponse,
)
from app.agent.graph import (
    AgentPlanner,
    _invoke_graph,
    _PlanningContext,
    _PlanningState,
    _to_result,
)
from app.agent.http_gateway import AuthenticatedHttpToolGateway
from app.agent.planning_contracts import PlanIntent, PlanningInput, PlanningOptions, PlanningOutcome
from app.agent.state import AgentTaskState, TaskStatus
from app.llm.config import ModelTier
from app.llm.contracts import ModelProvider


def build_tool_request(
    task_ref: str, action_index: int, action: ToolAction, binding: ActionBinding
) -> ToolRequest:
    """Canonical B0 validation precedes deterministic IDs; IDs never grant authority."""
    if (
        type(action_index) is not int
        or not 0 <= action_index < 10
        or binding.task_ref != task_ref
        or binding.action != action
    ):
        raise ExecutionInputError("Tool binding does not match the task action")
    request = ToolRequest(
        request_id="request-validation",
        task_ref=task_ref,
        action=action,
        purpose=binding.purpose,
        arguments=binding.arguments,
        idempotency_key="idempotency-validation",
    )
    payload = {
        "version": "B2.2a-v1",
        "action_index": action_index,
        **_logical_payload(request),
    }
    digest = sha256(_canonical(payload).encode("utf-8")).hexdigest()
    return ToolRequest.model_validate(
        {
            **request.model_dump(mode="python"),
            "request_id": f"req-b22a-{digest}",
            "idempotency_key": f"idem-b22a-{digest}",
        }
    )


def _logical_payload(request: ToolRequest) -> dict:
    return {
        name: value
        for name, value in request.model_dump(mode="json").items()
        if name not in ("request_id", "idempotency_key")
    }


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


class _ExecutionState(_PlanningState):
    current_action_index: int
    total_action_count: int
    execution_history: list[dict]
    terminal_outcome: str | None
    execution_error_code: str | None
    pending_approval_ref: str | None
    pending_request_ref: str | None
    gateway_error: str | None
    gateway_dispatched: bool
    pending_tool_request: Annotated[ToolRequest | None, UntrackedValue(ToolRequest)]
    gateway_response: Annotated[ToolResponse | None, UntrackedValue(ToolResponse)]


@dataclass(frozen=True)
class _ExecutionContext(_PlanningContext):
    bindings: tuple[ActionBinding, ...]


def _stop(outcome: ExecutionOutcome, error: ExecutionErrorCode | None = None) -> dict:
    return {
        "terminal_outcome": outcome.value,
        "execution_error_code": error.value if error is not None else None,
        "pending_tool_request": None,
        "gateway_response": None,
    }


class GatewayOrchestrator:
    """One shared planning pipeline plus bounded gateway nodes, not another agent.

    Supply the strict mock gateway or explicitly configured authorization adapter.
    Trusted mode never advances on authorization alone. Reuse a service/checkpointer;
    every admitted task is single-use, including failed and pending tasks.
    """

    def __init__(
        self,
        model_provider: ModelProvider,
        gateway: ToolGateway,
        model_tier: ModelTier = ModelTier.SUPER,
        *,
        planning_options: PlanningOptions | None = None,
        execution_options: ExecutionOptions | None = None,
        checkpointer: InMemorySaver | None = None,
        provenance: ExecutionProvenance = ExecutionProvenance.MOCK_SIMULATION,
    ) -> None:
        try:
            self.execution_options = ExecutionOptions.model_validate(
                (execution_options or ExecutionOptions()).model_dump(warnings=False)
            )
        except (ValueError, AttributeError, TypeError):
            raise ExecutionInputError("Invalid execution configuration") from None
        if not isinstance(provenance, ExecutionProvenance):
            raise ExecutionInputError("Trusted composition must select a provenance enum")
        authenticated = isinstance(gateway, AuthenticatedHttpToolGateway)
        trusted = provenance == ExecutionProvenance.TRUSTED_AUTHORIZATION_ONLY
        if (
            authenticated != trusted
            or (trusted and type(gateway) is not AuthenticatedHttpToolGateway)
            or (
                trusted
                and gateway.deadline_seconds >= self.execution_options.gateway_timeout_seconds
            )
        ):
            raise ExecutionInputError("Gateway transport and provenance configuration disagree")
        self._provenance = provenance
        self._action_result_type = AuthorizationActionResult if trusted else ActionExecutionResult
        self._execution_result_type = AuthorizationAgentResult if trusted else AgentExecutionResult
        self._planner = AgentPlanner(
            model_provider, model_tier, options=planning_options, checkpointer=checkpointer
        )
        self.checkpointer = self._planner.checkpointer
        self.model_tier = self._planner.model_tier
        self._gateway = gateway
        self._gateway_lock = self.checkpointer.__dict__.setdefault(
            "_ghost_b22a_gateway_lock", asyncio.Lock()
        )
        # A shared in-memory admission ledger closes the window before LangGraph's
        # first checkpoint, even across orchestrator instances sharing this saver.
        self._reserved_threads = self.checkpointer.__dict__.setdefault(
            "_ghost_b22a_reserved_threads", set()
        )
        self._graph = self._build_graph(model_provider)

    @property
    def recursion_limit(self) -> int:
        return 4 * self.execution_options.max_plan_actions + 8

    def _build_graph(self, provider: ModelProvider):
        builder = self._planner._build_graph_builder(
            provider,
            state_schema=_ExecutionState,
            context_schema=_ExecutionContext,
            valid_plan_target="select_next_action",
        )

        def select_next_action(state: _ExecutionState, runtime: Runtime[_ExecutionContext]) -> dict:
            plan = state["structured_plan"]
            actions = plan["proposed_actions"]
            if state["current_action_index"] == 0:
                metadata = {"total_action_count": len(actions)}
                if len(actions) > self.execution_options.max_plan_actions:
                    return {
                        **metadata,
                        **_stop(
                            ExecutionOutcome.ACTION_LIMIT_EXCEEDED,
                            ExecutionErrorCode.ACTION_LIMIT_EXCEEDED,
                        ),
                    }
                if plan["clarification_required"]:
                    return {
                        **metadata,
                        **_stop(
                            ExecutionOutcome.CLARIFICATION_REQUIRED,
                            ExecutionErrorCode.CLARIFICATION_REQUIRED,
                        ),
                    }
                if plan["intent"] == PlanIntent.UNSUPPORTED_OPERATION.value:
                    return {
                        **metadata,
                        **_stop(
                            ExecutionOutcome.UNSUPPORTED_OPERATION,
                            ExecutionErrorCode.UNSUPPORTED_OPERATION,
                        ),
                    }
                # Preflight every binding before any gateway call. No guessed IDs,
                # partial truncation, or duplicate semantic action dispatches.
                try:
                    if len(runtime.context.bindings) != len(actions):
                        raise ExecutionInputError("Missing or excess action bindings")
                    logical_actions = set()
                    for index, action in enumerate(actions):
                        request = build_tool_request(
                            state["task_ref"],
                            index,
                            ToolAction(action),
                            runtime.context.bindings[index],
                        )
                        identity = _canonical(_logical_payload(request))
                        if identity in logical_actions:
                            return {
                                **metadata,
                                **_stop(
                                    ExecutionOutcome.INVALID_TOOL_REQUEST,
                                    ExecutionErrorCode.DUPLICATE_ACTION,
                                ),
                            }
                        logical_actions.add(identity)
                except (ValidationError, ExecutionInputError, ValueError, TypeError):
                    return {
                        **metadata,
                        **_stop(
                            ExecutionOutcome.INVALID_TOOL_REQUEST,
                            ExecutionErrorCode.INVALID_TOOL_REQUEST,
                        ),
                    }
            if state["current_action_index"] == len(actions):
                return {
                    "total_action_count": len(actions),
                    **_stop(
                        ExecutionOutcome.ALL_ACTIONS_SUCCEEDED
                        if actions
                        else ExecutionOutcome.NO_ACTIONS
                    ),
                }
            index = state["current_action_index"]
            request = build_tool_request(
                state["task_ref"],
                index,
                ToolAction(actions[index]),
                runtime.context.bindings[index],
            )
            return {
                "task_status": TaskStatus.RUNNING.value,
                "total_action_count": len(actions),
                "pending_tool_request": request,
                "gateway_response": None,
                "gateway_error": None,
                "gateway_dispatched": False,
            }

        def validate_tool_request(state: _ExecutionState) -> dict:
            try:
                request = ToolRequest.model_validate(
                    state["pending_tool_request"].model_dump(mode="python", warnings=False)
                )
                index = state["current_action_index"]
                if (
                    request.task_ref != state["task_ref"]
                    or request.action != state["structured_plan"]["proposed_actions"][index]
                    or request.request_id
                    in {row["request_ref"] for row in state["execution_history"]}
                ):
                    raise ExecutionInputError("Invalid or duplicate tool request")
                return {"pending_tool_request": request}
            except (ValidationError, ExecutionInputError, AttributeError, ValueError, TypeError):
                return _stop(
                    ExecutionOutcome.INVALID_TOOL_REQUEST, ExecutionErrorCode.INVALID_TOOL_REQUEST
                )

        async def call_mock_gateway(state: _ExecutionState) -> dict:
            dispatched = False
            try:
                async with asyncio.timeout(self.execution_options.gateway_timeout_seconds):
                    async with self._gateway_lock:
                        dispatched = True
                        response = await self._gateway.execute(state["pending_tool_request"])
            except TimeoutError:
                category = ExecutionErrorCode.GATEWAY_TIMEOUT
            except Exception:
                category = ExecutionErrorCode.GATEWAY_UNAVAILABLE
            else:
                try:
                    if not isinstance(response, ToolResponse):
                        raise ValueError("Invalid gateway response type")
                    response = ToolResponse.model_validate(
                        response.model_dump(mode="python", warnings=False)
                    )
                    if response.request_id != state["pending_tool_request"].request_id:
                        raise ValueError("Gateway response request mismatch")
                    return {"gateway_response": response, "gateway_dispatched": dispatched}
                except (ValidationError, ValueError, TypeError, AttributeError):
                    category = ExecutionErrorCode.INVALID_GATEWAY_RESPONSE
            return {
                "gateway_error": category.value,
                "gateway_dispatched": dispatched,
                "gateway_response": None,
            }

        def process_gateway_response(state: _ExecutionState) -> dict:
            request = state["pending_tool_request"]
            response = state["gateway_response"]
            error = ExecutionErrorCode(state["gateway_error"]) if state["gateway_error"] else None
            if error is not None:
                row = self._action_result_type(
                    action_index=state["current_action_index"],
                    action=request.action,
                    request_ref=request.request_id,
                    idempotency_key=request.idempotency_key,
                    decision=None,
                    execution_status=ExecutionStatus.UNKNOWN
                    if state["gateway_dispatched"]
                    else ExecutionStatus.NOT_EXECUTED,
                    reason_code=None,
                    error_code=error,
                )
                outcome = (
                    ExecutionOutcome.EXECUTION_UNKNOWN
                    if (error == ExecutionErrorCode.INVALID_GATEWAY_RESPONSE)
                    else ExecutionOutcome.GATEWAY_UNAVAILABLE
                )
            else:
                if response.decision == AuthorizationDecision.DENY:
                    outcome, error = ExecutionOutcome.DENIED, ExecutionErrorCode.GATEWAY_DENIED
                elif response.decision == AuthorizationDecision.APPROVAL_REQUIRED:
                    outcome = ExecutionOutcome.APPROVAL_REQUIRED
                elif response.execution_status == ExecutionStatus.SUCCEEDED:
                    outcome = None
                elif response.execution_status == ExecutionStatus.UNKNOWN:
                    outcome, error = (
                        ExecutionOutcome.EXECUTION_UNKNOWN,
                        ExecutionErrorCode.GATEWAY_EXECUTION_UNKNOWN,
                    )
                else:
                    outcome = ExecutionOutcome.EXECUTION_FAILED
                    error = (
                        ExecutionErrorCode.GATEWAY_EXECUTION_FAILED
                        if (response.execution_status == ExecutionStatus.FAILED)
                        else ExecutionErrorCode.GATEWAY_NOT_EXECUTED
                    )
                row = self._action_result_type(
                    action_index=state["current_action_index"],
                    action=request.action,
                    request_ref=request.request_id,
                    idempotency_key=request.idempotency_key,
                    decision=response.decision,
                    execution_status=response.execution_status,
                    reason_code=response.reason_code,
                    audit_event_ref=response.audit_event_ref,
                    approval_ref=response.approval_ref
                    if (response.decision == AuthorizationDecision.APPROVAL_REQUIRED)
                    else None,
                    error_code=error,
                )
            updates = {
                "execution_history": [*state["execution_history"], row.model_dump(mode="json")],
                "gateway_response": None,
                "pending_tool_request": None,
            }
            if outcome is None:
                return {**updates, "current_action_index": state["current_action_index"] + 1}
            updates.update(_stop(outcome, error))
            if outcome == ExecutionOutcome.APPROVAL_REQUIRED:
                updates.update(
                    pending_approval_ref=row.approval_ref, pending_request_ref=row.request_ref
                )
            return updates

        def finish_execution(state: _ExecutionState) -> dict:
            outcome = ExecutionOutcome(state["terminal_outcome"])
            status = (
                TaskStatus.AWAITING_APPROVAL
                if (outcome == ExecutionOutcome.APPROVAL_REQUIRED)
                else TaskStatus.COMPLETED
                if outcome in (ExecutionOutcome.ALL_ACTIONS_SUCCEEDED, ExecutionOutcome.NO_ACTIONS)
                else TaskStatus.FAILED
            )
            return {
                "task_status": status.value,
                "user_request": "",
                "candidate_output": None,
                "pending_tool_request": None,
                "gateway_response": None,
            }

        def route(state: _ExecutionState) -> str:
            return "stop" if state["terminal_outcome"] is not None else "continue"

        builder.add_node("select_next_action", select_next_action)
        builder.add_node("validate_tool_request", validate_tool_request)
        builder.add_node("call_mock_gateway", call_mock_gateway)
        builder.add_node("process_gateway_response", process_gateway_response)
        builder.add_node("finish_execution", finish_execution)
        builder.add_conditional_edges(
            "select_next_action",
            route,
            {"stop": "finish_execution", "continue": "validate_tool_request"},
        )
        builder.add_conditional_edges(
            "validate_tool_request",
            route,
            {"stop": "finish_execution", "continue": "call_mock_gateway"},
        )
        builder.add_edge("call_mock_gateway", "process_gateway_response")
        builder.add_conditional_edges(
            "process_gateway_response",
            route,
            {"stop": "finish_execution", "continue": "select_next_action"},
        )
        builder.add_edge("finish_execution", END)
        return builder.compile(checkpointer=self.checkpointer)

    async def execute_task(
        self, task_ref: str, user_request: str, bindings: Sequence[ActionBinding] = ()
    ) -> AgentExecutionResult:
        if (
            self._provenance == ExecutionProvenance.TRUSTED_AUTHORIZATION_ONLY
            and task_ref != self._gateway.task_ref
        ):
            raise ExecutionInputError("Task must match the configured trusted gateway")
        try:
            request = PlanningInput(
                task_ref=task_ref, user_request=user_request, model_tier=self.model_tier
            )
            if len(bindings) > 10:
                raise ExecutionInputError("Too many action bindings")
            snapshots = tuple(
                ActionBinding.model_validate_json(
                    binding.model_dump_json(warnings=False), strict=True
                )
                for binding in bindings
            )
        except (ValidationError, AttributeError, TypeError, ValueError):
            raise ExecutionInputError("Invalid execution input") from None
        thread = f"b22a-{request.task_ref}"
        if (
            thread in self._reserved_threads
            or self.checkpointer.get_tuple({"configurable": {"thread_id": thread}}) is not None
        ):
            raise ExecutionInputError("Task execution cannot be repeated in B2.2a")
        self._reserved_threads.add(thread)  # No awaits before admission; single event loop.
        state = await _invoke_graph(
            self._graph,
            {
                "task_ref": request.task_ref,
                "skill_id": request.skill_id,
                "model_tier": self.model_tier.value,
                "task_status": TaskStatus.CREATED.value,
                "structured_plan": None,
                "error_code": None,
                "retry_count": 0,
                "correlation_ref": None,
                "response_task_ref": None,
                "outcome": None,
                "current_action_index": 0,
                "total_action_count": 0,
                "execution_history": [],
                "terminal_outcome": None,
                "execution_error_code": None,
                "pending_approval_ref": None,
                "pending_request_ref": None,
                "gateway_error": None,
                "gateway_dispatched": False,
            },
            _ExecutionContext(request.user_request, snapshots),
            thread_id=thread,
            recursion_limit=self.recursion_limit,
        )
        return self._to_execution_result(state)

    def _to_execution_result(self, state: _ExecutionState) -> AgentExecutionResult:
        planning_state = dict(state)
        plan = state["structured_plan"]
        if plan is not None:
            planning_state.update(
                task_status=TaskStatus.COMPLETED.value,
                outcome=(
                    PlanningOutcome.UNSUPPORTED_OPERATION.value
                    if plan["intent"] == PlanIntent.UNSUPPORTED_OPERATION.value
                    else PlanningOutcome.CLARIFICATION_REQUIRED.value
                    if plan["clarification_required"]
                    else PlanningOutcome.PLAN_READY.value
                ),
                error_code=None,
            )
        planning = _to_result(planning_state)
        outcome = state["terminal_outcome"] or ExecutionOutcome.PLANNING_FAILED.value
        error = state["execution_error_code"] or (
            ExecutionErrorCode.PLANNING_FAILED.value if plan is None else None
        )
        history = tuple(
            self._action_result_type.model_validate(row) for row in state["execution_history"]
        )
        return self._execution_result_type(
            task_ref=state["task_ref"],
            task_state=AgentTaskState(
                task_ref=state["task_ref"],
                skill_id=state["skill_id"],
                status=state["task_status"],
                pending_request_ref=state["pending_request_ref"],
                approval_ref=state["pending_approval_ref"],
                retry_count=0,
                last_error=error,
            ),
            planning_result=planning,
            execution_outcome=outcome,
            completed_action_count=sum(
                row.decision == AuthorizationDecision.ALLOW
                and row.execution_status == ExecutionStatus.SUCCEEDED
                for row in history
            ),
            total_action_count=state["total_action_count"],
            action_results=history,
            pending_approval_ref=state["pending_approval_ref"],
            error_code=error,
        )
