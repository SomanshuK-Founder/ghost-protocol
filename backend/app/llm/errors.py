"""Sanitized B1 failures: no SDK exception bodies, headers, prompts, or responses."""

from enum import StrEnum

from pydantic import Field

from app.agent.gateway_protocol import ContractModel, OpaqueReference


class ErrorCategory(StrEnum):
    CONFIGURATION = "CONFIGURATION"
    AUTHENTICATION = "AUTHENTICATION"
    PERMISSION = "PERMISSION"
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT = "TIMEOUT"
    NETWORK = "NETWORK"
    SERVER = "SERVER"
    INVALID_REQUEST = "INVALID_REQUEST"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    UNSUPPORTED_OPTION = "UNSUPPORTED_OPTION"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    INVALID_JSON = "INVALID_JSON"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"
    TRUNCATED_RESPONSE = "TRUNCATED_RESPONSE"
    REFUSAL = "REFUSAL"
    CANCELLED = "CANCELLED"
    INTERNAL = "INTERNAL"


class ProviderErrorCode(StrEnum):
    """Fixed safe diagnostics; arbitrary provider strings are never retained."""

    MODEL_NOT_FOUND = "model_not_found"
    INVALID_MODEL = "invalid_model"
    MODEL_UNAVAILABLE = "model_unavailable"
    INVALID_API_KEY = "invalid_api_key"
    AUTHENTICATION_ERROR = "authentication_error"
    PERMISSION_DENIED = "permission_denied"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    INSUFFICIENT_QUOTA = "insufficient_quota"
    INVALID_REQUEST_ERROR = "invalid_request_error"
    UNSUPPORTED_PARAMETER = "unsupported_parameter"
    UNSUPPORTED_VALUE = "unsupported_value"
    UNSUPPORTED_FEATURE = "unsupported_feature"
    SERVER_ERROR = "server_error"


class InferenceFailure(ContractModel):
    category: ErrorCategory
    correlation_ref: OpaqueReference
    task_ref: OpaqueReference | None = None
    attempts: int = Field(strict=True, ge=0, le=3)
    retryable: bool = False
    http_status: int | None = Field(default=None, strict=True, ge=100, le=599)
    provider_error_code: ProviderErrorCode | None = None


class NebiusInferenceError(Exception):
    """The structured failure, not the original exception, is safe for callers."""

    def __init__(self, failure: InferenceFailure) -> None:
        self.failure = failure
        super().__init__(
            f"Inference failed: {failure.category.value}; "
            f"correlation={failure.correlation_ref}; attempts={failure.attempts}"
        )


class NebiusConfigurationError(ValueError):
    """Contains a constant diagnostic and field names only, never configuration values."""
