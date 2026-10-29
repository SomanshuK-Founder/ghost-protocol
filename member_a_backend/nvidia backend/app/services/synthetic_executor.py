"""Trusted internal execution types; no agent-selected implementation or credentials."""

from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from typing import Literal, Protocol

from app.gateway_contracts import (
    DocumentFileResult,
    EmailArguments,
    EmailDraftResult,
    EmailSendResult,
    FileArguments,
    SimulatedFileResult,
    ToolResponse,
)


@dataclass(frozen=True)
class ExecutionContext:
    attempt_ref: str
    admitted_at: datetime
    mode: Literal["SIMULATED", "SYNTHETIC_READ", "EMAIL_DRAFT", "MAILPIT_SEND"] = "SIMULATED"


@dataclass(frozen=True)
class DocumentBinding:
    resource_ref: str
    owner_ref: str
    storage_reference: str = field(repr=False)
    content_digest: str = field(repr=False)
    classification: Literal["PRIVATE_ORIGINAL", "SHAREABLE"]


@dataclass(frozen=True)
class ExecutionInput:
    operation_ref: str
    task_ref: str
    request_id: str
    idempotency_key: str
    canonical_request_digest: str
    action: Literal["files.read", "email.draft", "email.send"]
    arguments: FileArguments | EmailArguments = field(repr=False)
    version_ref: str
    context: ExecutionContext
    document: DocumentBinding | None = None
    email_owner: str | None = None


@dataclass(frozen=True)
class ExecutionOutcome:
    status: Literal["SUCCEEDED", "FAILED", "UNKNOWN"]
    result: SimulatedFileResult | DocumentFileResult | EmailDraftResult | EmailSendResult | None = (
        field(default=None, repr=False)
    )
    sanitized_error_code: str | None = None


SyntheticOutcome = ExecutionOutcome


class Executor(Protocol):
    def execute(self, request: ExecutionInput) -> ExecutionOutcome: ...


@dataclass(frozen=True)
class ExecutionReport:
    operation_ref: str
    attempt_ref: str
    response: ToolResponse
    sanitized_error_code: str | None = None
    mode: Literal["SIMULATED", "SYNTHETIC_READ", "EMAIL_DRAFT", "MAILPIT_SEND"] = "SIMULATED"
    untrusted_document: bool = False
    controlled_replay: bool = False


SimulationReport = ExecutionReport


class SyntheticExecutor:
    """Selection/outcome is trusted dependency injection, never an agent argument."""

    def __init__(self, outcome: Literal["SUCCEEDED", "FAILED", "UNKNOWN"] = "SUCCEEDED"):
        if outcome not in ("SUCCEEDED", "FAILED", "UNKNOWN"):
            raise ValueError("Unsupported simulation outcome")
        self._outcome = outcome
        self._calls = 0
        self._lock = Lock()

    @property
    def calls(self) -> int:
        with self._lock:
            return self._calls

    def execute(self, request: ExecutionInput) -> SyntheticOutcome:
        if (
            not isinstance(request, ExecutionInput)
            or request.action != "files.read"
            or request.context.mode != "SIMULATED"
        ):
            raise ValueError("Unsupported synthetic action")
        with self._lock:
            self._calls = min(self._calls + 1, 1_000_000)
        result = (
            SimulatedFileResult(
                resource_id=request.arguments.resource_id, version_ref=request.version_ref
            )
            if self._outcome == "SUCCEEDED"
            else None
        )
        return SyntheticOutcome(self._outcome, result)
