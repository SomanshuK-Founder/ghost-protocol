"""Additive B2.2a simulation contracts; no changes to B0/B1/B2.1 wire interfaces."""

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, JsonValue, model_validator

from app.agent.gateway_protocol import (
    AuthorizationDecision,
    BoundedText,
    ContractModel,
    ExecutionStatus,
    OpaqueReference,
    ToolAction,
)
from app.agent.planning_contracts import AgentPlanningResult, PlanningOutcome
from app.agent.state import AgentTaskState, TaskStatus

MAX_PLAN_ACTIONS = 5


class ExecutionProvenance(StrEnum):
    MOCK_SIMULATION = "MOCK_SIMULATION"
    TRUSTED_AUTHORIZATION_ONLY = "TRUSTED_AUTHORIZATION_ONLY"


AUTHORIZATION_DENIAL_CODES = frozenset(
    {
        "ACTION_DISABLED",
        "TASK_NOT_ACTIVE",
        "PURPOSE_MISMATCH",
        "RESOURCE_NOT_AUTHORIZED",
        "RECIPIENT_NOT_AUTHORIZED",
        "RESOURCE_VERSION_CHANGED",
        "CONTENT_REVIEW_REQUIRED",
        "CONSENT_NOT_FOUND",
        "CONSENT_AMBIGUOUS",
        "CONSENT_EXPIRED",
        "CONSENT_REVOKED",
        "APPROVAL_REJECTED",
        "APPROVAL_EXPIRED",
        "APPROVAL_REVOKED",
        "APPROVAL_UNAVAILABLE",
        "SEND_SLOT_CLAIMED",
        "EMAIL_CONTENT_NOT_AUTHORIZED",
        "SEND_RECONCILIATION_REQUIRED",
    }
)


def validate_authorization_observation(decision, status, reason, approval_ref, result, audit_ref):
    """Wire/outcome validation only; permission remains exclusively backend-owned."""
    reasons = {
        AuthorizationDecision.ALLOW: {"EXECUTION_NOT_STARTED"},
        AuthorizationDecision.DENY: AUTHORIZATION_DENIAL_CODES,
        AuthorizationDecision.APPROVAL_REQUIRED: {"CONSENT_REVIEW_REQUIRED"},
    }
    if (
        status != ExecutionStatus.NOT_EXECUTED
        or result is not None
        or audit_ref is None
        or decision not in reasons
        or reason not in reasons[decision]
        or (approval_ref is not None) != (decision == AuthorizationDecision.APPROVAL_REQUIRED)
    ):
        raise ValueError("Invalid authorization-only observation")


class ActionBinding(ContractModel):
    """Explicit caller data, not permission. ToolRequest performs argument validation."""

    task_ref: OpaqueReference
    action: ToolAction
    purpose: BoundedText
    arguments: dict[str, JsonValue] = Field(repr=False)


class ExecutionOptions(ContractModel):
    max_plan_actions: int = Field(default=MAX_PLAN_ACTIONS, strict=True, ge=1, le=10)
    gateway_timeout_seconds: float = Field(default=5, gt=0, le=30, allow_inf_nan=False)


class ExecutionOutcome(StrEnum):
    ALL_ACTIONS_SUCCEEDED = "ALL_ACTIONS_SUCCEEDED"
    NO_ACTIONS = "NO_ACTIONS"
    DENIED = "DENIED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    EXECUTION_UNKNOWN = "EXECUTION_UNKNOWN"
    INVALID_TOOL_REQUEST = "INVALID_TOOL_REQUEST"
    GATEWAY_UNAVAILABLE = "GATEWAY_UNAVAILABLE"
    PLANNING_FAILED = "PLANNING_FAILED"
    ACTION_LIMIT_EXCEEDED = "ACTION_LIMIT_EXCEEDED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"


class ExecutionErrorCode(StrEnum):
    GATEWAY_DENIED = "GATEWAY_DENIED"
    GATEWAY_EXECUTION_FAILED = "GATEWAY_EXECUTION_FAILED"
    GATEWAY_EXECUTION_UNKNOWN = "GATEWAY_EXECUTION_UNKNOWN"
    GATEWAY_NOT_EXECUTED = "GATEWAY_NOT_EXECUTED"
    GATEWAY_UNAVAILABLE = "GATEWAY_UNAVAILABLE"
    GATEWAY_TIMEOUT = "GATEWAY_TIMEOUT"
    INVALID_GATEWAY_RESPONSE = "INVALID_GATEWAY_RESPONSE"
    INVALID_TOOL_REQUEST = "INVALID_TOOL_REQUEST"
    DUPLICATE_ACTION = "DUPLICATE_ACTION"
    ACTION_LIMIT_EXCEEDED = "ACTION_LIMIT_EXCEEDED"
    PLANNING_FAILED = "PLANNING_FAILED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"


