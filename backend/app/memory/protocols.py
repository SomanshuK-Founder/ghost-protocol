"""Explicit preference records and candidate changes; no consent authority or storage."""

from enum import StrEnum
from typing import Protocol, Self

from pydantic import AwareDatetime, JsonValue, model_validator

from app.agent.gateway_protocol import BoundedText, ContractModel, OpaqueReference


class MemoryStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    DELETED = "DELETED"


class MemoryRecord(ContractModel):
    memory_ref: OpaqueReference
    category: BoundedText
    value: JsonValue
    source_ref: OpaqueReference
    created_at: AwareDatetime
    updated_at: AwareDatetime
    status: MemoryStatus
    supersedes_ref: OpaqueReference | None = None

    @model_validator(mode="after")
    def validate_history(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("Memory update timestamp must not precede creation")
        if self.supersedes_ref == self.memory_ref:
            raise ValueError("Memory cannot supersede itself")
        return self


class MemoryProposal(ContractModel):
    """Uncommitted candidate; acceptance belongs to trusted persistence/user flow."""

    task_ref: OpaqueReference
    category: BoundedText
    value: JsonValue
    source_ref: OpaqueReference
    supersedes_ref: OpaqueReference | None = None


class MemoryRepository(Protocol):
    """Adapters must authorize scoped retrieval and keep proposals non-authoritative.

    Corrections are candidates with supersedes_ref; the approved trusted service
    must atomically accept/correct/supersede records. No storage adapter in B0.
    """

    async def get_for_task(self, task_ref: str) -> tuple[MemoryRecord, ...]: ...

    async def propose_update(self, proposal: MemoryProposal) -> MemoryProposal: ...
