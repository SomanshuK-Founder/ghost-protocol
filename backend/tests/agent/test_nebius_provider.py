"""Offline B1 tests: real async SDK serialization through HTTPX MockTransport only."""

import asyncio
import copy
import json
import logging
import smtplib
import socket
import subprocess
import traceback
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError

from app.llm.config import InferenceMode, ModelTier, NebiusSettings
from app.llm.contracts import InferenceRequest, ModelProvider
from app.llm.errors import (
    ErrorCategory,
    InferenceFailure,
    NebiusConfigurationError,
    NebiusInferenceError,
    ProviderErrorCode,
)
from app.llm.nebius_provider import NebiusModelProvider
from app.llm.telemetry import InMemoryTelemetrySink
from app.llm.validation import SyntheticToolProposal

SYNTHETIC_CREDENTIAL = "synthetic-offline-credential"
SYNTHETIC_URL = "https://inference.example.test/v1/"


class Summary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str


def settings(**overrides: object) -> NebiusSettings:
    return NebiusSettings(
        **{
            "api_key": SYNTHETIC_CREDENTIAL,
            "base_url": SYNTHETIC_URL,
            "model_super": "synthetic-super",
            "model_nano": "synthetic-nano",
            **overrides,
        }
    )


def request(schema: dict | None = None) -> InferenceRequest:
    return InferenceRequest(
        task_ref="task-synthetic-001",
        input_data={"instruction": "Return a small synthetic summary"},
        output_schema=Summary.model_json_schema() if schema is None else schema,
    )


def completion(content: str | None = '{"summary":"Synthetic"}', **overrides: object) -> dict:
    return {
        "id": "completion-synthetic-001",
        "object": "chat.completion",
        "created": 1,
        "model": "synthetic-super",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18},
        **overrides,
    }


def tool_completion(name: str = "get_current_task_summary", arguments: str | None = None) -> dict:
    return completion(
        choices=[
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-synthetic-001",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": '{"task_ref":"task-synthetic-001"}'
                                if arguments is None
                                else arguments,
                            },
                        }
                    ],
                },
            }
        ]
    )


