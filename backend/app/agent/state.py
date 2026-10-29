"""Provisional task state data, without graph execution or transitions."""

from enum import StrEnum

from pydantic import Field

from app.agent.gateway_protocol import ContractModel, OpaqueReference


class TaskStatus(StrEnum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AgentTaskState(ContractModel):
    task_ref: OpaqueReference
    skill_id: OpaqueReference
    status: TaskStatus = TaskStatus.CREATED
    pending_request_ref: OpaqueReference | None = None
    approval_ref: OpaqueReference | None = None
    retry_count: int = Field(default=0, strict=True, ge=0)
    last_error: OpaqueReference | None = None  # Sanitized code, never private error text.
