"""Untrusted output parsing and schema checks with no external reference retrieval."""

import json
import math
from typing import Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictStr
from referencing import Registry
from referencing.exceptions import NoSuchResource, Unresolvable

from app.agent.gateway_protocol import ContractModel, OpaqueReference
from app.llm.errors import ErrorCategory


class OutputValidationError(ValueError):
    def __init__(self, category: ErrorCategory) -> None:
        self.category = category
        super().__init__(category.value)


class SyntheticToolArguments(ContractModel):
    task_ref: OpaqueReference


class SyntheticToolProposal(ContractModel):
    name: Literal["get_current_task_summary"]
    call_ref: OpaqueReference
    arguments: SyntheticToolArguments


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    prompt_tokens: int | None = Field(default=None, strict=True, ge=0)
    completion_tokens: int | None = Field(default=None, strict=True, ge=0)
    total_tokens: int | None = Field(default=None, strict=True, ge=0)


class WireFunction(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    name: StrictStr
    arguments: StrictStr


class WireToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    id: OpaqueReference
    type: Literal["function"]
    function: WireFunction


class WireMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    role: Literal["assistant"]
    content: StrictStr | None = None
    refusal: StrictStr | None = None
    tool_calls: list[WireToolCall] | None = None
    function_call: JsonValue = None  # Retain legacy structures only so they can be rejected.


class WireChoice(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    finish_reason: Literal["stop", "tool_calls", "length", "content_filter", "function_call"]
    message: WireMessage


class CompletionEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    choices: list[WireChoice]
    usage: TokenUsage | None = None


def _reject_constant(value: str) -> None:
    raise ValueError("Nonstandard JSON numeric constant")


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object field")
        result[key] = value
    return result


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("Non-finite JSON number")
    return parsed


def parse_json_object(content: str) -> dict:
    try:
        value = json.loads(
            content,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
            object_pairs_hook=_unique_object,
        )
    except (ValueError, RecursionError):
        raise OutputValidationError(ErrorCategory.INVALID_JSON) from None
    if not isinstance(value, dict):
        raise OutputValidationError(ErrorCategory.SCHEMA_MISMATCH)
    return value


def _no_retrieval(uri: str) -> None:
    raise NoSuchResource(ref=uri)


def output_validator(schema: dict) -> Draft202012Validator:
    """Draft 2020-12 only; local fragments supported, network/file $refs rejected."""

    def inspect(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ("$ref", "$dynamicRef") and (
                    not isinstance(item, str) or not item.startswith("#")
                ):
                    raise OutputValidationError(ErrorCategory.INVALID_REQUEST)
                if key == "$schema" and item != "https://json-schema.org/draft/2020-12/schema":
                    raise OutputValidationError(ErrorCategory.INVALID_REQUEST)
                inspect(item)
        elif isinstance(value, list):
            for item in value:
                inspect(item)

    try:
        inspect(schema)
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema, registry=Registry(retrieve=_no_retrieval))
    except (SchemaError, RecursionError):
        raise OutputValidationError(ErrorCategory.INVALID_REQUEST) from None


def validate_output(output: dict, validator: Draft202012Validator) -> None:
    try:
        validator.validate(output)
    except (JsonSchemaValidationError, Unresolvable, RecursionError):
        raise OutputValidationError(ErrorCategory.SCHEMA_MISMATCH) from None