class ActionExecutionResult(ContractModel):
    simulation: Literal[True] = True
    action_index: int = Field(strict=True, ge=0, le=9)
    action: ToolAction
    request_ref: OpaqueReference
    idempotency_key: OpaqueReference
    decision: AuthorizationDecision | None
    execution_status: ExecutionStatus
    reason_code: OpaqueReference | None
    audit_event_ref: OpaqueReference | None = None
    approval_ref: OpaqueReference | None = None
    error_code: ExecutionErrorCode | None = None

    @model_validator(mode="after")
    def validate_recorded_outcome(self) -> Self:
        if self.decision is None:
            if (
                self.execution_status not in (ExecutionStatus.UNKNOWN, ExecutionStatus.NOT_EXECUTED)
                or self.error_code is None
                or self.reason_code is not None
                or self.approval_ref is not None
                or self.audit_event_ref is not None
            ):
                raise ValueError("An unobserved gateway decision cannot imply a known outcome")
        else:
            if self.reason_code is None:
                raise ValueError("Observed gateway decisions retain their reason code")
            if self.decision != AuthorizationDecision.ALLOW:
                if self.execution_status != ExecutionStatus.NOT_EXECUTED:
                    raise ValueError("Denied or pending actions cannot have executed")
            if self.decision == AuthorizationDecision.APPROVAL_REQUIRED:
                if self.approval_ref is None or self.error_code is not None:
                    raise ValueError("Pending approval requires its reference and no error")
            elif self.approval_ref is not None:
                raise ValueError("Only pending approval records retain an approval reference")
            if self.execution_status == ExecutionStatus.SUCCEEDED and self.error_code is not None:
                raise ValueError("Successful simulation cannot also record an execution error")
        return self