def run_fixture(
    responses: list,
    *,
    config: NebiusSettings | None = None,
    inference: InferenceRequest | None = None,
    **provider_options: object,
) -> tuple:
    calls, sleeps = [], []
    sink = InMemoryTelemetrySink()

    def handler(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        assert len(calls) <= len(responses), "Unexpected additional inference request"
        item = responses[len(calls) - 1]
        if isinstance(item, str):
            exception = httpx.ReadTimeout if item == "timeout" else httpx.ConnectError
            raise exception("Synthetic private error detail", request=http_request)
        if isinstance(item, tuple):
            status, body, headers = item
            return httpx.Response(status, json=body, headers=headers, request=http_request)
        return httpx.Response(200, json=item, request=http_request)

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    async def scenario() -> tuple:
        async with NebiusModelProvider(
            config or settings(),
            transport=httpx.MockTransport(handler),
            telemetry=sink,
            sleep=sleep,
            **provider_options,
        ) as provider:
            try:
                result = await provider.infer(inference or request())
            except NebiusInferenceError as error:
                result = error
            return result, calls, sleeps, sink.records

    return asyncio.run(scenario())


def test_configuration_loads_four_environment_fields_without_reading_dotenv() -> None:
    config = NebiusSettings.from_environment(
        {
            "NEBIUS_API_KEY": SYNTHETIC_CREDENTIAL,
            "NEBIUS_BASE_URL": SYNTHETIC_URL,
            "NEBIUS_MODEL_SUPER": "synthetic-super",
            "NEBIUS_MODEL_NANO": "synthetic-nano",
        }
    )
    assert config.model_for(ModelTier.NANO) == "synthetic-nano"
    assert SYNTHETIC_CREDENTIAL not in repr(config)
    assert SYNTHETIC_URL not in repr(config)


@pytest.mark.parametrize(
    "key", ["", "REPLACE_WITH_YOUR_API_KEY", "your_nebius_api_key_here", "x\ny"]
)
def test_missing_or_placeholder_credential_fails_safely(key: str) -> None:
    with pytest.raises(NebiusConfigurationError) as error:
        NebiusSettings.from_environment({"NEBIUS_API_KEY": key, "NEBIUS_BASE_URL": SYNTHETIC_URL})
    assert SYNTHETIC_URL not in str(error.value)


def test_empty_environment_mapping_does_not_fall_back_to_process_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEBIUS_API_KEY", SYNTHETIC_CREDENTIAL)
    with pytest.raises(NebiusConfigurationError):
        NebiusSettings.from_environment({})


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://localhost/v1/",
        "https://user:secret@x.test/v1/",
        "https://x.test/v1/?key=secret",
        "https://x.test/v1/#secret",
    ],
)
def test_unsafe_endpoints_rejected(url: str) -> None:
    with pytest.raises(ValidationError) as error:
        settings(base_url=url)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_attempts": 4},
        {"max_attempts": 0},
        {"max_attempts": True},
        {"max_tokens": 0},
        {"timeout_seconds": 0},
        {"timeout_seconds": float("inf")},
        {"model_super": "bad model"},
        {"backoff_seconds": 2, "max_retry_delay_seconds": 1},
    ],
)
def test_configuration_bounds(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        settings(**overrides)


@pytest.mark.parametrize(
    ("tier", "model"), [(ModelTier.SUPER, "synthetic-super"), (ModelTier.NANO, "synthetic-nano")]
)
def test_explicit_tier_resolves_exact_configured_model(tier: ModelTier, model: str) -> None:
    result, calls, _, events = run_fixture([completion()], tier=tier)
    assert result.output == {"summary": "Synthetic"}
    assert json.loads(calls[0].content)["model"] == model
    assert events[0].model_id == model
    assert events[0].model_tier == tier


def test_super_is_default_and_protocol_is_unchanged() -> None:
    provider: ModelProvider
    provider = NebiusModelProvider(
        settings(), transport=httpx.MockTransport(lambda r: httpx.Response(200))
    )
    assert provider.tier == ModelTier.SUPER
    asyncio.run(provider.aclose())


@pytest.mark.parametrize("tier", ["ULTRA", "nano", "", 1])
def test_unsupported_tier_does_not_construct_a_live_client(tier: object) -> None:
    with pytest.raises(NebiusConfigurationError):
        NebiusModelProvider(settings(), tier=tier)


@pytest.mark.parametrize("tier", [ModelTier.SUPER, ModelTier.NANO])
def test_missing_model_has_structured_failure_and_no_fallback(tier: ModelTier) -> None:
    config = settings(**({"model_super": ""} if tier == ModelTier.SUPER else {"model_nano": ""}))
    result, calls, _, events = run_fixture([], config=config, tier=tier)
    assert result.failure.category == ErrorCategory.MODEL_UNAVAILABLE
    assert result.failure.attempts == 0
    assert calls == []
    assert events[0].success is False


def test_text_mode_wraps_text_in_existing_output_contract() -> None:
    result, calls, _, _ = run_fixture(
        [completion("Synthetic text")],
        mode=InferenceMode.TEXT,
        inference=request(
            {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            }
        ),
    )
    assert result.output == {"text": "Synthetic text"}
    assert "response_format" not in json.loads(calls[0].content)


@pytest.mark.parametrize(
    "mode", [InferenceMode.JSON_REQUEST, InferenceMode.JSON_OBJECT, InferenceMode.JSON_SCHEMA]
)
def test_structured_modes_validate_locally_and_send_explicit_options(mode: InferenceMode) -> None:
    result, calls, _, _ = run_fixture([completion()], mode=mode, response_model=Summary)
    payload = json.loads(calls[0].content)
    assert result.output == {"summary": "Synthetic"}
    if mode == InferenceMode.JSON_REQUEST:
        assert "response_format" not in payload
    else:
        assert payload["response_format"]["type"] == mode.value.lower()
    assert calls[0].headers["x-client-request-id"] == result.correlation_ref
    assert str(calls[0].url) == SYNTHETIC_URL + "chat/completions"
    assert payload["max_tokens"] == 256


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        '```json\n{"summary":"x"}\n```',
        '{"summary":"x","summary":"y"}',
        '{"summary":NaN}',
    ],
)
def test_invalid_json_is_not_repaired_or_retried(content: str) -> None:
    result, calls, _, events = run_fixture([completion(content)])
    assert result.failure.category == ErrorCategory.INVALID_JSON
    assert len(calls) == 1
    assert events[0].success is False


@pytest.mark.parametrize("content", ["[]", "{}", '{"summary":3}', '{"summary":"x","allow":true}'])
def test_schema_mismatch_rejected(content: str) -> None:
    result, calls, _, _ = run_fixture([completion(content)], response_model=Summary)
    assert result.failure.category == ErrorCategory.SCHEMA_MISMATCH
    assert len(calls) == 1


def test_pydantic_expected_model_is_validated_even_with_permissive_json_schema() -> None:
    result, _, _, _ = run_fixture(
        [completion('{"summary":7}')], inference=request({}), response_model=Summary
    )
    assert result.failure.category == ErrorCategory.SCHEMA_MISMATCH


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "invalid"},
        {"$ref": "https://private.example.test/schema"},
        {"$ref": "file:///private/document"},
        {"$schema": "https://example.test/custom"},
        {"properties": {"x": {"$dynamicRef": "https://example.test/schema"}}},
    ],
)
def test_invalid_or_external_schemas_fail_before_any_request(schema: dict) -> None:
    result, calls, _, events = run_fixture([], inference=request(schema))
    assert result.failure.category == ErrorCategory.INVALID_REQUEST
    assert events[0].attempts == 0
    assert calls == []


