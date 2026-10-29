"""Tests live safety controls using synthetic provider factories, not actual API calls."""

import asyncio
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.llm.config import InferenceMode, ModelTier, NebiusSettings
from app.llm.contracts import InferenceResponse
from app.llm.errors import (
    ErrorCategory,
    InferenceFailure,
    NebiusConfigurationError,
    NebiusInferenceError,
)
from app.llm.live_validation import (
    LiveExpectations,
    SyntheticIntent,
    parse_environment_text,
    render_live_report,
    run_live_validation,
)
from app.llm.telemetry import ModelCallTelemetry


def config() -> NebiusSettings:
    return NebiusSettings(
        api_key="synthetic-offline-credential",
        base_url="https://inference.example.test/v1/",
        model_super="synthetic-super",
        model_nano="synthetic-nano",
    )


def expectations(**overrides: object) -> LiveExpectations:
    return LiveExpectations(
        **{
            "base_url": "https://inference.example.test/v1/",
            "model_super": "synthetic-super",
            "model_nano": "synthetic-nano",
            **overrides,
        }
    )


def synthetic_factory(calls: list, failures: dict[int, ErrorCategory] | None = None):
    class SyntheticProvider:
        def __init__(self, settings: NebiusSettings, **options: object) -> None:
            self.settings, self.options = settings, options

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def infer(self, request):
            calls.append((self.settings, self.options))
            failure = (failures or {}).get(len(calls))
            self.options["telemetry"].record(
                ModelCallTelemetry(
                    correlation_ref=f"synthetic-call-{len(calls)}",
                    task_ref=request.task_ref,
                    model_id=self.settings.model_for(self.options["tier"]),
                    model_tier=self.options["tier"],
                    inference_mode=self.options["mode"],
                    started_at=datetime(2026, 10, 13, tzinfo=UTC),
                    latency_ms=1,
                    input_tokens=10,
                    output_tokens=5,
                    total_tokens=15,
                    usage_complete=True,
                    success=failure is None,
                    error_category=failure,
                    attempts=1,
                    retry_count=0,
                )
            )
            if failure:
                raise NebiusInferenceError(
                    InferenceFailure(
                        category=failure,
                        correlation_ref="synthetic-failure",
                        attempts=1,
                    )
                )
            return InferenceResponse(
                task_ref=request.task_ref,
                output={"response": "SYNTHETIC_RESPONSE_NOT_FOR_REPORT"},
                correlation_ref="synthetic",
            )

    return SyntheticProvider


def test_no_client_constructed_without_explicit_approval() -> None:
    calls = []
    with pytest.raises(NebiusConfigurationError, match="approval"):
        asyncio.run(
            run_live_validation(config(), expectations(), provider_factory=synthetic_factory(calls))
        )
    assert calls == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"model_super": "wrong-super"},
        {"model_nano": "wrong-nano"},
        {"base_url": "https://other.example.test/v1/"},
    ],
)
def test_preflight_requires_exact_expected_public_configuration(overrides: dict) -> None:
    calls = []
    with pytest.raises(NebiusConfigurationError, match="expectations"):
        asyncio.run(
            run_live_validation(
                config(),
                expectations(**overrides),
                approved=True,
                provider_factory=synthetic_factory(calls),
            )
        )
    assert calls == []


def test_blank_model_id_stops_preflight_without_calls() -> None:
    calls = []
    with pytest.raises(NebiusConfigurationError):
        asyncio.run(
            run_live_validation(
                config().model_copy(update={"model_nano": None}),
                expectations(),
                approved=True,
                provider_factory=synthetic_factory(calls),
            )
        )
    assert calls == []


def test_approved_operator_workflow_is_exactly_six_sequential_calls_without_retries() -> None:
    calls = []
    results = asyncio.run(
        run_live_validation(
            config(), expectations(), approved=True, provider_factory=synthetic_factory(calls)
        )
    )
    assert len(calls) == len(results) == 6
    assert sum(result.api_attempts for result in results) == 6
    assert [result.inference_mode for result in results] == [
        InferenceMode.TEXT,
        InferenceMode.TEXT,
        InferenceMode.JSON_SCHEMA,
        InferenceMode.JSON_SCHEMA,
        InferenceMode.TOOL_CALL,
        InferenceMode.TOOL_CALL,
    ]
    assert [result.model_tier for result in results] == [ModelTier.SUPER, ModelTier.NANO] * 3
    assert all(settings.max_attempts == 1 and settings.max_tokens <= 256 for settings, _ in calls)
    report = render_live_report(results, config().base_url)
    assert "synthetic-offline-credential" not in report
    assert "SYNTHETIC_RESPONSE_NOT_FOR_REPORT" not in report
    assert "Return a JSON object" not in report
    assert "API attempts: 6" in report


@pytest.mark.parametrize(
    "category",
    [
        ErrorCategory.AUTHENTICATION,
        ErrorCategory.PERMISSION,
        ErrorCategory.CONFIGURATION,
        ErrorCategory.MODEL_UNAVAILABLE,
    ],
)
def test_first_fatal_error_stops_remaining_requests(category: ErrorCategory) -> None:
    calls = []
    results = asyncio.run(
        run_live_validation(
            config(),
            expectations(),
            approved=True,
            provider_factory=synthetic_factory(calls, {1: category}),
        )
    )
    assert len(calls) == 1
    assert results[0].status == "FAILED"
    assert all(result.status == "NOT_RUN" for result in results[1:])
    assert sum(result.api_attempts for result in results) == 1