class AgentExecutionResult(ContractModel):
    simulation: Literal[True] = True
    task_ref: OpaqueReference
    task_state: AgentTaskState
    planning_result: AgentPlanningResult
    execution_outcome: ExecutionOutcome
    completed_action_count: int = Field(strict=True, ge=0, le=10)
    total_action_count: int = Field(strict=True, ge=0, le=10)
    action_results: tuple[ActionExecutionResult, ...] = Field(max_length=10)
    pending_approval_ref: OpaqueReference | None = None
    error_code: ExecutionErrorCode | None = None

    @model_validator(mode="after")
    def consistent_execution(self) -> Self:
        task = self.task_state
        plan = self.planning_result.structured_plan
        if (
            task.task_ref != self.task_ref
            or self.planning_result.task_state.task_ref != self.task_ref
        ):
            raise ValueError("Planning and execution must belong to the same task")
        if task.retry_count != 0:
            raise ValueError("B2.2a never retries gateway execution")
        if self.total_action_count != (len(plan.proposed_actions) if plan is not None else 0):
            raise ValueError("Action count must match the validated plan")
        completed = sum(
            item.decision == AuthorizationDecision.ALLOW
            and item.execution_status == ExecutionStatus.SUCCEEDED
            for item in self.action_results
        )
        if completed != self.completed_action_count or completed > self.total_action_count:
            raise ValueError("Completed count must reflect observed simulated successes")
        if len({item.request_ref for item in self.action_results}) != len(self.action_results):
            raise ValueError("Duplicate logical request results are forbidden")
        for index, item in enumerate(self.action_results):
            if (
                plan is None
                or item.action_index != index
                or index >= self.total_action_count
                or item.action != plan.proposed_actions[index]
            ):
                raise ValueError("Recorded actions must follow the validated plan in order")
            if index < len(self.action_results) - 1 and (
                item.decision != AuthorizationDecision.ALLOW
                or item.execution_status != ExecutionStatus.SUCCEEDED
            ):
                raise ValueError("Execution must stop at the first non-success")
        if self.execution_outcome == ExecutionOutcome.APPROVAL_REQUIRED:
            if (
                task.status != TaskStatus.AWAITING_APPROVAL
                or not self.action_results
                or self.action_results[-1].decision != AuthorizationDecision.APPROVAL_REQUIRED
                or self.pending_approval_ref != self.action_results[-1].approval_ref
                or task.approval_ref != self.pending_approval_ref
                or task.pending_request_ref != self.action_results[-1].request_ref
                or self.error_code is not None
                or task.last_error is not None
            ):
                raise ValueError("Pending approval must retain consistent references")
        else:
            if self.pending_approval_ref is not None or task.approval_ref is not None:
                raise ValueError("Only pending outcomes may retain approval references")
            if task.pending_request_ref is not None:
                raise ValueError("Terminal execution cannot retain a pending request")
            success = self.execution_outcome in (
                ExecutionOutcome.ALL_ACTIONS_SUCCEEDED,
                ExecutionOutcome.NO_ACTIONS,
            )
            if success:
                if (
                    task.status != TaskStatus.COMPLETED
                    or self.error_code is not None
                    or task.last_error is not None
                    or completed != self.total_action_count
                ):
                    raise ValueError("Completion requires all observed actions to succeed")
            elif (
                task.status != TaskStatus.FAILED
                or self.error_code is None
                or task.last_error != self.error_code.value
            ):
                raise ValueError("Failed execution must carry a sanitized error code")
        if self.execution_outcome == ExecutionOutcome.PLANNING_FAILED:
            if self.planning_result.outcome != PlanningOutcome.FAILED:
                raise ValueError("Planning failure must remain separate from execution failure")
        elif self.planning_result.outcome == PlanningOutcome.FAILED:
            raise ValueError("An invalid plan cannot be executed")
        if self.execution_outcome == ExecutionOutcome.NO_ACTIONS and self.total_action_count != 0:
            raise ValueError("No-actions outcome cannot describe an executed tool plan")
        if self.execution_outcome == ExecutionOutcome.ALL_ACTIONS_SUCCEEDED and (
            self.total_action_count == 0
            or self.planning_result.outcome != PlanningOutcome.PLAN_READY
        ):
            raise ValueError("Tool completion requires an executable nonempty plan")
        if self.action_results:
            last = self.action_results[-1]
            expected_stop = (
                ExecutionOutcome.DENIED
                if last.decision == AuthorizationDecision.DENY
                else ExecutionOutcome.APPROVAL_REQUIRED
                if last.decision == AuthorizationDecision.APPROVAL_REQUIRED
                else ExecutionOutcome.EXECUTION_FAILED
                if last.decision == AuthorizationDecision.ALLOW
                and last.execution_status in (ExecutionStatus.FAILED, ExecutionStatus.NOT_EXECUTED)
                else ExecutionOutcome.EXECUTION_UNKNOWN
                if last.decision == AuthorizationDecision.ALLOW
                and last.execution_status == ExecutionStatus.UNKNOWN
                else ExecutionOutcome.EXECUTION_UNKNOWN
                if last.decision is None
                and last.error_code == ExecutionErrorCode.INVALID_GATEWAY_RESPONSE
                else ExecutionOutcome.GATEWAY_UNAVAILABLE
                if last.decision is None
                else None
            )
            if expected_stop is not None and self.execution_outcome != expected_stop:
                raise ValueError("Terminal outcome must reflect the last observed gateway result")
        return self


class AuthorizationActionResult(ActionExecutionResult):
    """Opt-in v1.1 result; the original simulation-only model is unchanged."""

    simulation: Literal[False] = False
    provenance: Literal[ExecutionProvenance.TRUSTED_AUTHORIZATION_ONLY] = (
        ExecutionProvenance.TRUSTED_AUTHORIZATION_ONLY
    )

    @model_validator(mode="after")
    def authorization_only(self) -> Self:
        if self.decision is not None:
            validate_authorization_observation(
                self.decision,
                self.execution_status,
                self.reason_code,
                self.approval_ref,
                None,
                self.audit_event_ref,
            )
        return self


class AuthorizationAgentResult(AgentExecutionResult):
    simulation: Literal[False] = False
    provenance: Literal[ExecutionProvenance.TRUSTED_AUTHORIZATION_ONLY] = (
        ExecutionProvenance.TRUSTED_AUTHORIZATION_ONLY
    )
    action_results: tuple[AuthorizationActionResult, ...] = Field(max_length=10)

    @model_validator(mode="after")
    def authorization_provenance(self) -> Self:
        if self.completed_action_count != 0 or any(item.simulation for item in self.action_results):
            raise ValueError("Authorization does not complete tool execution")
        return self


class ExecutionInputError(ValueError):
    """Constant boundary/replay diagnostics only; never echoes private caller data."""
