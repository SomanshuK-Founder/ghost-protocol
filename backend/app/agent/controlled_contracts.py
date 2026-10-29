"""Strict v1.3 execution observations, not authorization authority."""

from typing import Literal

from pydantic import Field, model_validator

from app.agent.gateway_protocol import ContractModel as Model
from app.agent.gateway_protocol import OpaqueReference as Reference


class ResumeExecution(Model):
    resume_ref: Reference


class SimulatedResult(Model):
    resource_id: Reference
    version_ref: Reference
    content_type: Literal["text/plain"]
    text: Literal["SIMULATED: no document was read."]


class DraftResult(Model):
    draft_ref: Reference
    payload_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class SendResult(Model):
    receipt_ref: Reference
    submission_state: Literal["ACCEPTED"]


class ControlledExecutionResult(Model):
    contract_version: Literal["gw-execution-v1.3"]
    task_ref: Reference
    operation_ref: Reference
    attempt_ref: Reference
    workflow_ref: Reference
    request_id: Reference
    idempotency_key: Reference
    audit_event_ref: Reference
    decision: Literal["ALLOW"]
    admission: Literal["ADMITTED"]
    execution_status: Literal["SUCCEEDED", "FAILED", "UNKNOWN"]
    mode: Literal["SIMULATED", "EMAIL_DRAFT", "MAILPIT_SEND"]
    effect: Literal["SIMULATED", "NO_MESSAGE_SUBMISSION", "MAILPIT_TEST_ONLY"]
    result: SimulatedResult | DraftResult | SendResult | None
    sanitized_error_code: (
        Literal[
            "SIMULATED_FAILURE",
            "SIMULATED_UNKNOWN",
            "EXECUTOR_TIMEOUT",
            "EXECUTOR_UNCONFIRMED",
            "MAILPIT_NOT_ACCEPTED",
            "MAILPIT_UNCONFIRMED",
        ]
        | None
    )
    replayed: bool = Field(strict=True)

    @model_validator(mode="after")
    def consistent(self):
        shape, effect = {
            "SIMULATED": (SimulatedResult, "SIMULATED"),
            "EMAIL_DRAFT": (DraftResult, "NO_MESSAGE_SUBMISSION"),
            "MAILPIT_SEND": (SendResult, "MAILPIT_TEST_ONLY"),
        }[self.mode]
        if self.effect != effect:
            raise ValueError("Invalid execution provenance")
        if self.execution_status == "SUCCEEDED":
            if not isinstance(self.result, shape) or self.sanitized_error_code is not None:
                raise ValueError("Invalid successful execution")
        else:
            errors = {"EXECUTOR_TIMEOUT", "EXECUTOR_UNCONFIRMED"}
            errors |= (
                (
                    {"SIMULATED_FAILURE"}
                    if self.execution_status == "FAILED"
                    else {"SIMULATED_UNKNOWN"}
                )
                if self.mode == "SIMULATED"
                else (
                    {"MAILPIT_NOT_ACCEPTED"}
                    if self.execution_status == "FAILED"
                    else {"MAILPIT_UNCONFIRMED"}
                )
            )
            if self.result is not None or self.sanitized_error_code not in errors:
                raise ValueError("Invalid execution failure")
            if self.execution_status == "FAILED" and self.sanitized_error_code in {
                "EXECUTOR_TIMEOUT",
                "EXECUTOR_UNCONFIRMED",
            }:
                raise ValueError("Uncertain execution cannot be a known failure")
        return self
