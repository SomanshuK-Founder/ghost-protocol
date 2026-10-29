"""B2.1 planning contracts. Plans describe proposals, never permission or execution."""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, StringConstraints, model_validator

from app.agent.gateway_protocol import ContractModel, OpaqueReference, ToolAction
from app.agent.state import AgentTaskState, TaskStatus
from app.llm.config import ModelTier
from app.llm.errors import ErrorCategory

PLANNING_SKILL_ID = "task-planning"
UserRequest = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=4000)
]


class PlanIntent(StrEnum):
    SUMMARIZE_DOCUMENT = "summarize_document"
    PREPARE_EMAIL = "prepare_email"
    SUMMARIZE_AND_PREPARE_EMAIL = "summarize_and_prepare_email"
    MORNING_BRIEF = "morning_brief"
    ANSWER_QUESTION = "answer_question"
    CLARIFY_REQUEST = "clarify_request"
    UNSUPPORTED_OPERATION = "unsupported_operation"


class TaskPlan(ContractModel):
    task_ref: OpaqueReference
    intent: PlanIntent
    proposed_actions: tuple[ToolAction, ...] = Field(max_length=10)
    requires_external_action: StrictBool
    clarification_required: StrictBool

    @model_validator(mode="after")
    def consistent_proposals(self) -> Self:
        if self.requires_external_action != bool(self.proposed_actions):
            raise ValueError("External-action flag must match proposed actions")
        if self.clarification_required and self.proposed_actions:
            raise ValueError("An ambiguous plan cannot propose actions")
        if self.intent == PlanIntent.CLARIFY_REQUEST and not self.clarification_required:
            raise ValueError("Clarification intent requires clarification")
        if self.intent == PlanIntent.UNSUPPORTED_OPERATION and (
            self.proposed_actions or self.clarification_required
        ):
            raise ValueError("Unsupported operations cannot propose actions or permission")
        return self


class PlanningInput(ContractModel):
    task_ref: OpaqueReference
    user_request: UserRequest = Field(repr=False)
    skill_id: Literal["task-planning"] = PLANNING_SKILL_ID
    model_tier: ModelTier = ModelTier.SUPER


class PlanningOptions(ContractModel):
    # This outer deadline accommodates B1's default bounded attempts/backoff.
    # Tokens and SDK retries remain the injected provider's configuration.
    inference_timeout_seconds: float = Field(default=110, gt=0, le=420, allow_inf_nan=False)


class PlanningOutcome(StrEnum):
    PLAN_READY = "PLAN_READY"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    FAILED = "FAILED"


class AgentPlanningResult(ContractModel):
    task_state: AgentTaskState
    structured_plan: TaskPlan | None
    model_tier: ModelTier
    outcome: PlanningOutcome
    error_code: ErrorCategory | None = None
    correlation_ref: OpaqueReference | None = None

    @model_validator(mode="after")
    def consistent_terminal_result(self) -> Self:
        task = self.task_state
        if task.pending_request_ref is not None or task.approval_ref is not None:
            raise ValueError("Planning cannot create gateway or approval references")
        if task.retry_count != 0:
            raise ValueError("B2.1 does not retry graph planning")
        if self.outcome == PlanningOutcome.FAILED:
            if (
                task.status != TaskStatus.FAILED
                or self.structured_plan is not None
                or self.error_code is None
                or task.last_error != self.error_code.value
            ):
                raise ValueError("Failed planning requires a sanitized error and no plan")
        else:
            if (
                task.status != TaskStatus.COMPLETED
                or self.structured_plan is None
                or self.error_code is not None
                or task.last_error is not None
            ):
                raise ValueError("Completed planning requires a validated plan and no error")
            if self.structured_plan.task_ref != task.task_ref:
                raise ValueError("Plan must belong to the requested task")
            expected = (
                PlanningOutcome.UNSUPPORTED_OPERATION
                if self.structured_plan.intent == PlanIntent.UNSUPPORTED_OPERATION
                else PlanningOutcome.CLARIFICATION_REQUIRED
                if self.structured_plan.clarification_required
                else PlanningOutcome.PLAN_READY
            )
            if self.outcome != expected:
                raise ValueError("Outcome must match the validated plan")
        return self


class PlanningInputError(ValueError):
    """Constant diagnostics only; never echoes caller data or validation errors."""
