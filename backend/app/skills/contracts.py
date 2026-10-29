"""Versioned skill metadata, without a registry or executor."""

from typing import Annotated

from pydantic import Field, StringConstraints

from app.agent.gateway_protocol import BoundedText, ContractModel, OpaqueReference, ToolAction


class SkillDefinition(ContractModel):
    skill_id: OpaqueReference
    name: BoundedText
    description: BoundedText
    version: Annotated[str, StringConstraints(strict=True, pattern=r"^\d+\.\d+\.\d+$")]
    required_actions: tuple[ToolAction, ...] = Field(max_length=5)
