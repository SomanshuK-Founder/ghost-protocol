"""Private backend identity types; these are not public control/request schemas."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

Reference = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")]
ResourceReference = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]
Action = Literal["files.list_authorized", "files.read", "email.draft", "email.send", "tasks.list"]
Purpose = Literal[
    "summarize_document",
    "prepare_email",
    "summarize_and_prepare_email",
    "morning_brief",
    "answer_question",
]


class IdentityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)


class OwnerContext(IdentityModel):
    owner_id: Reference


class ResourceVersion(IdentityModel):
    resource_id: ResourceReference
    version_ref: ResourceReference
    classification: Literal["PRIVATE_ORIGINAL", "SHAREABLE"]


class TaskScope(IdentityModel):
    purpose: Purpose
    allowed_actions: Annotated[tuple[Action, ...], Field(min_length=1, max_length=5)]
    resource_ids: Annotated[tuple[ResourceReference, ...], Field(max_length=20)] = ()
    resource_versions: Annotated[tuple[ResourceVersion, ...], Field(max_length=20)] = ()
    # A mailbox is only a ceiling; exact owner review is still required for each email.
    recipient: Annotated[str, Field(min_length=1, max_length=254)] | None = None
    approval_enabled: bool = False

    @field_validator("allowed_actions")
    @classmethod
    def unique_actions(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Actions must be unique")
        return value

    @model_validator(mode="after")
    def pinned_resources(self):
        if self.recipient is not None and (
            self.resource_ids
            or not any(action.startswith("email.") for action in self.allowed_actions)
        ):
            raise ValueError("Synthetic email scope cannot include document resources")
        ids = tuple(item.resource_id for item in self.resource_versions)
        if len(set(ids)) != len(ids) or len(set(self.resource_ids)) != len(self.resource_ids):
            raise ValueError("Resource IDs must be unique")
        if set(ids) != set(self.resource_ids):
            raise ValueError("Every resource requires exactly one pinned version")
        return self


class AuthenticatedAgentContext(IdentityModel):
    credential_ref: Reference
    task_ref: Reference
    owner_id: Reference
    credential_expires_at: AwareDatetime
    approved_scope: TaskScope


class IssuedAgentCredential(IdentityModel):
    credential_ref: Reference
    task_ref: Reference
    expires_at: datetime
    token: SecretStr = Field(repr=False, exclude=True)