def test_unsupported_schema_is_recorded_without_an_extra_fallback_call() -> None:
    calls = []
    results = asyncio.run(
        run_live_validation(
            config(),
            expectations(),
            approved=True,
            provider_factory=synthetic_factory(calls, {3: ErrorCategory.UNSUPPORTED_OPTION}),
        )
    )
    assert len(calls) == 6
    assert results[2].capability_status == "REJECTED_OPTION"
    assert results[2].status == "FAILED"


def test_environment_parser_handles_only_literal_requested_assignments() -> None:
    values = parse_environment_text(
        '# comment\nNEBIUS_API_KEY="synthetic-offline-credential"\n'
        "export NEBIUS_MODEL_SUPER='synthetic-super'\n"
        "NEBIUS_MODEL_NANO=\nUNRELATED_CREDENTIAL=do-not-load\n"
    )
    assert values["NEBIUS_MODEL_SUPER"] == "synthetic-super"
    assert values["NEBIUS_MODEL_NANO"] == ""
    assert "UNRELATED_CREDENTIAL" not in values


@pytest.mark.parametrize(
    "text", ["NEBIUS_API_KEY=one\nNEBIUS_API_KEY=two", "NEBIUS_API_KEY='unclosed"]
)
def test_ambiguous_environment_assignments_fail_without_echoing_values(text: str) -> None:
    with pytest.raises(NebiusConfigurationError) as error:
        parse_environment_text(text)
    assert "unclosed" not in str(error.value)
    assert "one" not in str(error.value)


def test_capability_only_workflow_schedules_exactly_four_sequential_probes() -> None:
    calls, requests = [], []

    class CapturingProvider(synthetic_factory(calls)):
        async def infer(self, request):
            requests.append(request)
            return await super().infer(request)

    results = asyncio.run(
        run_live_validation(
            config(),
            expectations(),
            approved=True,
            capabilities_only=True,
            provider_factory=CapturingProvider,
        )
    )
    assert len(calls) == len(requests) == len(results) == 4
    assert sum(result.api_attempts for result in results) == 4
    assert [result.inference_mode for result in results] == [
        InferenceMode.JSON_SCHEMA,
        InferenceMode.JSON_SCHEMA,
        InferenceMode.TOOL_CALL,
        InferenceMode.TOOL_CALL,
    ]
    assert [result.model_tier for result in results] == [ModelTier.SUPER, ModelTier.NANO] * 2
    assert all(settings.max_attempts == 1 and settings.max_tokens == 256 for settings, _ in calls)
    assert all(request.task_ref == "task_demo_001" for request in requests)
    for request in requests[:2]:
        assert set(request.output_schema["required"]) == {
            "intent",
            "requires_approval",
            "resource_id",
        }
        assert request.output_schema["additionalProperties"] is False
    assert all(options["response_model"] is SyntheticIntent for _, options in calls[:2])


def test_capability_only_mode_still_requires_explicit_approval() -> None:
    calls = []
    with pytest.raises(NebiusConfigurationError, match="approval"):
        asyncio.run(
            run_live_validation(
                config(),
                expectations(),
                capabilities_only=True,
                provider_factory=synthetic_factory(calls),
            )
        )
    assert calls == []


def test_capability_only_selection_rejects_ambiguous_operator_values() -> None:
    calls = []
    with pytest.raises(NebiusConfigurationError, match="boolean"):
        asyncio.run(
            run_live_validation(
                config(),
                expectations(),
                approved=True,
                capabilities_only="false",
                provider_factory=synthetic_factory(calls),
            )
        )
    assert calls == []


@pytest.mark.parametrize(
    "category",
    [ErrorCategory.AUTHENTICATION, ErrorCategory.PERMISSION, ErrorCategory.CONFIGURATION],
)
def test_capability_only_fatal_error_stops_remaining_requests(category: ErrorCategory) -> None:
    calls = []
    results = asyncio.run(
        run_live_validation(
            config(),
            expectations(),
            approved=True,
            capabilities_only=True,
            provider_factory=synthetic_factory(calls, {1: category}),
        )
    )
    assert len(calls) == 1
    assert len(results) == 4
    assert all(result.status == "NOT_RUN" for result in results[1:])
    assert sum(result.api_attempts for result in results) == 1


def test_capability_only_unsupported_schema_does_not_add_fallback_requests() -> None:
    calls = []
    results = asyncio.run(
        run_live_validation(
            config(),
            expectations(),
            approved=True,
            capabilities_only=True,
            provider_factory=synthetic_factory(calls, {1: ErrorCategory.UNSUPPORTED_OPTION}),
        )
    )
    assert len(calls) == 4
    assert results[0].capability_status == "REJECTED_OPTION"
    assert results[0].error_category == ErrorCategory.UNSUPPORTED_OPTION
    assert sum(result.api_attempts for result in results) == 4


@pytest.mark.parametrize(
    "payload",
    [
        {"intent": "summarize_document", "requires_approval": False},
        {
            "intent": "summarize_document",
            "requires_approval": "false",
            "resource_id": "demo_document_001",
        },
        {
            "intent": "summarize_document",
            "requires_approval": False,
            "resource_id": "demo_document_001",
            "extra": "untrusted",
        },
        {
            "intent": "send_email",
            "requires_approval": False,
            "resource_id": "demo_document_001",
        },
    ],
)
def test_synthetic_intent_rejects_missing_wrong_type_extra_or_unexpected_fields(payload: dict):
    with pytest.raises(ValidationError):
        SyntheticIntent.model_validate(payload, strict=True)
