"""Deterministic B2.1/B2.2 test provider. No networking, credentials, or execution."""

import copy
from enum import StrEnum

from app.agent.planning_contracts import PlanIntent
from app.llm.config import InferenceMode, ModelTier
from app.llm.contracts import InferenceRequest, InferenceResponse
from app.llm.errors import ErrorCategory, InferenceFailure, NebiusInferenceError


class MockPlanningScenario(StrEnum):
    VALID = "VALID"
    EMPTY_ACTIONS = "EMPTY_ACTIONS"
    AMBIGUOUS = "AMBIGUOUS"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    UNKNOWN_ACTION = "UNKNOWN_ACTION"
    INVALID_SCHEMA = "INVALID_SCHEMA"
    MALFORMED_JSON = "MALFORMED_JSON"
    TIMEOUT = "TIMEOUT"
    AUTHENTICATION = "AUTHENTICATION"


class MockModelProvider:
    """Fixtures deliberately include invalid plans; the graph must reject them.

    MALFORMED_JSON simulates the B1 parser's error: the unchanged ModelProvider
    protocol carries dict outputs, so raw malformed JSON is an inference failure.
    Tier selection is explicit at construction and recorded for every call.
    """

    def __init__(
        self,
        *,
        tier: ModelTier = ModelTier.SUPER,
        scenario: MockPlanningScenario = MockPlanningScenario.VALID,
        output: dict | None = None,
        failure: ErrorCategory | None = None,
    ) -> None:
        self.tier = ModelTier(tier)
        self.mode = InferenceMode.JSON_SCHEMA
        self.scenario = MockPlanningScenario(scenario)
        self._output = copy.deepcopy(output)
        self._failure = ErrorCategory(failure) if failure is not None else None
        self.requests: list[InferenceRequest] = []
        self.requested_tiers: list[ModelTier] = []

    async def infer(self, request: InferenceRequest) -> InferenceResponse:
        request_copy = InferenceRequest.model_validate(request.model_dump(mode="python"))
        self.requests.append(request_copy)
        self.requested_tiers.append(ModelTier(request_copy.input_data["model_tier"]))
        correlation = f"mock-planning-{len(self.requests)}"
        category = self._failure or {
            MockPlanningScenario.MALFORMED_JSON: ErrorCategory.INVALID_JSON,
            MockPlanningScenario.TIMEOUT: ErrorCategory.TIMEOUT,
            MockPlanningScenario.AUTHENTICATION: ErrorCategory.AUTHENTICATION,
        }.get(self.scenario)
        if category is not None:
            raise NebiusInferenceError(
                InferenceFailure(
                    category=category,
                    correlation_ref=correlation,
                    task_ref=request_copy.task_ref,
                    attempts=1,
                    retryable=category == ErrorCategory.TIMEOUT,
                )
            )
        output = {
            "task_ref": request_copy.task_ref,
            "intent": PlanIntent.SUMMARIZE_AND_PREPARE_EMAIL.value,
            "proposed_actions": ["files.list_authorized", "files.read", "email.draft"],
            "requires_external_action": True,
            "clarification_required": False,
        }
        if self.scenario in (
            MockPlanningScenario.EMPTY_ACTIONS,
            MockPlanningScenario.AMBIGUOUS,
            MockPlanningScenario.UNSUPPORTED_OPERATION,
        ):
            output.update(
                intent={
                    MockPlanningScenario.EMPTY_ACTIONS: PlanIntent.ANSWER_QUESTION.value,
                    MockPlanningScenario.AMBIGUOUS: PlanIntent.CLARIFY_REQUEST.value,
                    MockPlanningScenario.UNSUPPORTED_OPERATION: (
                        PlanIntent.UNSUPPORTED_OPERATION.value
                    ),
                }[self.scenario],
                proposed_actions=[],
                requires_external_action=False,
                clarification_required=self.scenario == MockPlanningScenario.AMBIGUOUS,
            )
        elif self.scenario == MockPlanningScenario.UNKNOWN_ACTION:
            output["proposed_actions"] = ["shell.exec"]
        elif self.scenario == MockPlanningScenario.INVALID_SCHEMA:
            output["clarification_required"] = "false"
        if self._output is not None:
            output = copy.deepcopy(self._output)
        return InferenceResponse(
            task_ref=request_copy.task_ref,
            output=output,
            correlation_ref=correlation,
        )
