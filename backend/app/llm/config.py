"""Trusted-process configuration; never reads .env implicitly or enters a sandbox."""

import os
import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from app.llm.errors import NebiusConfigurationError


class ModelTier(StrEnum):
    SUPER = "SUPER"
    NANO = "NANO"


class InferenceMode(StrEnum):
    TEXT = "TEXT"
    JSON_REQUEST = "JSON_REQUEST"
    JSON_OBJECT = "JSON_OBJECT"
    JSON_SCHEMA = "JSON_SCHEMA"
    TOOL_CALL = "TOOL_CALL"


class NebiusSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    api_key: SecretStr = Field(repr=False)
    base_url: HttpUrl = Field(repr=False)
    model_super: str | None = Field(default=None, repr=False)
    model_nano: str | None = Field(default=None, repr=False)
    timeout_seconds: float = Field(default=30, gt=0, le=120, allow_inf_nan=False)
    max_attempts: int = Field(default=3, strict=True, ge=1, le=3)
    max_tokens: int = Field(default=256, strict=True, ge=1, le=4096)
    backoff_seconds: float = Field(default=0.25, ge=0, le=5, allow_inf_nan=False)
    max_retry_delay_seconds: float = Field(default=5, ge=0, le=30, allow_inf_nan=False)

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if (
            not raw
            or raw != raw.strip()
            or any(character.isspace() for character in raw)
            or not raw.isascii()
            or any(ord(character) < 33 or ord(character) > 126 for character in raw)
            or raw.casefold() in {"replace_with_your_api_key", "your_nebius_api_key_here"}
        ):
            raise ValueError("A non-placeholder API credential is required")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: HttpUrl) -> HttpUrl:
        if (
            value.scheme != "https"
            or value.username
            or value.password
            or value.query
            or value.fragment
        ):
            raise ValueError(
                "Endpoint must use HTTPS without embedded credentials, query, or fragment"
            )
        return value

    @field_validator("model_super", "model_nano", mode="before")
    @classmethod
    def validate_model_id(cls, value: object) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9/._-]{0,199}", value
        ):
            raise ValueError("Model identifier must be an explicit API identifier")
        return value

    @model_validator(mode="after")
    def validate_backoff(self) -> Self:
        if self.backoff_seconds > self.max_retry_delay_seconds:
            raise ValueError("Initial backoff must not exceed maximum retry delay")
        return self

    def model_for(self, tier: ModelTier) -> str | None:
        if tier not in (ModelTier.SUPER, ModelTier.NANO):
            raise NebiusConfigurationError("Unsupported model tier")
        return self.model_super if tier == ModelTier.SUPER else self.model_nano

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> Self:
        source = os.environ if environment is None else environment
        # Explicit None distinguishes an empty test mapping from the process environment.
        try:
            return cls(
                api_key=source.get("NEBIUS_API_KEY", ""),
                base_url=source.get("NEBIUS_BASE_URL", ""),
                model_super=source.get("NEBIUS_MODEL_SUPER"),
                model_nano=source.get("NEBIUS_MODEL_NANO"),
            )
        except ValidationError:
            raise NebiusConfigurationError(
                "Invalid Nebius configuration; check NEBIUS_API_KEY, NEBIUS_BASE_URL, "
                "NEBIUS_MODEL_SUPER, and NEBIUS_MODEL_NANO"
            ) from None
