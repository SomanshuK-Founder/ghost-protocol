"""PROVISIONAL wire contracts for Member A's trusted gateway.

Validation restricts the shape of proposals; it does not authorize them.
Untrusted argument/result text is data and never instruction authority.
"""

from enum import StrEnum
from typing import Annotated, Any, Protocol, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    model_validator,
)

OpaqueReference = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
]
BoundedText = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=500)
]


class ContractModel(BaseModel):
    """Reject extra authority fields and hide inputs in printable validation errors.

    Nested JSON remains data. Never log ValidationError.errors(), which can
    include raw inputs, or full model dumps containing private content.
    """

    model_config = ConfigDict(
        extra="forbid", frozen=True, hide_input_in_errors=True, validate_default=True
    )


class ToolAction(StrEnum):
    FILES_LIST_AUTHORIZED = "files.list_authorized"
    FILES_READ = "files.read"
    EMAIL_DRAFT = "email.draft"
    EMAIL_SEND = "email.send"
    TASKS_LIST = "tasks.list"


class ScopedListArguments(ContractModel):
    """Scope is resolved by A from authenticated task identity, never raw paths."""


class FileReadArguments(ContractModel):
    resource_id: OpaqueReference


class EmailArguments(ContractModel):
    # Minimal wire shape, not email deliverability or recipient authorization.
    recipient: Annotated[
        str,
        StringConstraints(strict=True, max_length=254, pattern=r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$"),
    ]
    subject: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=200)]
    body: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=20000)]
    attachment_resource_ids: tuple[OpaqueReference, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def reject_header_newlines(self) -> Self:
        if "\r" in self.subject or "\n" in self.subject:
            raise ValueError("Subject must be a single line")
        return self


_ARGUMENT_TYPES = {
    ToolAction.FILES_LIST_AUTHORIZED: ScopedListArguments,
    ToolAction.FILES_READ: FileReadArguments,
    ToolAction.EMAIL_DRAFT: EmailArguments,
    ToolAction.EMAIL_SEND: EmailArguments,
    ToolAction.TASKS_LIST: ScopedListArguments,
}


class ToolRequest(ContractModel):
    request_id: OpaqueReference
    task_ref: OpaqueReference
    action: ToolAction
    purpose: BoundedText
    arguments: ScopedListArguments | FileReadArguments | EmailArguments
    idempotency_key: OpaqueReference

    @model_validator(mode="before")
    @classmethod
    def parse_action_arguments(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        try:
            action = ToolAction(data.get("action"))
        except (ValueError, TypeError):
            return data  # Enum validation rejects unsupported actions.
        argument_type = _ARGUMENT_TYPES[action]
        arguments = data.get("arguments")
        if isinstance(arguments, BaseModel):
            arguments = arguments.model_dump(mode="python")
        return {**data, "arguments": argument_type.model_validate(arguments)}

    @model_validator(mode="after")
    def validate_argument_type(self) -> Self:
        if not isinstance(self.arguments, _ARGUMENT_TYPES[self.action]):
            raise ValueError("Arguments do not match the requested action")
        return self


class AuthorizationDecision(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"


class ExecutionStatus(StrEnum):
    NOT_EXECUTED = "NOT_EXECUTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class ToolResponse(ContractModel):
    request_id: OpaqueReference
    decision: AuthorizationDecision
    execution_status: ExecutionStatus
    reason_code: OpaqueReference
    approval_ref: OpaqueReference | None = None
    result: JsonValue = None
    audit_event_ref: OpaqueReference | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.decision != AuthorizationDecision.ALLOW:
            if self.execution_status != ExecutionStatus.NOT_EXECUTED or self.result is not None:
                raise ValueError("A denied or pending request must not have an execution result")
        if self.decision == AuthorizationDecision.APPROVAL_REQUIRED and self.approval_ref is None:
            raise ValueError("Approval-required response must identify the pending approval")
        if self.execution_status == ExecutionStatus.NOT_EXECUTED and self.result is not None:
            raise ValueError("An unexecuted request must not have an execution result")
        return self


class ToolGateway(Protocol):
    """Only A can bind trusted identity, authorize, and execute protected tools.

    Decision/execution failures use ToolResponse; transport failures may raise
    sanitized exceptions. Never retry a consequential UNKNOWN outcome blindly.
    Transport, authentication, and concrete error types require A's sign-off.
    """

    async def execute(self, request: ToolRequest) -> ToolResponse: ...
