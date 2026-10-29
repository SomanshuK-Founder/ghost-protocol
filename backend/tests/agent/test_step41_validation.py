"""Offline-only checks of the explicit Step 41 paid-request fence."""

import asyncio
import gzip
import json

import httpx
import pytest

from app.agent.gateway_protocol import ToolRequest
from app.agent.planning_contracts import TaskPlan
from app.llm.config import InferenceMode, NebiusSettings
from app.llm.contracts import InferenceRequest
from app.llm.errors import NebiusInferenceError
from app.llm.nebius_provider import NebiusModelProvider
from tests.live.step41_validation import (
    ENDPOINT,
    MODEL,
    Budget,
    CappedTransport,
    SafetyStop,
    proposal_schema,
    read_request,
)


def parameters():
    return {
        "model": MODEL,
        "max_tokens": 1024,
        "n": 1,
        "stream": False,
        "response_format": {"type": "json_schema", "json_schema": {"strict": True}},
    }


def test_budget_is_durable_single_use_and_never_reopened(tmp_path):
    path = tmp_path / "budget.json"
    budget = Budget(path)
    for probe in "ABCD":
        budget.claim(probe)
    with pytest.raises(SafetyStop):
        budget.claim("A")
    assert len(json.loads(path.read_text())["records"]) == 4
    with pytest.raises(FileExistsError):
        Budget(path)


@pytest.mark.parametrize("change", ["host", "model", "tokens", "tools", "secret"])
def test_transport_rejects_unapproved_request_before_spending_budget(tmp_path, change):
    calls = []

    async def handler(request):
        calls.append(True)
        return httpx.Response(200, json={})

    budget = Budget(tmp_path / "budget.json")
    transport = CappedTransport(
        budget, "A", "task_one", ("SECRET_MARKER",), httpx.MockTransport(handler)
    )
    body, url = parameters(), ENDPOINT + "chat/completions"
    if change == "host":
        url = "https://unapproved.test/v1/chat/completions"
    elif change == "model":
        body["model"] = "nano"
    elif change == "tokens":
        body["max_tokens"] = 1025
    elif change == "tools":
        body["tools"] = []
    else:
        body["messages"] = [{"content": "SECRET_MARKER"}]
    with pytest.raises(SafetyStop):
        asyncio.run(transport.handle_async_request(httpx.Request("POST", url, json=body)))
    assert not calls and not budget.records


def test_failed_sdk_call_counts_once_and_no_layer_retries(tmp_path):
    calls = []

    async def failure(request):
        calls.append(True)
        raise httpx.ConnectError("Synthetic connection failure")

    budget = Budget(tmp_path / "budget.json")
    transport = CappedTransport(budget, "A", "task_one", ("SECRET",), httpx.MockTransport(failure))
    settings = NebiusSettings(
        api_key="synthetic-key",
        base_url=ENDPOINT,
        model_super=MODEL,
        max_attempts=1,
        max_tokens=1024,
        timeout_seconds=60,
    )

    async def run():
        async with NebiusModelProvider(
            settings, mode=InferenceMode.JSON_SCHEMA, response_model=TaskPlan, transport=transport
        ) as provider:
            assert provider._client.max_retries == 0
            with pytest.raises(NebiusInferenceError):
                await provider.infer(
                    InferenceRequest(
                        task_ref="task_one",
                        input_data={},
                        output_schema=TaskPlan.model_json_schema(),
                    )
                )

    asyncio.run(run())
    assert len(calls) == len(budget.records) == 1
    assert budget.records[0]["retries"] == 0


def test_read_only_probe_schema_still_uses_existing_tool_request():
    from app.llm.validation import output_validator, validate_output

    expected = read_request("task_one")
    schema = proposal_schema(expected)
    validate_output(expected.model_dump(mode="json"), output_validator(schema))
    assert ToolRequest.model_validate_json(expected.model_dump_json(), strict=True) == expected
    assert schema["properties"]["action"]["const"] == "files.read"


def test_compressed_response_is_not_decoded_twice(tmp_path):
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield gzip.compress(
                json.dumps(
                    {
                        "choices": [
                            {
                                "finish_reason": "stop",
                                "message": {"content": '{"task_ref":"task_one"}'},
                            }
                        ],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                    }
                ).encode()
            )

    async def handler(request):
        return httpx.Response(200, headers={"content-encoding": "gzip"}, stream=Stream())

    budget = Budget(tmp_path / "budget.json")
    transport = CappedTransport(budget, "A", "task_one", ("SECRET",), httpx.MockTransport(handler))
    response = asyncio.run(
        transport.handle_async_request(
            httpx.Request("POST", ENDPOINT + "chat/completions", json=parameters())
        )
    )
    assert response.json()["usage"]["total_tokens"] == 15
    assert budget.records[0]["output_tokens"] == 5
