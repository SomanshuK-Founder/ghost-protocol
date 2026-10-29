"""Explicit trusted-local operator workflow. Never imported by the inference provider.

Nothing runs on import. Approval, expected public configuration, and a six-call
sequential budget are checked before client construction. Only this operator
helper may explicitly read a local configuration file or write the B1 report.
"""

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, StrictBool, StrictStr

from app.agent.gateway_protocol import ContractModel
from app.llm.config import InferenceMode, ModelTier, NebiusSettings
from app.llm.contracts import InferenceRequest
from app.llm.errors import ErrorCategory, NebiusConfigurationError, NebiusInferenceError
from app.llm.nebius_provider import NebiusModelProvider
from app.llm.telemetry import InMemoryTelemetrySink
from app.llm.validation import SyntheticToolProposal

_ENVIRONMENT_NAMES = (
    "NEBIUS_API_KEY",
    "NEBIUS_BASE_URL",
    "NEBIUS_MODEL_SUPER",
    "NEBIUS_MODEL_NANO",
)


class LiveExpectations(ContractModel):
    base_url: HttpUrl
    model_super: StrictStr
    model_nano: StrictStr


class SyntheticSummary(ContractModel):
    summary: StrictStr = Field(min_length=1, max_length=140)


class SyntheticIntent(ContractModel):
    """Synthetic output only; requires_approval is not an authorization decision."""

    intent: Literal["summarize_document"]
    requires_approval: StrictBool
    resource_id: Literal["demo_document_001"]


class LiveObservation(ContractModel):
    model_tier: ModelTier
    model_id: str
    inference_mode: InferenceMode
    status: str
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    error_category: ErrorCategory | None = None
    api_attempts: int = 0
    capability_status: str


def parse_environment_text(text: str) -> dict[str, str]:
    """Four literal assignments only; no interpolation, command execution, or mutation.

    Accept whole-value single/double quotes and comments on their own lines.
    Ignore unrelated keys. Duplicate target keys or malformed quotes fail safely.
    """
    result: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        key, separator, value = stripped.partition("=")
        key = key.strip()
        if key not in _ENVIRONMENT_NAMES:
            continue
        if not separator or key in result:
            raise NebiusConfigurationError("Invalid or duplicate local environment assignment")
        value = value.strip()
        if value[:1] in ("'", '"'):
            if len(value) < 2 or value[-1] != value[0]:
                raise NebiusConfigurationError("Invalid quoted local environment assignment")
            value = value[1:-1]
        result[key] = value
    return result


def load_live_settings(
    *, env_file: Path | None = None, environment: Mapping[str, str] | None = None
) -> NebiusSettings:
    source = os.environ if environment is None else environment
    values: dict[str, str] = {}
    if env_file is not None:
        try:
            values = parse_environment_text(env_file.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError):
            raise NebiusConfigurationError(
                "Unable to read the explicitly selected local environment file"
            ) from None
    values.update({name: source[name] for name in _ENVIRONMENT_NAMES if name in source})
    return NebiusSettings.from_environment(values)


def _confirm(settings: NebiusSettings, expectations: LiveExpectations, approved: bool) -> None:
    if not approved:
        raise NebiusConfigurationError("Explicit approval is required before live inference")
    if not settings.model_super or not settings.model_nano:
        raise NebiusConfigurationError(
            "Both exact model identifiers must be configured before live validation"
        )
    if (
        settings.base_url != expectations.base_url
        or settings.model_super != expectations.model_super
        or settings.model_nano != expectations.model_nano
    ):
        raise NebiusConfigurationError(
            "Configured endpoint or model identifiers do not match explicit expectations"
        )


