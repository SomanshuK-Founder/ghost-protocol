"""Provisional model_calls proposal; bounded, instance-owned records, no logging."""

from collections import deque
from typing import Protocol

from pydantic import AwareDatetime, Field

from app.agent.gateway_protocol import ContractModel, OpaqueReference
from app.llm.config import InferenceMode, ModelTier
from app.llm.errors import ErrorCategory


class ModelCallTelemetry(ContractModel):
    correlation_ref: OpaqueReference
    task_ref: OpaqueReference | None
    model_id: str | None
    model_tier: ModelTier
    inference_mode: InferenceMode
    started_at: AwareDatetime
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    input_tokens: int | None = Field(default=None, strict=True, ge=0)
    output_tokens: int | None = Field(default=None, strict=True, ge=0)
    total_tokens: int | None = Field(default=None, strict=True, ge=0)
    usage_complete: bool
    success: bool
    error_category: ErrorCategory | None
    attempts: int = Field(strict=True, ge=0, le=3)
    retry_count: int = Field(strict=True, ge=0, le=2)
    telemetry_scope: str = "logical_inference"  # Usage is from the final API response only.


class TelemetrySink(Protocol):
    def record(self, event: ModelCallTelemetry) -> None: ...


class InMemoryTelemetrySink:
    """No persistence or global state. Oldest records are dropped at capacity."""

    def __init__(self, capacity: int = 128) -> None:
        if capacity < 1:
            raise ValueError("Telemetry capacity must be positive")
        self._records: deque[ModelCallTelemetry] = deque(maxlen=capacity)

    @property
    def records(self) -> tuple[ModelCallTelemetry, ...]:
        return tuple(self._records)

    def record(self, event: ModelCallTelemetry) -> None:
        self._records.append(event)
