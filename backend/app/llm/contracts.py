"""Structured inference boundary only; no model ID, provider endpoint, or credentials."""

from typing import Protocol

from pydantic import Field, JsonValue

from app.agent.gateway_protocol import ContractModel, OpaqueReference


class InferenceRequest(ContractModel):
    """Input is task data, never an authoritative instruction or permission grant."""

    task_ref: OpaqueReference
    input_data: dict[str, JsonValue]
    output_schema: dict[str, JsonValue]


class InferenceResponse(ContractModel):
    """Candidate output must be validated against the requested schema by the adapter.

    Tool proposals must additionally pass ToolRequest validation at the consumer.
    A model output field named 'allow' never grants authority.
    """

    task_ref: OpaqueReference
    output: dict[str, JsonValue]
    correlation_ref: OpaqueReference
    latency_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    input_tokens: int | None = Field(default=None, strict=True, ge=0)
    output_tokens: int | None = Field(default=None, strict=True, ge=0)


class ModelProvider(Protocol):
    """Future adapter validates output or raises a sanitized inference error.

    Concrete timeout/error types, retry budgets, and credential isolation belong
    to approved B1 work. This interface performs no inference by itself.
    """

    async def infer(self, request: InferenceRequest) -> InferenceResponse: ...