def test_local_json_schema_references_work() -> None:
    schema = {
        "type": "object",
        "properties": {"summary": {"$ref": "#/$defs/text"}},
        "required": ["summary"],
        "$defs": {"text": {"type": "string"}},
    }
    result, _, _, _ = run_fixture([completion()], inference=request(schema))
    assert result.output["summary"] == "Synthetic"


def test_synthetic_tool_call_is_a_proposal_only() -> None:
    result, calls, _, _ = run_fixture(
        [tool_completion()], mode=InferenceMode.TOOL_CALL, inference=request({})
    )
    assert result.output["name"] == "get_current_task_summary"
    assert result.output["arguments"] == {"task_ref": "task-synthetic-001"}
    payload = json.loads(calls[0].content)
    assert len(payload["tools"]) == 1
    assert payload["tools"][0]["function"]["name"] == "get_current_task_summary"
    assert len(calls) == 1  # No tool result submitted, execution, or follow-up inference.


@pytest.mark.parametrize(
    ("name", "arguments", "category"),
    [
        ("shell.exec", "{}", ErrorCategory.SCHEMA_MISMATCH),
        ("get_current_task_summary", "not json", ErrorCategory.INVALID_JSON),
        ("get_current_task_summary", "{}", ErrorCategory.SCHEMA_MISMATCH),
        ("get_current_task_summary", '{"task_ref":7}', ErrorCategory.SCHEMA_MISMATCH),
        ("get_current_task_summary", '{"task_ref":"other-task"}', ErrorCategory.SCHEMA_MISMATCH),
        (
            "get_current_task_summary",
            '{"task_ref":"task-synthetic-001","allow":true}',
            ErrorCategory.SCHEMA_MISMATCH,
        ),
    ],
)
def test_bad_tool_proposals_rejected(name: str, arguments: str, category: ErrorCategory) -> None:
    result, calls, _, _ = run_fixture(
        [tool_completion(name, arguments)], mode=InferenceMode.TOOL_CALL, inference=request({})
    )
    assert result.failure.category == category
    assert len(calls) == 1


def test_unexpected_tool_call_rejected_in_text_or_json_mode() -> None:
    result, _, _, _ = run_fixture([tool_completion()])
    assert result.failure.category == ErrorCategory.MALFORMED_RESPONSE


@pytest.mark.parametrize(
    ("status", "body", "category"),
    [
        (401, {"error": {"message": SYNTHETIC_CREDENTIAL}}, ErrorCategory.AUTHENTICATION),
        (403, {"error": {"message": "Private denied detail"}}, ErrorCategory.PERMISSION),
        (404, {"error": {"code": "model_not_found"}}, ErrorCategory.MODEL_UNAVAILABLE),
        (400, {"error": {"param": "model"}}, ErrorCategory.MODEL_UNAVAILABLE),
        (400, {"error": {"message": "Invalid request"}}, ErrorCategory.INVALID_REQUEST),
        (422, {"error": {"message": "Invalid request"}}, ErrorCategory.INVALID_REQUEST),
    ],
)
def test_permanent_api_errors_not_retried_and_never_echo_bodies(
    status: int,
    body: dict,
    category: ErrorCategory,
) -> None:
    result, calls, sleeps, events = run_fixture([(status, body, {})])
    assert result.failure.category == category
    assert len(calls) == 1 and sleeps == []
    assert events[0].error_category == category
    rendered = "".join(traceback.format_exception(result))
    assert SYNTHETIC_CREDENTIAL not in rendered
    assert "Private denied detail" not in rendered
    assert result.__context__ is None


@pytest.mark.parametrize(
    ("response", "category"),
    [
        ((429, {"error": {"message": "Rate limited"}}, {}), ErrorCategory.RATE_LIMIT),
        ((500, {"error": {"message": "Server problem"}}, {}), ErrorCategory.SERVER),
        ((408, {"error": {"message": "Timeout"}}, {}), ErrorCategory.TIMEOUT),
        ("timeout", ErrorCategory.TIMEOUT),
        ("network", ErrorCategory.NETWORK),
    ],
)
def test_transient_failures_retry_with_bounded_exponential_backoff(
    response: object,
    category: ErrorCategory,
) -> None:
    result, calls, sleeps, events = run_fixture([response, response, completion()])
    assert result.output == {"summary": "Synthetic"}
    assert len(calls) == 3
    assert sleeps == [0.25, 0.5]
    assert events[0].attempts == 3 and events[0].retry_count == 2
    assert events[0].error_category is None
    assert len({call.headers["x-client-request-id"] for call in calls}) == 1