async def run_live_validation(
    settings: NebiusSettings,
    expectations: LiveExpectations,
    *,
    approved: bool = False,
    capabilities_only: bool = False,
    provider_factory: Callable[..., NebiusModelProvider] = NebiusModelProvider,
) -> tuple[LiveObservation, ...]:
    """Six initial or four capability probes; no retries, fallback, or endpoint search.

    Invocation is not itself evidence of approval; the operator must obtain user
    approval before invoking this workflow. Factory injection is for offline tests.
    Capability-only mode never schedules a basic text inference request.
    """
    if not isinstance(capabilities_only, bool):
        raise NebiusConfigurationError("Capability-only selection must be an explicit boolean")
    _confirm(settings, expectations, approved)
    plans = (
        (ModelTier.SUPER, InferenceMode.TEXT),
        (ModelTier.NANO, InferenceMode.TEXT),
        (ModelTier.SUPER, InferenceMode.JSON_SCHEMA),
        (ModelTier.NANO, InferenceMode.JSON_SCHEMA),
        (ModelTier.SUPER, InferenceMode.TOOL_CALL),
        (ModelTier.NANO, InferenceMode.TOOL_CALL),
    )
    if capabilities_only:
        plans = tuple(plan for plan in plans if plan[1] != InferenceMode.TEXT)
    results: list[LiveObservation] = []
    fatal: ErrorCategory | None = None
    for tier, mode in plans:
        model = settings.model_for(tier)
        if fatal is not None:
            results.append(
                LiveObservation(
                    model_tier=tier,
                    model_id=model,
                    inference_mode=mode,
                    status="NOT_RUN",
                    error_category=fatal,
                    capability_status="NOT YET VERIFIED",
                )
            )
            continue
        call_settings = NebiusSettings.model_validate(
            settings.model_copy(
                update={
                    "max_attempts": 1,
                    "max_tokens": 128 if mode == InferenceMode.TEXT else 256,
                }
            ).model_dump()
        )
        if mode == InferenceMode.TEXT:
            schema = {
                "type": "object",
                "properties": {"text": {"type": "string", "minLength": 1}},
                "required": ["text"],
                "additionalProperties": False,
            }
            instruction = "Reply with a short greeting for a synthetic connectivity check."
            response_model = None
        elif mode == InferenceMode.JSON_SCHEMA:
            if capabilities_only:
                response_model = SyntheticIntent
                instruction = (
                    'Return a JSON object with intent="summarize_document", '
                    'requires_approval=false, and resource_id="demo_document_001". '
                    "This is synthetic data, not permission to perform any action."
                )
            else:
                response_model = SyntheticSummary
                instruction = "Return a JSON object with summary: 'Synthetic task ready'."
            schema = response_model.model_json_schema()
        else:
            schema = SyntheticToolProposal.model_json_schema()
            instruction = (
                "Propose get_current_task_summary for this synthetic task; do not execute it."
            )
            response_model = SyntheticToolProposal
        inference = InferenceRequest(
            task_ref="task_demo_001" if capabilities_only else "live-synthetic-task",
            input_data={"instruction": instruction},
            output_schema=schema,
        )
        sink = InMemoryTelemetrySink()
        failure: ErrorCategory | None = None
        try:
            async with provider_factory(
                call_settings, tier=tier, mode=mode, response_model=response_model, telemetry=sink
            ) as provider:
                await provider.infer(inference)
        except NebiusInferenceError as error:
            failure = error.failure.category
        except NebiusConfigurationError:
            failure = ErrorCategory.CONFIGURATION
        except Exception:
            failure = ErrorCategory.INTERNAL  # No raw operator/SDK exception text in reports.
        event = sink.records[-1] if sink.records else None
        if failure in (
            ErrorCategory.AUTHENTICATION,
            ErrorCategory.PERMISSION,
            ErrorCategory.CONFIGURATION,
            ErrorCategory.MODEL_UNAVAILABLE,
            ErrorCategory.INVALID_REQUEST,
        ):
            fatal = failure
        capability = (
            "NOT_TESTED"
            if mode == InferenceMode.TEXT
            else (
                "VERIFIED"
                if failure is None
                else "REJECTED_OPTION"
                if failure == ErrorCategory.UNSUPPORTED_OPTION
                else "NOT_CONFIRMED"
            )
        )
        results.append(
            LiveObservation(
                model_tier=tier,
                model_id=model,
                inference_mode=mode,
                status="SUCCEEDED" if failure is None else "FAILED",
                error_category=failure,
                latency_ms=event.latency_ms if event else None,
                input_tokens=event.input_tokens if event else None,
                output_tokens=event.output_tokens if event else None,
                total_tokens=event.total_tokens if event else None,
                api_attempts=event.attempts if event else 0,
                capability_status=capability,
            )
        )
    return tuple(results)


def render_live_report(results: tuple[LiveObservation, ...], endpoint: HttpUrl) -> str:
    lines = [
        "# Phase B1 live validation report",
        "",
        "Observed sequential operator probes. No tool was executed; "
        "no OpenShell isolation was verified.",
        "",
        f"Endpoint used: `{endpoint}`",
        "",
        "| Tier | Exact API ID | Mode | Result | Latency ms | Input/output/total tokens | "
        "Capability | Error | Attempts |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for result in results:
        latency = f"{result.latency_ms:.2f}" if result.latency_ms is not None else "unknown"
        tokens = "/".join(
            "unknown" if value is None else str(value)
            for value in (result.input_tokens, result.output_tokens, result.total_tokens)
        )
        lines.append(
            f"| {result.model_tier.value} | `{result.model_id}` | {result.inference_mode.value} | "
            f"{result.status} | {latency} | {tokens} | {result.capability_status} | "
            f"{result.error_category.value if result.error_category else '-'} | "
            f"{result.api_attempts} |"
        )
    lines.extend(
        [
            "",
            f"API attempts: {sum(result.api_attempts for result in results)} "
            "(budget: at most six).",
            "Native JSON-schema probing does not verify every schema or JSON-object mode.",
            "Capabilities marked NOT_RUN/NOT_CONFIRMED remain NOT YET VERIFIED.",
            "No extended ten-case benchmark was run. It requires separate user approval.",
            "",
        ]
    )
    return "\n".join(lines)
