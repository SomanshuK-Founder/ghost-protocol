"""Exact ghost-app-v1 task/planning projections; no operational secrets or raw results."""

from typing import Annotated, Generic, Literal, TypeVar

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from app.agent_schemas import Action, IdentityModel, Purpose, Reference, ResourceVersion
from app.browser_auth import AuthCode, BrowserResponse
from app.gateway_contracts import Authorization, EmailArguments, FileArguments, OpaqueReference

AuthorizationDecision = Authorization.model_fields["decision"].annotation
AuthorizationReason = Authorization.model_fields["reason_code"].annotation

ProfileId = Literal["document_simulation_v1", "email_draft_v1", "email_send_v1"]
PlanningState = Literal["NOT_STARTED", "RUNNING", "FINISHED", "FAILED", "UNCERTAIN"]
PlanningError = Literal[
    "PLANNING_FAILED",
    "PLAN_OUT_OF_SCOPE",
    "AUTHORIZATION_UNAVAILABLE",
    "CHECKPOINT_UNAVAILABLE",
    "HOST_UNAVAILABLE",
    "COMMAND_TIMEOUT",
    "COMMAND_UNCERTAIN",
]
AppCode = (
    AuthCode
    | Literal[
        "INVALID_CURSOR",
        "IDEMPOTENCY_KEY_REQUIRED",
        "IDEMPOTENCY_KEY_INVALID",
        "IDEMPOTENCY_CONFLICT",
        "COMMAND_IN_PROGRESS",
        "COMMAND_UNCERTAIN",
        "TASK_NOT_ACTIVE",
        "PLANNING_ALREADY_STARTED",
        "CAPACITY_EXCEEDED",
        "INTERNAL_ERROR",
        "BACKEND_UNAVAILABLE",
        "HOST_UNAVAILABLE",
        "COMMAND_TIMEOUT",
        "APPROVAL_STATE_CONFLICT",
        "WORKFLOW_NOT_READY",
        "WORKFLOW_DENIED",
        "RECONCILIATION_REQUIRED",
    ]
)
Outcome = Literal["PLAN_READY", "CLARIFICATION_REQUIRED", "UNSUPPORTED_OPERATION", "FAILED"]
Intent = Purpose | Literal["clarify_request", "unsupported_operation"]
OperationState = Literal[
    "ADMITTED",
    "PENDING_APPROVAL",
    "READY",
    "DENIED",
    "DISPATCHING",
    "SUCCEEDED",
    "FAILED",
    "UNKNOWN",
]
WorkflowPhase = Literal["PREPARING", "PAUSED", "ADMITTED", "RESUMING", "RESUMED", "DENIED"]


class Provenance(BrowserResponse):
    environment: Literal["OFFLINE_DEMO"] = "OFFLINE_DEMO"
    planning_source: Literal["NOT_RUN", "MOCK_MODEL", "UNATTESTED"] = "NOT_RUN"
    execution_mode: Literal["SIMULATED", "EMAIL_DRAFT", "MAILPIT_SEND"] | None = None
    effect: Literal[
        "NONE", "SIMULATED", "NO_MESSAGE_SUBMISSION", "FAKE_SMTP_ONLY", "UNCONFIRMED"
    ] = "NONE"
    evidence: Literal["CONFIGURED", "OBSERVED", "UNATTESTED"] = "CONFIGURED"


class TaskCreate(IdentityModel):
    profile_id: ProfileId
    resource_id: OpaqueReference | None

    @model_validator(mode="after")
    def resource_profile(self):
        if (self.profile_id == "document_simulation_v1") != (self.resource_id is not None):
            raise ValueError("Resource does not match profile")
        return self


class PlanningStart(IdentityModel):
    user_request: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
        Field(repr=False),
    ]


class PlanningView(BrowserResponse):
    task_ref: Reference
    planning_ref: OpaqueReference | None = None
    state: PlanningState = "NOT_STARTED"
    outcome: Outcome | None = None
    intent: Intent | None = None
    proposed_actions: tuple[Action, ...] = Field(default=(), max_length=10)
    authorization_decision: Literal["ALLOW", "DENY", "APPROVAL_REQUIRED"] | None = None
    reason_code: AuthorizationReason | None = None
    request_id: OpaqueReference | None = None
    operation_ref: OpaqueReference | None = None
    approval_ref: OpaqueReference | None = None
    error_code: PlanningError | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    provenance: Provenance = Field(default_factory=Provenance)


class TaskSummary(BrowserResponse):
    task_ref: Reference
    profile_id: ProfileId
    authority_state: Literal["OPEN", "COMPLETED", "CANCELLED", "EXPIRED"]
    created_at: AwareDatetime
    expires_at: AwareDatetime
    planning_state: PlanningState
    approval_ref: OpaqueReference | None
    workflow_phase: WorkflowPhase | None
    operation_state: OperationState | None
    provenance: Provenance