def test_retry_exhaustion_is_structured_and_sdk_does_not_add_retries() -> None:
    result, calls, sleeps, events = run_fixture(["timeout"] * 3)
    assert result.failure.category == ErrorCategory.TIMEOUT
    assert result.failure.attempts == 3
    assert result.failure.retryable is True
    assert len(calls) == 3 and len(sleeps) == 2
    assert events[0].success is False


@pytest.mark.parametrize("headers", [{"Retry-After": "1"}, {"retry-after-ms": "1000"}])
def test_retry_after_is_respected(headers: dict) -> None:
    result, calls, sleeps, _ = run_fixture([(429, {"error": {}}, headers), completion()])
    assert result.output
    assert len(calls) == 2
    assert sleeps == [1]


def test_long_retry_after_stops_instead_of_retrying_early() -> None:
    result, calls, sleeps, _ = run_fixture([(429, {"error": {}}, {"Retry-After": "60"})])
    assert result.failure.category == ErrorCategory.RATE_LIMIT
    assert len(calls) == 1 and sleeps == []


@pytest.mark.parametrize(
    "mode", [InferenceMode.JSON_OBJECT, InferenceMode.JSON_SCHEMA, InferenceMode.TOOL_CALL]
)
def test_unsupported_capability_does_not_automatically_fallback(mode: InferenceMode) -> None:
    result, calls, _, _ = run_fixture(
        [(400, {"error": {"code": "unsupported_parameter"}}, {})],
        mode=mode,
    )
    assert result.failure.category == ErrorCategory.UNSUPPORTED_OPTION
    assert len(calls) == 1


@pytest.mark.parametrize("content", [None, "", "  "])
def test_empty_model_response_is_not_success(content: str | None) -> None:
    result, _, _, _ = run_fixture([completion(content)])
    assert result.failure.category == ErrorCategory.EMPTY_RESPONSE


def test_no_choices_is_empty_response() -> None:
    result, _, _, _ = run_fixture([completion(choices=[])])
    assert result.failure.category == ErrorCategory.EMPTY_RESPONSE


def test_truncated_response_is_rejected_even_if_json_would_parse() -> None:
    raw = completion()
    raw["choices"][0]["finish_reason"] = "length"
    result, _, _, _ = run_fixture([raw])
    assert result.failure.category == ErrorCategory.TRUNCATED_RESPONSE


@pytest.mark.parametrize("usage", [None, {}, {"prompt_tokens": 12}])
def test_missing_usage_remains_unknown_not_zero(usage: dict | None) -> None:
    result, _, _, events = run_fixture([completion(usage=usage)])
    assert result.output_tokens is None
    assert events[0].total_tokens is None
    assert events[0].usage_complete is False


def test_complete_usage_and_latency_match_response_and_telemetry() -> None:
    readings = iter([10, 10.1, 10.1])
    start = datetime(2026, 10, 13, tzinfo=UTC)
    result, _, _, events = run_fixture(
        [completion()], clock=lambda: next(readings), utc_now=lambda: start
    )
    event = events[0]
    assert result.latency_ms == pytest.approx(100)
    assert event.latency_ms == pytest.approx(100)
    assert (event.input_tokens, event.output_tokens, event.total_tokens) == (12, 6, 18)
    assert event.correlation_ref == result.correlation_ref
    assert event.task_ref == result.task_ref and event.started_at == start
    assert event.usage_complete and event.success
    assert SYNTHETIC_CREDENTIAL not in event.model_dump_json()
    assert "instruction" not in event.model_dump_json()


def test_sdk_debug_logging_is_refused_before_sending_private_prompts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="openai._base_client")
    with pytest.raises(NebiusConfigurationError):
        NebiusModelProvider(settings())
    assert SYNTHETIC_CREDENTIAL not in caplog.text


def test_redirects_not_followed_to_another_host() -> None:
    result, calls, _, _ = run_fixture(
        [(307, {"error": {}}, {"Location": "https://other.example.test"})]
    )
    assert result.failure.category == ErrorCategory.CONFIGURATION
    assert len(calls) == 1


def test_telemetry_collector_is_bounded() -> None:
    _, _, _, events = run_fixture([completion()])
    collector = InMemoryTelemetrySink(capacity=1)
    collector.record(events[0])
    collector.record(events[0])
    assert len(collector.records) == 1


def test_configuration_model_selection_cannot_silently_map_unknown_tier_to_nano() -> None:
    with pytest.raises(NebiusConfigurationError):
        settings().model_for("ULTRA")


