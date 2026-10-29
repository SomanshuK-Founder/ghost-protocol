"""v1.2 metadata contracts; credentials/payloads are deliberately not fields."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.agent.gateway_protocol import ContractModel, OpaqueReference


class WorkflowSnapshot(ContractModel):
    binding_ref: OpaqueReference
    owner_ref: OpaqueReference
    task_ref: OpaqueReference
    operation_ref: OpaqueReference
    approval_ref: OpaqueReference
    request_id: OpaqueReference
    idempotency_key: OpaqueReference
    canonical_request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    thread_id: OpaqueReference
    checkpoint_id: OpaqueReference | None
    workflow_version: Literal["approval-workflow-v1"]
    registration_authorization_version: int = Field(ge=0)
    authorization_version: int = Field(ge=0)
    admitted_authorization_version: int | None
    phase: Literal["PREPARING", "PAUSED", "ADMITTED", "RESUMING", "RESUMED", "DENIED"]
    expires_at: AwareDatetime | None
    audit_event_ref: OpaqueReference

    @model_validator(mode="after")
    def phase_binding(self):
        if self.checkpoint_id is not None and str(UUID(self.checkpoint_id)) != self.checkpoint_id:
            raise ValueError("Invalid checkpoint identity")
        if self.phase != "PREPARING" and self.checkpoint_id is None:
            raise ValueError("Missing checkpoint identity")
        if self.phase in ("ADMITTED", "RESUMING", "RESUMED") and (
            self.admitted_authorization_version is None or self.expires_at is None
        ):
            raise ValueError("Missing admission identity")
        return self


def resume_identity(snapshot):
    return {
        key: getattr(snapshot, key)
        for key in (
            "task_ref",
            "operation_ref",
            "approval_ref",
            "request_id",
            "idempotency_key",
            "thread_id",
            "checkpoint_id",
            "workflow_version",
        )
    } | {"expected_authorization_version": snapshot.authorization_version}


class WorkflowError(Exception):
    def __init__(self, code="WORKFLOW_UNAVAILABLE"):
        super().__init__("Workflow could not be continued safely")
        self.code = code
