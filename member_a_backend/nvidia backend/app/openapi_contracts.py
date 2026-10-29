"""Documentation DTOs and schemas; existing bounded request parsers remain authoritative."""

from typing import Literal

from pydantic import AwareDatetime, JsonValue

from app.agent_schemas import IdentityModel
from app.application_contracts import ApprovalState
from app.gateway_contracts import OpaqueReference


class ConsentGrantResult(IdentityModel):
    consent_ref: OpaqueReference
    state: Literal["ACTIVE"]
    expires_at: AwareDatetime


class ConsentRevokeResult(IdentityModel):
    state: Literal["REVOKED"]
    in_flight: bool


class PendingApprovalItem(IdentityModel):
    approval_ref: OpaqueReference
    operation_ref: OpaqueReference
    request_id: OpaqueReference
    state: Literal["PENDING"]
    expires_at: AwareDatetime


class PendingApprovalList(IdentityModel):
    approvals: list[PendingApprovalItem]


class ApprovalResolutionResult(IdentityModel):
    approval_ref: OpaqueReference
    state: ApprovalState
    expires_at: AwareDatetime
    audit_event_ref: OpaqueReference


class ApprovalRevokeResult(ApprovalResolutionResult):
    in_flight: bool


class LegacyToolResult(IdentityModel):
    result: dict[str, JsonValue]


class GatewayError(IdentityModel):
    error_code: str
    message: Literal["Request cannot be processed"]
    correlation_ref: str
    request_id: str | None
    audit_event_ref: str | None
    execution_uncertain: bool


class DetailError(IdentityModel):
    detail: str


def request_body(model):
    return {
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": model.model_json_schema(ref_template="#/components/schemas/{model}")
                }
            },
        }
    }