def test_numeric_overflow_in_json_is_rejected() -> None:
    result, calls, _, _ = run_fixture([completion('{"number":1e999}')], inference=request({}))
    assert result.failure.category == ErrorCategory.INVALID_JSON
    assert len(calls) == 1


def test_missing_tool_proposal_is_rejected() -> None:
    result, calls, _, _ = run_fixture(
        [completion("No tool call")], mode=InferenceMode.TOOL_CALL, inference=request({})
    )
    assert result.failure.category == ErrorCategory.MALFORMED_RESPONSE
    assert len(calls) == 1


def test_missing_tool_argument_string_is_malformed_response() -> None:
    raw = tool_completion()
    del raw["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    result, _, _, _ = run_fixture([raw], mode=InferenceMode.TOOL_CALL, inference=request({}))
    assert result.failure.category == ErrorCategory.MALFORMED_RESPONSE


def test_multiple_tool_proposals_are_rejected() -> None:
    raw = tool_completion()
    raw["choices"][0]["message"]["tool_calls"] *= 2
    result, _, _, _ = run_fixture([raw], mode=InferenceMode.TOOL_CALL, inference=request({}))
    assert result.failure.category == ErrorCategory.MALFORMED_RESPONSE


def test_unresolvable_local_schema_reference_fails_closed() -> None:
    result, _, _, _ = run_fixture([completion()], inference=request({"$ref": "#/$defs/missing"}))
    assert result.failure.category == ErrorCategory.SCHEMA_MISMATCH


def test_http_date_retry_after_respected() -> None:
    start = datetime(2026, 10, 13, 0, 0, 0, tzinfo=UTC)
    result, _, sleeps, _ = run_fixture(
        [(429, {"error": {}}, {"Retry-After": "Tue, 13 Oct 2026 00:00:02 GMT"}), completion()],
        utc_now=lambda: start,
    )
    assert result.output
    assert sleeps == [2]


def test_invalid_retry_after_uses_bounded_default_backoff() -> None:
    result, _, sleeps, _ = run_fixture(
        [(429, {"error": {}}, {"Retry-After": "invalid-date"}), completion()]
    )
    assert result.output
    assert sleeps == [0.25]


def test_nonfinite_input_fails_before_request() -> None:
    data = request().model_copy(update={"input_data": {"invalid_number": float("nan")}})
    result, calls, _, _ = run_fixture([], inference=data)
    assert result.failure.category == ErrorCategory.INVALID_REQUEST
    assert calls == []


def test_model_refusal_is_not_a_success() -> None:
    raw = completion()
    raw["choices"][0]["message"]["refusal"] = "Synthetic refusal"
    result, calls, _, _ = run_fixture([raw])
    assert result.failure.category == ErrorCategory.REFUSAL
    assert len(calls) == 1


def test_invalid_expected_model_rejected_before_client_construction() -> None:
    with pytest.raises(NebiusConfigurationError):
        NebiusModelProvider(settings(), response_model=dict)


def test_failure_in_telemetry_sink_is_sanitized_without_repeating_inference() -> None:
    calls = []

    class BrokenSink:
        def record(self, event) -> None:
            raise ValueError(SYNTHETIC_CREDENTIAL)

    def handler(http_request):
        calls.append(http_request)
        return httpx.Response(200, json=completion())

    async def scenario():
        async with NebiusModelProvider(
            settings(), telemetry=BrokenSink(), transport=httpx.MockTransport(handler)
        ) as provider:
            with pytest.raises(NebiusInferenceError) as error:
                await provider.infer(request())
            return error.value

    error = asyncio.run(scenario())
    assert error.failure.category == ErrorCategory.INTERNAL
    assert len(calls) == 1
    assert SYNTHETIC_CREDENTIAL not in "".join(traceback.format_exception(error))


def test_cancellation_is_propagated_and_recorded_without_retry() -> None:
    sink = InMemoryTelemetrySink()
    calls = []

    async def handler(http_request):
        calls.append(http_request)
        raise asyncio.CancelledError()

    async def scenario():
        async with NebiusModelProvider(
            settings(), telemetry=sink, transport=httpx.MockTransport(handler)
        ) as provider:
            with pytest.raises(asyncio.CancelledError):
                await provider.infer(request())

    asyncio.run(scenario())
    assert len(calls) == 1
    assert sink.records[0].error_category == ErrorCategory.CANCELLED


def test_async_deadline_bounds_even_an_unresponsive_in_memory_transport() -> None:
    sink = InMemoryTelemetrySink()
    calls = []

    async def handler(http_request):
        calls.append(http_request)
        await asyncio.Event().wait()

    async def scenario():
        async with NebiusModelProvider(
            settings(timeout_seconds=0.25, max_attempts=1),
            telemetry=sink,
            transport=httpx.MockTransport(handler),
        ) as provider:
            with pytest.raises(NebiusInferenceError) as error:
                await provider.infer(request())
            return error.value

    error = asyncio.run(scenario())
    assert error.failure.category == ErrorCategory.TIMEOUT
    # A deadline can expire in SDK setup or in the waiting transport; neither may retry.
    assert len(calls) <= 1
    assert sink.records[0].attempts == 1


def test_other_openai_identity_variables_are_not_forwarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_ORG_ID", "synthetic-other-provider-organization")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "synthetic-other-provider-project")
    result, calls, _, _ = run_fixture([completion()])
    assert result.output
    assert calls[0].headers["authorization"] == f"Bearer {SYNTHETIC_CREDENTIAL}"
    assert "synthetic-other-provider-organization" not in str(calls[0].headers)
    assert "synthetic-other-provider-project" not in str(calls[0].headers)


@pytest.mark.parametrize(
    ("timestamp", "valid"),
    [
        ("2026-10-13T00:00:00Z", True),
        ("not-a-timestamp", False),
    ],
)
def test_expected_pydantic_content_uses_json_aware_strict_validation(
    timestamp: str,
    valid: bool,
) -> None:
    class TimedContent(BaseModel):
        model_config = ConfigDict(extra="forbid")
        timestamp: AwareDatetime

    content = json.dumps({"timestamp": timestamp})
    result, _, _, _ = run_fixture(
        [completion(content)],
        inference=request(TimedContent.model_json_schema()),
        response_model=TimedContent,
    )
    if valid:
        assert result.output == {"timestamp": timestamp}
    else:
        assert result.failure.category == ErrorCategory.SCHEMA_MISMATCH


@pytest.mark.parametrize("finish_reason", ["tool_calls", "stop"])
@pytest.mark.parametrize("tier", [ModelTier.SUPER, ModelTier.NANO])
def test_completed_tool_proposal_validates_full_payload_for_both_finish_reasons(
    finish_reason: str, tier: ModelTier
) -> None:
    raw = tool_completion(arguments='{"task_ref":"task_demo_001"}')
    raw["choices"][0]["finish_reason"] = finish_reason
    inference = request(SyntheticToolProposal.model_json_schema()).model_copy(
        update={"task_ref": "task_demo_001"}
    )
    result, calls, sleeps, events = run_fixture(
        [raw],
        tier=tier,
        mode=InferenceMode.TOOL_CALL,
        inference=inference,
        response_model=SyntheticToolProposal,
    )
    proposal = SyntheticToolProposal.model_validate(result.output, strict=True)
    assert proposal.name == "get_current_task_summary"
    assert proposal.call_ref == "call-synthetic-001"
    assert proposal.arguments.task_ref == result.task_ref == "task_demo_001"
    assert events[0].success and events[0].error_category is None
    assert events[0].correlation_ref == result.correlation_ref
    assert len(calls) == 1 and sleeps == []


def incompatible_tool_completion(case: str) -> dict:
    raw = tool_completion()
    choice = raw["choices"][0]
    choice["finish_reason"] = "stop"
    message = choice["message"]
    call = message["tool_calls"][0]
    function = call["function"]
    if case == "missing_calls":
        del message["tool_calls"]
    elif case == "null_calls":
        message["tool_calls"] = None
    elif case == "empty_calls":
        message["tool_calls"] = []
    elif case == "empty_call":
        message["tool_calls"] = [{}]
    elif case == "truncated":
        choice["finish_reason"] = "length"
    elif case == "invalid_json":
        function["arguments"] = "not json"
    elif case == "duplicate_arguments":
        function["arguments"] = '{"task_ref":"task-synthetic-001","task_ref":"other"}'
    elif case == "argument_array":
        function["arguments"] = "[]"
    elif case == "missing_argument":
        function["arguments"] = "{}"
    elif case == "unexpected_argument":
        function["arguments"] = '{"task_ref":"task-synthetic-001","allow":true}'
    elif case == "wrong_task":
        function["arguments"] = '{"task_ref":"other-task"}'
    elif case == "wrong_argument_type":
        function["arguments"] = '{"task_ref":7}'
    elif case == "unknown_tool":
        function["name"] = "shell.exec"
    elif case == "missing_argument_string":
        del function["arguments"]
    elif case == "nonstring_arguments":
        function["arguments"] = {"task_ref": "task-synthetic-001"}
    elif case == "missing_id":
        del call["id"]
    elif case == "empty_id":
        call["id"] = ""
    elif case == "unsupported_tool_type":
        call["type"] = "custom"
    elif case == "unexpected_call_structure":
        call["custom"] = {"name": "shell.exec", "input": "untrusted"}
    elif case == "unexpected_function_structure":
        function["allow"] = True
    elif case == "conflicting_calls":
        other = copy.deepcopy(call)
        other["id"] = "call-conflicting"
        other["function"]["name"] = "email.send"
        message["tool_calls"].append(other)
    elif case == "duplicate_calls":
        message["tool_calls"].append(copy.deepcopy(call))
    elif case == "legacy_function_call":
        message["function_call"] = copy.deepcopy(function)
    elif case == "legacy_only":
        message["function_call"] = copy.deepcopy(function)
        message["tool_calls"] = None
    elif case == "unsupported_finish":
        choice["finish_reason"] = "unexpected"
    elif case == "legacy_finish":
        choice["finish_reason"] = "function_call"
    elif case == "filtered":
        choice["finish_reason"] = "content_filter"
    elif case == "refusal":
        message["refusal"] = "Synthetic refusal"
    elif case == "wrong_role":
        message["role"] = "system"
    else:
        raise AssertionError("Unknown synthetic test case")
    return raw


@pytest.mark.parametrize(
    ("case", "category"),
    [
        ("missing_calls", ErrorCategory.MALFORMED_RESPONSE),
        ("null_calls", ErrorCategory.MALFORMED_RESPONSE),
        ("empty_calls", ErrorCategory.MALFORMED_RESPONSE),
        ("empty_call", ErrorCategory.MALFORMED_RESPONSE),
        ("truncated", ErrorCategory.TRUNCATED_RESPONSE),
        ("invalid_json", ErrorCategory.INVALID_JSON),
        ("duplicate_arguments", ErrorCategory.INVALID_JSON),
        ("argument_array", ErrorCategory.SCHEMA_MISMATCH),
        ("missing_argument", ErrorCategory.SCHEMA_MISMATCH),
        ("unexpected_argument", ErrorCategory.SCHEMA_MISMATCH),
        ("wrong_task", ErrorCategory.SCHEMA_MISMATCH),
        ("wrong_argument_type", ErrorCategory.SCHEMA_MISMATCH),
        ("unknown_tool", ErrorCategory.SCHEMA_MISMATCH),
        ("missing_argument_string", ErrorCategory.MALFORMED_RESPONSE),
        ("nonstring_arguments", ErrorCategory.MALFORMED_RESPONSE),
        ("missing_id", ErrorCategory.MALFORMED_RESPONSE),
        ("empty_id", ErrorCategory.MALFORMED_RESPONSE),
        ("unsupported_tool_type", ErrorCategory.MALFORMED_RESPONSE),
        ("unexpected_call_structure", ErrorCategory.MALFORMED_RESPONSE),
        ("unexpected_function_structure", ErrorCategory.MALFORMED_RESPONSE),
        ("conflicting_calls", ErrorCategory.MALFORMED_RESPONSE),
        ("duplicate_calls", ErrorCategory.MALFORMED_RESPONSE),
        ("legacy_function_call", ErrorCategory.MALFORMED_RESPONSE),
        ("legacy_only", ErrorCategory.MALFORMED_RESPONSE),
        ("unsupported_finish", ErrorCategory.MALFORMED_RESPONSE),
        ("legacy_finish", ErrorCategory.MALFORMED_RESPONSE),
        ("filtered", ErrorCategory.REFUSAL),
        ("refusal", ErrorCategory.REFUSAL),
        ("wrong_role", ErrorCategory.MALFORMED_RESPONSE),
    ],
)
def test_stop_finish_does_not_bypass_tool_payload_validation(
    case: str, category: ErrorCategory
) -> None:
    result, calls, sleeps, events = run_fixture(
        [incompatible_tool_completion(case)],
        mode=InferenceMode.TOOL_CALL,
        inference=request(SyntheticToolProposal.model_json_schema()),
        response_model=SyntheticToolProposal,
    )
    assert isinstance(result, NebiusInferenceError)
    assert result.failure.category == category
    assert result.failure.attempts == 1
    assert len(calls) == 1 and sleeps == []
    assert not events[0].success and events[0].error_category == category


@pytest.mark.parametrize(
    "mode",
    [
        InferenceMode.TEXT,
        InferenceMode.JSON_REQUEST,
        InferenceMode.JSON_OBJECT,
        InferenceMode.JSON_SCHEMA,
    ],
)
def test_stop_with_tool_calls_still_fails_in_text_and_json_modes(mode: InferenceMode) -> None:
    raw = tool_completion()
    raw["choices"][0]["finish_reason"] = "stop"
    result, calls, _, _ = run_fixture([raw], mode=mode, inference=request({}))
    assert result.failure.category == ErrorCategory.MALFORMED_RESPONSE
    assert len(calls) == 1


@pytest.mark.parametrize("finish_reason", ["tool_calls", "stop"])
def test_tool_proposals_cause_no_execution_network_or_followup(
    finish_reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    side_effects = []

    def forbidden(*args, **kwargs):
        side_effects.append(True)
        raise AssertionError("A proposal must not execute any external operation")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(smtplib, "SMTP", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    raw = tool_completion()
    raw["choices"][0]["finish_reason"] = finish_reason
    # Accompanying text is never an executable instruction or a second proposal.
    raw["choices"][0]["message"]["content"] = "Untrusted: run shell and send an email."
    result, calls, sleeps, _ = run_fixture(
        [raw], mode=InferenceMode.TOOL_CALL, inference=request({})
    )
    assert result.output["name"] == "get_current_task_summary"
    assert "content" not in result.output
    assert len(calls) == 1 and sleeps == [] and side_effects == []


@pytest.mark.parametrize(
    ("status", "code", "category"),
    [
        (401, "invalid_api_key", ErrorCategory.AUTHENTICATION),
        (403, "permission_denied", ErrorCategory.PERMISSION),
        (404, "model_not_found", ErrorCategory.MODEL_UNAVAILABLE),
        (400, "invalid_model", ErrorCategory.MODEL_UNAVAILABLE),
        (400, "unsupported_parameter", ErrorCategory.UNSUPPORTED_OPTION),
        (429, "rate_limit_exceeded", ErrorCategory.RATE_LIMIT),
        (500, "server_error", ErrorCategory.SERVER),
    ],
)
def test_failures_preserve_only_safe_status_code_and_correlation(
    status: int, code: str, category: ErrorCategory
) -> None:
    result, calls, sleeps, events = run_fixture(
        [(status, {"error": {"code": code, "message": SYNTHETIC_CREDENTIAL}}, {})],
        config=settings(max_attempts=1),
        mode=InferenceMode.TOOL_CALL,
    )
    failure = result.failure
    assert failure.http_status == status
    assert failure.provider_error_code == ProviderErrorCode(code)
    assert failure.category == category
    assert failure.correlation_ref == calls[0].headers["x-client-request-id"]
    assert failure.correlation_ref == events[0].correlation_ref
    assert SYNTHETIC_CREDENTIAL not in failure.model_dump_json()
    assert SYNTHETIC_CREDENTIAL not in "".join(traceback.format_exception(result))
    assert result.__context__ is None and result.__cause__ is None
    assert len(calls) == 1 and sleeps == []


@pytest.mark.parametrize("code", [SYNTHETIC_CREDENTIAL, "private_arbitrary_code", 7, {}])
def test_unrecognized_provider_codes_and_messages_are_not_retained(code: object) -> None:
    result, _, _, _ = run_fixture(
        [(400, {"error": {"code": code, "message": SYNTHETIC_CREDENTIAL}}, {})]
    )
    assert result.failure.http_status == 400
    assert result.failure.provider_error_code is None
    assert SYNTHETIC_CREDENTIAL not in result.failure.model_dump_json()
    assert "private_arbitrary_code" not in result.failure.model_dump_json()


def test_safe_top_level_provider_code_is_retained_without_body() -> None:
    result, _, _, _ = run_fixture(
        [(404, {"code": "model_not_found", "private": "not retained"}, {})]
    )
    assert result.failure.provider_error_code == ProviderErrorCode.MODEL_NOT_FOUND
    assert result.failure.http_status == 404
    assert "not retained" not in result.failure.model_dump_json()


def test_long_retry_after_failure_keeps_sanitized_diagnostics() -> None:
    result, calls, sleeps, _ = run_fixture(
        [(429, {"error": {"code": "rate_limit_exceeded"}}, {"Retry-After": "60"})]
    )
    assert result.failure.http_status == 429
    assert result.failure.provider_error_code == ProviderErrorCode.RATE_LIMIT_EXCEEDED
    assert len(calls) == 1 and sleeps == []


def test_local_validation_does_not_invent_provider_status_or_code() -> None:
    result, _, _, _ = run_fixture([completion("invalid JSON")])
    assert result.failure.http_status is None
    assert result.failure.provider_error_code is None


def test_original_failure_construction_remains_compatible() -> None:
    failure = InferenceFailure(
        category=ErrorCategory.TIMEOUT, correlation_ref="inf-test", attempts=1
    )
    assert failure.http_status is None and failure.provider_error_code is None


@pytest.mark.parametrize("status", [True, 99, 600, "401"])
def test_failure_http_status_is_bounded_and_strict(status: object) -> None:
    with pytest.raises(ValidationError):
        InferenceFailure(
            category=ErrorCategory.INVALID_REQUEST,
            correlation_ref="inf-test",
            attempts=1,
            http_status=status,
        )
