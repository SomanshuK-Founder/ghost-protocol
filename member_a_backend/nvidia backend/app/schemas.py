from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConsentRequest(BaseModel):
    scope: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9:_-]*$")
    granted: bool


class ToolPermissionRequest(BaseModel):
    tool_name: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    allowed: bool


class ToolExecuteRequest(BaseModel):
    tool_name: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    arguments: dict = Field(default_factory=dict)


class ConsentResponse(BaseModel):
    id: int
    scope: str
    granted: bool
    model_config = ConfigDict(from_attributes=True)


class ToolPermissionResponse(BaseModel):
    tool_name: str
    allowed: bool


class AuditEventResponse(BaseModel):
    event_type: str
    outcome: str
    detail: dict
    created_at: datetime


class HealthResponse(BaseModel):
    status: str
    database: str | None = None

    model_config = ConfigDict(exclude_none=True)
