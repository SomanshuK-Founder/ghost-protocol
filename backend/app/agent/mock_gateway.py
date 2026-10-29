"""Explicitly injected TEST/DEV simulation; never a production authorization service."""

from collections.abc import Sequence

from pydantic import ValidationError

from app.agent.gateway_protocol import (
    AuthorizationDecision,
    ExecutionStatus,
    ToolAction,
    ToolRequest,
    ToolResponse,
)


class MockToolGateway:
    """Exact whole-request fixtures only; missing or malformed requests fail closed.

    Fixtures cannot execute callbacks. No external tools, policy, consent lookup,
    transport, persistence, or idempotency ledger are implemented here.
    """

    def __init__(self, fixtures: Sequence[tuple[ToolRequest, ToolResponse]] = ()) -> None:
        validated: list[tuple[ToolRequest, ToolResponse]] = []
        for request, response in fixtures:
            request_copy = ToolRequest.model_validate(request.model_dump(mode="python"))
            response_copy = ToolResponse.model_validate(response.model_dump(mode="python"))
            if request_copy.request_id != response_copy.request_id:
                raise ValueError("Mock fixture request and response IDs must match")
            if any(existing == request_copy for existing, _ in validated):
                raise ValueError("Duplicate mock request fixture")
            validated.append((request_copy, response_copy))
        self._fixtures = tuple(validated)

    @staticmethod
    def _deny(request_id: str, reason_code: str) -> ToolResponse:
        return ToolResponse(
            request_id=request_id,
            decision=AuthorizationDecision.DENY,
            execution_status=ExecutionStatus.NOT_EXECUTED,
            reason_code=reason_code,
            audit_event_ref=f"mock-event-{request_id}"[:128],
        )

    async def execute(self, request: ToolRequest) -> ToolResponse:
        # Defend against schema bypass (model_construct/model_copy without validation).
        if request.action not in tuple(ToolAction):
            return self._deny(request.request_id, "MOCK_UNKNOWN_ACTION")
        try:
            validated_request = ToolRequest.model_validate(request.model_dump(mode="python"))
        except ValidationError:
            return self._deny(request.request_id, "MOCK_INVALID_REQUEST")
        for fixture_request, fixture_response in self._fixtures:
            if fixture_request == validated_request:
                data = fixture_response.model_dump(mode="python")
                data["reason_code"] = f"MOCK_{fixture_response.reason_code}"[:128]
                data["audit_event_ref"] = f"mock-event-{validated_request.request_id}"[:128]
                if fixture_response.execution_status != ExecutionStatus.NOT_EXECUTED:
                    data["result"] = {"simulation": True, "fixture_result": data["result"]}
                return ToolResponse.model_validate(data)
        return self._deny(validated_request.request_id, "MOCK_NO_FIXTURE")