class TaskDetail(TaskSummary):
    purpose: Purpose
    resource_ids: tuple[OpaqueReference, ...] = Field(max_length=1)
    allowed_action: Action
    authorization_version: int = Field(ge=0)
    in_flight: bool
    reconciliation_required: bool


T = TypeVar("T")


class AppSuccess(BrowserResponse, Generic[T]):
    api_version: Literal["ghost-app-v1"] = "ghost-app-v1"
    data: T
    replayed: bool = False


class TaskPage(BrowserResponse):
    items: tuple[TaskSummary, ...] = Field(max_length=50)
    next_cursor: str | None
    snapshot_at: AwareDatetime


class AppErrorDetail(BrowserResponse):
    code: AppCode
    message: Literal["Request cannot be processed"] = "Request cannot be processed"
    correlation_ref: OpaqueReference
    command_ref: OpaqueReference | None = None
    command_uncertain: bool = False
    execution_uncertain: bool = False
    reconciliation_required: bool = False
    reason_code: None = None


class AppFailure(BrowserResponse):
    api_version: Literal["ghost-app-v1"] = "ghost-app-v1"
    error: AppErrorDetail


ApprovalState = Literal["PENDING", "APPROVED", "REJECTED", "EXPIRED", "REVOKED"]


class ApprovalDecision(IdentityModel):
    resolution: Literal["APPROVE", "REJECT"]


class ApprovalSummary(BrowserResponse):
    approval_ref: OpaqueReference
    task_ref: Reference
    operation_ref: OpaqueReference
    request_id: OpaqueReference
    state: ApprovalState
    expires_at: AwareDatetime


class ApprovalDetail(ApprovalSummary):
    action: Action
    purpose: Purpose
    arguments: FileArguments | EmailArguments
    resource_versions: tuple[ResourceVersion, ...] = Field(max_length=1)
    binding_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    consumed: bool
    in_flight: bool
    provenance: Provenance


class ApprovalList(BrowserResponse):
    items: tuple[ApprovalSummary, ...] = Field(max_length=5)


class ApprovalMutation(BrowserResponse):
    approval: ApprovalSummary
    in_flight: bool


class WorkflowView(BrowserResponse):
    task_ref: Reference
    binding_ref: OpaqueReference | None
    operation_ref: OpaqueReference | None
    approval_ref: OpaqueReference | None
    phase: WorkflowPhase | None
    authorization_version: int = Field(ge=0)
    expires_at: AwareDatetime | None
    continuation_available: bool
    reconciliation_required: bool
    provenance: Provenance


class OperationView(BrowserResponse):
    operation_ref: OpaqueReference
    task_ref: Reference
    request_id: OpaqueReference
    action: Action
    state: OperationState
    decision: AuthorizationDecision
    execution_status: Literal["NOT_EXECUTED", "SUCCEEDED", "FAILED", "UNKNOWN"]
    reason_code: AuthorizationReason
    approval_ref: OpaqueReference | None
    approval_state: ApprovalState | None
    attempt_ref: OpaqueReference | None
    audit_event_ref: OpaqueReference
    revision: int = Field(ge=0)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    reconciliation_required: bool
    provenance: Provenance


class OperationList(BrowserResponse):
    items: tuple[OperationView, ...] = Field(max_length=20)


class TimelineItem(BrowserResponse):
    event_ref: OpaqueReference
    timestamp: AwareDatetime
    kind: Literal[
        "AUTHORIZATION",
        "APPROVAL_TRANSITION",
        "APPROVAL_VIEWED",
        "WORKFLOW_TRANSITION",
        "EXECUTION_ADMISSION",
        "EXECUTION_OUTCOME",
    ]
    task_ref: Reference
    operation_ref: OpaqueReference | None
    attempt_ref: OpaqueReference | None
    approval_ref: OpaqueReference | None
    state: ApprovalState | WorkflowPhase | OperationState | None
    decision: AuthorizationDecision | None
    execution_status: Literal["NOT_EXECUTED", "SUCCEEDED", "FAILED", "UNKNOWN"] | None
    reason_code: AuthorizationReason | None


class DocumentMetadata(BrowserResponse):
    resource_id: OpaqueReference
    version_ref: OpaqueReference
    display_name: str = Field(min_length=1, max_length=120)
    classification: Literal["PRIVATE_ORIGINAL", "SHAREABLE"]
    resource_type: Literal["SYNTHETIC_TEXT"] = "SYNTHETIC_TEXT"
    synthetic: Literal[True] = True


class AppPage(BrowserResponse, Generic[T]):
    items: tuple[T, ...] = Field(max_length=50)
    next_cursor: str | None
    snapshot_at: AwareDatetime


class CancelResult(BrowserResponse):
    task: TaskSummary
    in_flight: bool


class ApplicationError(Exception):
    def __init__(
        self, status, code, *, command_ref=None, uncertain=False, execution_uncertain=False
    ):
        self.status, self.code = status, code
        self.command_ref, self.uncertain = command_ref, uncertain
        self.execution_uncertain = execution_uncertain
        super().__init__(code)
