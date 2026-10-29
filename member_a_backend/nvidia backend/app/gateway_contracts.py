"""Gateway wire contracts; HTTP admission remains non-dispatching."""

import json
import re
from datetime import UTC
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, Field, StringConstraints, field_validator, model_validator

from app.agent_schemas import Action, IdentityModel, Purpose, ResourceReference, ResourceVersion

OpaqueReference = ResourceReference
NonEmailAction = Literal["files.list_authorized", "files.read", "tasks.list"]


class ListArguments(IdentityModel):
    pass


class FileArguments(IdentityModel):
    resource_id: OpaqueReference


class EmailArguments(IdentityModel):
    recipient: Annotated[str, Field(min_length=1, max_length=254, repr=False)]
    subject: Annotated[str, Field(min_length=1, max_length=200, repr=False)]
    body: Annotated[str, Field(min_length=1, max_length=20000, repr=False)]
    attachment_resource_ids: tuple[OpaqueReference, ...] = Field(default=(), max_length=20)

    @field_validator("recipient")
    @classmethod
    def mailbox(cls, value):
        if not re.fullmatch(
            r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", value
        ):
            raise ValueError("A bare ASCII mailbox is required")
        local, domain = value.rsplit("@", 1)
        if (
            len(local) > 64
            or local.startswith(".")
            or local.endswith(".")
            or ".." in local
            or any(
                len(label) > 63 or label.startswith("-") or label.endswith("-")
                for label in domain.split(".")
            )
        ):
            raise ValueError("Invalid mailbox syntax")
        return local + "@" + domain.lower()

    @field_validator("subject")
    @classmethod
    def header_controls(cls, value):
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Header controls are forbidden")
        return value

    @field_validator("attachment_resource_ids")
    @classmethod
    def unique_attachments(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Duplicate attachments are forbidden")
        return value

    @field_validator("body", "subject")
    @classmethod
    def utf8_text(cls, value):
        try:
            encoded = value.encode("utf-8", errors="strict")
        except UnicodeError:
            raise ValueError("UTF-8 text required") from None
        if len(encoded) > 32768 or any(
            (ord(char) < 32 and char not in "\r\n\t") or ord(char) == 127 for char in value
        ):
            raise ValueError("Unsupported message text")
        return value


ARGUMENT_TYPES = {
    "files.list_authorized": ListArguments,
    "files.read": FileArguments,
    "email.draft": EmailArguments,
    "email.send": EmailArguments,
    "tasks.list": ListArguments,
}


class ToolRequest(IdentityModel):
    request_id: OpaqueReference
    task_ref: OpaqueReference
    action: Action
    purpose: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    arguments: ListArguments | FileArguments | EmailArguments
    idempotency_key: OpaqueReference

    @model_validator(mode="before")
    @classmethod
    def parse_arguments(cls, value: Any):
        if not isinstance(value, dict):
            return value
        action = value.get("action")
        if not isinstance(action, str) or action not in ARGUMENT_TYPES:
            return value
        args = value.get("arguments")
        if isinstance(args, IdentityModel):
            args = args.model_dump(mode="json")
        return {**value, "arguments": ARGUMENT_TYPES[action].model_validate_json(json.dumps(args))}

    @model_validator(mode="after")
    def action_arguments(self):
        if not isinstance(self.arguments, ARGUMENT_TYPES[self.action]):
            raise ValueError("Arguments do not match action")
        return self


class ConsentCreate(IdentityModel):
    action: NonEmailAction
    purpose: Purpose
    resource_ids: tuple[OpaqueReference, ...] = Field(max_length=20)
    expires_at: AwareDatetime

    @field_validator("expires_at")
    @classmethod
    def utc_expiry(cls, value):
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def exact_resources(self):
        if len(set(self.resource_ids)) != len(self.resource_ids):
            raise ValueError("Resource IDs must be unique")
        if self.action == "files.read" and len(self.resource_ids) != 1:
            raise ValueError("File read requires one resource")
        if self.action == "tasks.list" and self.resource_ids:
            raise ValueError("Task listing has no document resources")
        return self


class Authorization(IdentityModel):
    decision: Literal["ALLOW", "DENY", "APPROVAL_REQUIRED"]
    reason_code: Literal[
        "EXECUTION_NOT_STARTED",
        "EXECUTION_SUCCEEDED",
        "TOOL_FAILED_NO_EFFECT",
        "APPROVAL_UNAVAILABLE",
        "AUTH_INVALID",
        "TASK_SCOPE_MISMATCH",
        "ACTION_DISABLED",
        "TASK_NOT_ACTIVE",
        "PURPOSE_MISMATCH",
        "RESOURCE_NOT_AUTHORIZED",
        "RESOURCE_VERSION_CHANGED",
        "RECIPIENT_NOT_AUTHORIZED",
        "CONSENT_AMBIGUOUS",
        "CONSENT_EXPIRED",
        "CONSENT_REVOKED",
        "EXECUTION_UNCONFIRMED",
        "CONSENT_REVIEW_REQUIRED",
        "APPROVAL_REJECTED",
        "APPROVAL_EXPIRED",
        "APPROVAL_REVOKED",
        "EMAIL_CONTENT_NOT_AUTHORIZED",
        "SEND_SLOT_CLAIMED",
        "SEND_RECONCILIATION_REQUIRED",
    ]


class SimulatedFileResult(IdentityModel):
    resource_id: OpaqueReference
    version_ref: OpaqueReference
    content_type: Literal["text/plain"] = "text/plain"
    text: Literal["SIMULATED: no document was read."] = "SIMULATED: no document was read."


class DocumentFileResult(IdentityModel):
    resource_id: OpaqueReference
    version_ref: OpaqueReference
    content_type: Literal["text/plain"] = "text/plain"
    text: str = Field(max_length=20000, repr=False)


class EmailDraftResult(IdentityModel):
    draft_ref: OpaqueReference
    payload_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class EmailSendResult(IdentityModel):
    receipt_ref: OpaqueReference
    submission_state: Literal["ACCEPTED"] = "ACCEPTED"


class ToolResponse(Authorization):
    request_id: OpaqueReference
    execution_status: Literal["NOT_EXECUTED", "UNKNOWN", "SUCCEEDED", "FAILED"] = "NOT_EXECUTED"
    approval_ref: OpaqueReference | None = None
    result: SimulatedFileResult | DocumentFileResult | EmailDraftResult | EmailSendResult | None = (
        None
    )
    audit_event_ref: OpaqueReference

    @model_validator(mode="after")
    def historical_uncertainty(self):
        if (self.execution_status == "SUCCEEDED") != (self.result is not None):
            raise ValueError("Only confirmed success has a result")
        terminal_reasons = {"SUCCEEDED": "EXECUTION_SUCCEEDED", "FAILED": "TOOL_FAILED_NO_EFFECT"}
        if self.execution_status in terminal_reasons and (
            self.decision != "ALLOW" or self.reason_code != terminal_reasons[self.execution_status]
        ):
            raise ValueError("Terminal outcomes require their recorded authorized reason")
        if self.execution_status == "NOT_EXECUTED" and self.reason_code in (
            "EXECUTION_SUCCEEDED",
            "TOOL_FAILED_NO_EFFECT",
            "EXECUTION_UNCONFIRMED",
        ):
            raise ValueError("Execution reasons cannot describe an unexecuted request")
        if (self.decision == "APPROVAL_REQUIRED") != (self.approval_ref is not None):
            raise ValueError("Only durable pending approvals have an approval reference")
        if self.decision == "APPROVAL_REQUIRED" and self.reason_code != "CONSENT_REVIEW_REQUIRED":
            raise ValueError("Pending approval requires the review reason")
        if self.execution_status == "UNKNOWN" and (
            self.decision != "ALLOW" or self.reason_code != "EXECUTION_UNCONFIRMED"
        ):
            raise ValueError("Uncertainty requires a recorded authorized attempt")
        return self


class OperationStatus(IdentityModel):
    operation_ref: OpaqueReference
    request_id: OpaqueReference
    task_ref: OpaqueReference
    operation_state: Literal[
        "ADMITTED",
        "PENDING_APPROVAL",
        "READY",
        "DENIED",
        "DISPATCHING",
        "UNKNOWN",
        "SUCCEEDED",
        "FAILED",
    ]
    decision: Literal["ALLOW", "DENY", "APPROVAL_REQUIRED"]
    execution_status: Literal["NOT_EXECUTED", "UNKNOWN", "SUCCEEDED", "FAILED"]
    reason_code: OpaqueReference
    approval_ref: OpaqueReference | None = None
    approval_state: Literal["PENDING", "APPROVED", "REJECTED", "EXPIRED", "REVOKED"] | None = None
    resume_ref: OpaqueReference | None = None
    audit_event_ref: OpaqueReference
    revision: int = Field(ge=0)


class ApprovalResolution(IdentityModel):
    resolution: Literal["APPROVE", "REJECT"]


class ApprovalReview(IdentityModel):
    approval_ref: OpaqueReference
    operation_ref: OpaqueReference
    request_id: OpaqueReference
    task_ref: OpaqueReference
    action: Action
    purpose: Purpose
    arguments: ListArguments | FileArguments | EmailArguments = Field(repr=False)
    resource_versions: tuple[ResourceVersion, ...]
    binding_digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    state: Literal["PENDING", "APPROVED", "REJECTED", "EXPIRED", "REVOKED"]
    expires_at: AwareDatetime
