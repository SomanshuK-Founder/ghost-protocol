# Ghost frontend application API contract

> Change record,2026-10-28: the original proposal below is preserved. Approved
> [A18 clarification1.0](../integration/GHOST_APP_V1_A18_CATALOG_CLARIFICATION.md)
> confirms owner-management metadata without task consent; protected content and
> execution still require the existing task/action/purpose-bound authorization.
> Implementation record, 2026-10-29: A09–A19 are implemented and checked offline in
> [Step 44D](../integration/STEP44D_APPLICATION_INTERFACES.md). The original
> proposal and historical NOT_IMPLEMENTED labels below remain unchanged.

Contract: **ghost-app-v1, draft 0.1.0**. Step 44A, 2026-10-28.
**PROPOSED — every `/api/app/v1` route below is NEW and NOT_IMPLEMENTED.**
No existing route, gateway envelope, approval contract or database schema changes
in this phase. This draft specifies the minimum local synthetic demo application.

## 1. Scope and common endpoint requirements

Public UI prefix: `/api/app/v1`; same-origin cookie authentication from
[01_AUTHENTICATION_CONTRACT.md](01_AUTHENTICATION_CONTRACT.md). The sole existing
public route reused directly is GET `/health`. All other reuse is server-side
delegation to A/B services, not exposing existing bearer routes to JavaScript.

There are **19 proposed application route/method pairs**, IDs A01–A19. No browser
route executes a protected tool. Scope is planning/authorization, exact owner
approval, metadata continuation and observation of separately operator-admitted
synthetic execution. No full document summary, live provider selection, uploads,
attachments, scheduler, memory service, SSE or general chat is implied.

Requirements inherited by **every** endpoint, with explicit auth exceptions A01–A03:

| Concern | Contract |
| --- | --- |
| Models | Pydantic v2; strict JSON-aware validation, frozen DTOs, extra=forbid, hide_input_in_errors. Nullable fields below are required and emitted as null. No private ORM object serialization |
| References | Ref: case-sensitive string `^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`; TaskRef follows existing 64-character identity type; UUID4 request idempotency keys use canonical lowercase UUID strings |
| Times/numbers | Aware UTC RFC3339 timestamps; strict integers/booleans; no string coercion, NaN or Infinity |
| Wire limits | UTF-8 JSON object, depth <=8, body <=32 KiB, headers <=8 KiB; unsupported encoding/media 415; malformed/duplicate JSON 400; size 413; schema 422; unknown query keys rejected on this NEW API |
| Reads | GET body absent; active owner session except A01; no protected execution or authority mutation; no-store, no redirects; public results bounded to 256 KiB |
| Writes | Exact Origin + X-Ghost-CSRF + active session; A02 permits preauth/current session; A03 permits preauth logout. No browser bearer/owner/role/credential/mode fields |
| Ownership | Resolve owner from server session; resolve each task/approval/operation/workflow/catalog object under that owner. App-managed tasks only, established by successful app task-create records. Unknown/foreign/out-of-scope objects ->404 NOT_FOUND |
| Success | AppSuccess[T] `{api_version:"ghost-app-v1", data:T, replayed:bool}`. GET replayed=false. Logout alone returns 204 without JSON |
| Errors | AppFailure `{api_version:"ghost-app-v1", error:AppError}`; enums below; no downstream exception, body, SQL, token, path or prompt |
| Execution boundary | No handler imports/calls `_dispatch`, `dispatch_document_read`, direct SMTP or ControlledExecutionClient.execute_completed. Planning can call authorization-only gateway; continuation can call metadata workflow service |

AppError has exactly `{code:AppCode, message:SafeMessage, correlation_ref:Ref,
command_ref:Ref|null, command_uncertain:bool, execution_uncertain:bool,
reconciliation_required:bool, reason_code:Reason|null}`. SafeMessage is a fixed
server mapping (<=160 characters), never input/exception text. Reason is a closed
existing gateway/workflow reason enum, nullable; its presence conveys no authority.

Common error set **C**, inherited by all applicable rows:

| HTTP | AppCode values / meaning |
| --- | --- |
| 400 | MALFORMED_JSON, DUPLICATE_JSON_FIELD, INVALID_CURSOR, IDEMPOTENCY_KEY_REQUIRED, IDEMPOTENCY_KEY_INVALID, UNEXPECTED_IDEMPOTENCY_KEY |
| 401 | SESSION_REQUIRED, SESSION_EXPIRED; LOGIN_FAILED only A02 |
| 403 | ORIGIN_FORBIDDEN, CSRF_INVALID, CREDENTIAL_HEADER_FORBIDDEN |
| 404 | NOT_FOUND for generic owner-scoped lookup failure |
| 409 | IDEMPOTENCY_CONFLICT, COMMAND_IN_PROGRESS, COMMAND_UNCERTAIN, TASK_NOT_ACTIVE, PLANNING_ALREADY_STARTED, APPROVAL_STATE_CONFLICT, WORKFLOW_NOT_READY, WORKFLOW_DENIED, RECONCILIATION_REQUIRED |
| 413 / 415 / 422 | PAYLOAD_TOO_LARGE / UNSUPPORTED_MEDIA_TYPE / INVALID_REQUEST |
| 429 | AUTH_RATE_LIMITED, CAPACITY_EXCEEDED; Retry-After, never automatic protected retry |
| 500 / 503 / 504 | INTERNAL_ERROR / AUTH_NOT_CONFIGURED, BACKEND_UNAVAILABLE, HOST_UNAVAILABLE / COMMAND_TIMEOUT |

Route rows restrict successful/domain outcomes; C supplies validation/security/
availability errors, not permission to return nonsensical errors on any route.
Validation errors never include submitted values. `command_uncertain=true` means
metadata/model/continuation outcome is unresolved. It does not invent a tool
effect: app planning and continuation have execution_uncertain=false. Historical
DISPATCHING/UNKNOWN projections set execution_uncertain=true and require
reconciliation. A transport error never becomes an invented gateway DENY.

## 2. Server-selected demo task profiles

| Profile ID | Immutable A scope / trusted binding | Permitted effect |
| --- | --- | --- |
| document_simulation_v1 | purpose=summarize_document; allowed_actions=(files.read,); one owner-active registered resource/version; no recipient; approval_enabled=true | Fixed simulated text only; no document opened/summarized |
| email_draft_v1 | purpose=prepare_email; allowed_actions=(email.draft,); no resources; fixed backend allowlisted demo recipient/template; approval_enabled=true | Synthetic draft metadata, no submission |
| email_send_v1 | purpose=prepare_email; allowed_actions=(email.send,); no resources; same fixed backend email profile; approval_enabled=true | Injected fake SMTP only under separately trusted operator execution |

Task TTL is fixed at **900 seconds**, within A's current 60-minute ceiling.
Credential issuance remains server-side, at planning admission, at most A's
15-minute limit and task expiry. Approval expiry remains A's 10-minute bound;
workflow admission remains <=60 seconds. No silent credential rotation, task
extension or reactivation. Inactive/missing catalog resources reject creation;
the app does not auto-register files or seed accounts. An empty catalog is valid.

The browser selects a profile and, for document simulation, a server-known
resource_id. It cannot set owner, purpose, allowed_actions, pinned versions,
expiry, recipient, body, transport, model/provider, approval_enabled or execution
mode. The owner sees the fixed synthetic email arguments in exact approval review.
Draft and send are **separate tasks/operations/approvals**; there is no document
or draft-to-send chaining in v1.0 of this application surface.

## 3. Schema dictionary

All fields listed are exact. `[]` means a bounded array, not arbitrary JSON.
Existing enums retain their meanings; new application enums never widen B's wire.

| Schema | Fields and constraints |
| --- | --- |
| EmptyObject | `{}` only |
| TaskCreate | `{profile_id:ProfileId, resource_id:Ref\|null}`; resource_id nonnull only for document profile, otherwise null |
| PlanningStart | `{user_request:string}`; trimmed 1..4000 characters, repr suppressed, synthetic-only input; no prompt persistence in ledger/checkpoint/audit |
| ApprovalDecision | `{resolution:"APPROVE"\|"REJECT"}`; no replacement arguments or TTL |
| TaskSummary | `{task_ref:TaskRef, profile_id:ProfileId, authority_state:AuthorityState, created_at:UTC, expires_at:UTC, planning_state:PlanningState, approval_ref:Ref\|null, workflow_phase:WorkflowPhase\|null, operation_state:OperationState\|null, provenance:Provenance}` |
| TaskDetail | All TaskSummary fields plus `{purpose:existing Purpose, resource_ids:Ref[0..1], allowed_action:one profile action, authorization_version:int>=0, in_flight:bool, reconciliation_required:bool}`; no prompt/credential/hint |
| PlanningView | `{task_ref:TaskRef, planning_ref:Ref\|null, state:PlanningState, outcome:existing PlanningOutcome\|null, intent:existing PlanIntent\|null, proposed_actions:existing ToolAction[0..10], authorization_decision:Decision\|null, reason_code:Reason\|null, request_id:Ref\|null, operation_ref:Ref\|null, approval_ref:Ref\|null, error_code:PlanningError\|null, started_at:UTC\|null, finished_at:UTC\|null, provenance:Provenance}` |
| ApprovalSummary | `{approval_ref:Ref, task_ref:TaskRef, operation_ref:Ref, request_id:Ref, state:ApprovalState, expires_at:UTC}` |
| ApprovalDetail | All ApprovalSummary fields plus `{action:profile action, purpose:Purpose, arguments:existing FileArguments\|EmailArguments, resource_versions:existing ResourceVersion[0..1], binding_digest:Hex64, consumed:bool, in_flight:bool, provenance:Provenance}`; exact owner review only, no-store |
| ApprovalList | `{items:ApprovalSummary[0..5]}`; pending only for required task_ref; no pagination because existing task approval bound is five |
| ApprovalMutation | `{approval:ApprovalSummary, in_flight:bool}`; reports current effective state on idempotent replay |
| WorkflowView | `{task_ref:TaskRef, binding_ref:Ref\|null, operation_ref:Ref\|null, approval_ref:Ref\|null, phase:WorkflowPhase\|null, authorization_version:int>=0, expires_at:UTC\|null, continuation_available:bool, reconciliation_required:bool, provenance:Provenance}`; null phase means no binding, not a fabricated phase |
| OperationView | `{operation_ref:Ref, task_ref:TaskRef, request_id:Ref, action:profile action, state:OperationState, decision:Decision, execution_status:ExecutionStatus, reason_code:Reason, approval_ref:Ref\|null, approval_state:ApprovalState\|null, attempt_ref:Ref\|null, audit_event_ref:Ref, revision:int>=0, created_at:UTC, updated_at:UTC, reconciliation_required:bool, provenance:Provenance}` |
| OperationList | `{items:OperationView[0..20]}`; existing 20-operation/task ceiling, ascending (created_at,operation_ref), no cursor |
| TimelineItem | `{event_ref:Ref, timestamp:UTC, kind:TimelineKind, task_ref:TaskRef, operation_ref:Ref\|null, attempt_ref:Ref\|null, approval_ref:Ref\|null, state:TimelineState\|null, decision:Decision\|null, execution_status:ExecutionStatus\|null, reason_code:Reason\|null}`; no arbitrary detail/message/body/digest |
| DocumentMetadata | `{resource_id:Ref, version_ref:Ref, display_name:string[1..120], classification:"PRIVATE_ORIGINAL"\|"SHAREABLE", resource_type:"SYNTHETIC_TEXT", synthetic:true}`; active owner-registered resources only; no filename/path/storage alias/content hash/text |
| Page[T] | `{items:T[0..limit], next_cursor:Cursor\|null, snapshot_at:UTC}`; used by tasks/documents/timeline |
| CancelResult | `{task:TaskSummary, in_flight:bool}`; cancellation does not undo already admitted effects |

Enums:

- AuthorityState = OPEN, COMPLETED, CANCELLED, EXPIRED (effective view of existing
  A task/time; planning completion never writes task COMPLETED).
- PlanningState = NOT_STARTED, RUNNING, FINISHED, FAILED, UNCERTAIN (new app
  command status; not B TaskStatus). A finished valid plan can still await approval.
- WorkflowPhase = PREPARING, PAUSED, ADMITTED, RESUMING, RESUMED, DENIED.
- OperationState = ADMITTED, PENDING_APPROVAL, READY, DENIED, DISPATCHING,
  SUCCEEDED, FAILED, UNKNOWN. DISPATCHING projects execution_status=UNKNOWN.
- ApprovalState = PENDING, APPROVED, REJECTED, EXPIRED, REVOKED.
- Decision = ALLOW, DENY, APPROVAL_REQUIRED; ExecutionStatus = NOT_EXECUTED,
  SUCCEEDED, FAILED, UNKNOWN.
- PlanningError = PLANNING_FAILED, PLAN_OUT_OF_SCOPE, AUTHORIZATION_UNAVAILABLE,
  CHECKPOINT_UNAVAILABLE, HOST_UNAVAILABLE, COMMAND_TIMEOUT, COMMAND_UNCERTAIN.
  Existing underlying sanitized codes are mapped, not displayed as raw exceptions.
- TimelineKind = AUTHORIZATION, APPROVAL_TRANSITION, APPROVAL_VIEWED,
  WORKFLOW_TRANSITION, EXECUTION_ADMISSION, EXECUTION_OUTCOME.
  Only genuinely persisted, task-correlated allowlisted source events qualify;
  omit an uncorrelated catalog event rather than invent task membership.
- TimelineState is the closed union of ApprovalState, WorkflowPhase and
  OperationState. Validate kind/state correlation: approval kinds use approval
  states, workflow kind uses workflow phases, execution kinds use operation
  states; authorization may use an observed operation state or null. It is not
  arbitrary legacy audit outcome text.

Reason is the closed v1.1 denial set from B AUTHORIZATION_DENIAL_CODES, the five
non-denial codes EXECUTION_NOT_STARTED, EXECUTION_SUCCEEDED, TOOL_FAILED_NO_EFFECT,
EXECUTION_UNCONFIRMED, CONSENT_REVIEW_REQUIRED, and the eight workflow409 codes
listed in gateway v1.2. AUTH_INVALID/TASK_SCOPE_MISMATCH are transport failures,
not invented 200 policy decisions. Unknown legacy values are not passed through.

Provenance is exactly `{environment:"OFFLINE_DEMO", planning_source:"NOT_RUN"|
"MOCK_MODEL"|"UNATTESTED", execution_mode:null|"SIMULATED"|"EMAIL_DRAFT"|
"MAILPIT_SEND", effect:"NONE"|"SIMULATED"|"NO_MESSAGE_SUBMISSION"|
"FAKE_SMTP_ONLY"|"UNCONFIRMED", evidence:"CONFIGURED"|"OBSERVED"|"UNATTESTED"}`.
Null mode/NONE means no admitted execution. Configured profile is not an observed
effect. OBSERVED requires correlated committed A state plus trusted host evidence
of the configured simulator/fake transport; mode MAILPIT_SEND alone cannot prove
fake versus real transport. Missing/contradictory provenance is UNATTESTED and
UNCONFIRMED, never relabelled successful delivery. No live provenance is selectable
in this version. Details in [05](05_FRONTEND_SECURITY_BOUNDARIES.md).

## 4. New endpoint inventory and delegation

Every A04–A19 endpoint uses an active **owner session**, never browser bearer
authentication. Every POST inherits CSRF/Origin and command admission below.
All rows inherit common C errors and the exact schema dictionary. Existing domain
failures are mapped to AppCode with a closed optional reason_code, without
altering the old backend routes' status or body.

| ID / method / URL | Request -> success response | Authorization and backend delegation | Domain errors | Idempotency / pagination | Transition / provenance |
| --- | --- | --- | --- | --- | --- |
| A01 GET `/api/app/v1/session` | None ->200 SessionView | Preauth/session inspection; auth contract | Auth contract | Safe; none | No task transition; LOCAL_DEMO |
| A02 POST `/api/app/v1/session/login` | LoginRequest ->200 SessionView | Preauth pairing only | Auth contract | One-use, no key/page | Anonymous -> owner session; no task effect |
| A03 POST `/api/app/v1/session/logout` | EmptyObject ->204 | Own current session/preauth | Auth contract | No key/page | Session invalidated; no task effect |
| A04 POST `/api/app/v1/tasks` | TaskCreate ->201 TaskDetail | Session owner; catalog lookup_resource; create_trusted_task validation; new atomic app-create adapter | 404 NOT_FOUND; 429 CAPACITY_EXCEEDED | Required key; replay returns200 same task, current projection; no page | Create OPEN only; CONFIGURED provenance, no grant/execution |
| A05 GET `/api/app/v1/tasks` | limit/cursor ->200 Page[TaskSummary] | New owner-filtered query joined to successful app task-create records | 400 INVALID_CURSOR | Safe; page policy | Read effective state; stored/attested provenance only |
| A06 GET `/api/app/v1/tasks/{task_ref}` | None ->200 TaskDetail | Owned app task; new safe projection of GatewayTask/command/workflow/operation | 404 NOT_FOUND | Safe; none | Read, no task completion mutation |
| A07 POST `/api/app/v1/tasks/{task_ref}/planning` | PlanningStart ->200 PlanningView | Owned active task; server credential issuance; supervised B gateway_runtime + GatewayOrchestrator once; automatic metadata pause on genuine pending approval | 409 TASK_NOT_ACTIVE/PLANNING_ALREADY_STARTED/COMMAND_IN_PROGRESS/COMMAND_UNCERTAIN; 503 HOST_UNAVAILABLE; 504 COMMAND_TIMEOUT | Required key; at most one planning command/task ever; no page | NOT_STARTED ->RUNNING ->FINISHED/FAILED/UNCERTAIN; MOCK_MODEL, authorization-only, zero effects |
| A08 GET `/api/app/v1/tasks/{task_ref}/planning` | None ->200 PlanningView | Owned task; retained safe command/model outcome + authoritative current refs; no model call | 404 NOT_FOUND | Safe; none | NOT_STARTED with null ref if absent; no retry/replan |
| A09 GET `/api/app/v1/approvals` | Required task_ref query ->200 ApprovalList | Owned task; reuse list_pending/reconciliation; no global approval search | 404 NOT_FOUND | Safe; bounded five, no cursor | Pending owner review only; no effect |
| A10 GET `/api/app/v1/approvals/{approval_ref}` | None ->200 ApprovalDetail | Existing owner_approval review and app-task membership; exact original arguments | 404 NOT_FOUND | Safe; none | May reconcile expiry/audit a view; never approve; configured/observed provenance |
| A11 POST `/api/app/v1/approvals/{approval_ref}/decision` | ApprovalDecision ->200 ApprovalMutation | Existing owner_approval resolution after app ownership; exact immutable operation, fresh authority | 409 APPROVAL_STATE_CONFLICT/TASK_NOT_ACTIVE/RECONCILIATION_REQUIRED | Required key; same command reads current state; existing exact decision idempotence preserved | PENDING ->APPROVED/REJECTED; no resume/execution |
| A12 POST `/api/app/v1/approvals/{approval_ref}/revoke` | EmptyObject ->200 ApprovalMutation | Existing owner_approval revoke; owned app approval | 409 APPROVAL_STATE_CONFLICT | Required key; repeated recorded revoke safe | PENDING/APPROVED ->REVOKED; in_flight truthful |
| A13 GET `/api/app/v1/tasks/{task_ref}/workflow` | None ->200 WorkflowView | Owned task; discover unique WorkflowCheckpoint then workflow_checkpoint(get); strip private host fields | 404 NOT_FOUND | Safe; none | Null binding when absent; no admission |
| A14 POST `/api/app/v1/tasks/{task_ref}/workflow/continue` | EmptyObject ->200 WorkflowView | Owned active task; server discovers binding; private B DurableApprovalWorkflow.resume uses existing admit/claim/complete | 409 WORKFLOW_NOT_READY/WORKFLOW_DENIED/RECONCILIATION_REQUIRED/COMMAND_UNCERTAIN; 503 HOST_UNAVAILABLE; 504 COMMAND_TIMEOUT | Required key; one app continuation claim per binding; no page | PAUSED/ADMITTED ->RESUMING ->RESUMED or DENIED; **metadata-only**, no executor call |
| A15 GET `/api/app/v1/tasks/{task_ref}/operations` | None ->200 OperationList | New A owner-only history projection; owned task then owner/task-filtered ledger/attempt/approval records | 404 NOT_FOUND | Safe; bounded20, no cursor | Read history only; no result regeneration |
| A16 GET `/api/app/v1/tasks/{task_ref}/operations/{operation_ref}` | None ->200 OperationView | New owner projection; exact operation/task/owner relation; existing history validation reused | 404 NOT_FOUND | Safe; none | Read history; UNKNOWN requires reconciliation |
| A17 GET `/api/app/v1/tasks/{task_ref}/timeline` | limit/cursor ->200 Page[TimelineItem] | New A allowlisted audit projection; owner+task binding verified, ordered by real audit IDs | 400 INVALID_CURSOR; 404 NOT_FOUND | Safe; page policy | Read genuine events; no fabricated SSE/progress |
| A18 GET `/api/app/v1/documents` | limit/cursor ->200 Page[DocumentMetadata] | New owner catalog metadata query; registered active SYNTHETIC_TEXT only; reuse lookup validation semantics | 400 INVALID_CURSOR | Safe; page policy | Management metadata only, no files.read/registration |
| A19 POST `/api/app/v1/tasks/{task_ref}/cancel` | EmptyObject ->200 CancelResult | Existing revoke_trusted_task after owned app-task lookup; invalidate grants/credentials/pending approvals | 409 COMMAND_UNCERTAIN if outcome cannot be established | Required key; cancellation repeated safely; no page | OPEN ->CANCELLED; expired task can be revoked without reactivation; existing effects retained |

GET /health remains existing, public, HealthResponse, 200, no idempotency/page/
lifecycle transition. It is liveness only. The table deliberately includes no
credential issuance, direct consent grant, execution, generic tool or SMTP route.

## 5. Idempotency and persistence requirements (NEW implementation work)

A04/A07/A11/A12/A14/A19 require `Idempotency-Key: <canonical UUID4>`.
Key scope is owner + HTTP method + full canonical target path + key. Bind a
SHA-256 canonical request digest (including profile/target/body) and reserve
admission under a DB uniqueness constraint. A different payload for the same
scope/key returns 409 IDEMPOTENCY_CONFLICT, before delegation. Concurrent admitted
duplicates return 409 COMMAND_IN_PROGRESS; finished identical commands return
current safe projections with replayed=true, never invoke B/service effects again.
Authentication, CSRF and owner lookup precede replay disclosure. Mutable approval/
task/workflow state may differ from the original response; stale approval success
must not be replayed as current authority.

Propose one additive A-owned `application_commands` table, **not present today**:
command_ref, owner_id, canonical target scope digest, client_key, request_digest,
kind, nullable task/target refs, state CLAIMED/SUCCEEDED/FAILED/UNCERTAIN, timestamps,
bounded typed safe_result metadata, and nullable failure_code/failure_http_status.
Unique(owner,scope_digest,client_key),
unique nullable planning_task_ref, and unique nullable continuation_binding_ref
enforce one planning/continuation admission even with new browser keys. MySQL
uses nullable unique columns, not unsupported partial-index assumptions. Refs
must match owner/task relationships; state checks and FK design require migration
review. Keep identity tombstones at least task expiry+30 days and while unresolved.
No prompt, pairing code, cookie, bearer, resume hint, email body or raw result.

Command SUCCEEDED means a validated response was recorded, not model success,
approval or tool success. A validated failed plan can therefore have command
SUCCEEDED and PlanningView.state=FAILED. A definitive failed command records its
closed AppCode/HTTP failure and exact replay returns that sanitized failure;
UNCERTAIN replay returns 409 COMMAND_UNCERTAIN. Neither state can be readmitted.
Successful replay uses original identity and a fresh safe projection as above.

Sessions/cursors remain in memory; authoritative app command identity and safe
planning metadata require this additive persistence. Do not hide application
state in existing audit JSON, task ceilings, approval fields or B checkpoints.
Task profiles are retained as typed task-create result metadata, not an editable
authorization field. List only tasks linked to successful application creation.

Atomic task creation and command association require extracting A's existing
task validation/write unit for reuse inside one transaction, preserving the old
create_trusted_task signature/behavior. Its current self-owned transaction cannot
simply be nested. Approval/revoke/cancel wrapper command results should commit
with their domain transition where feasible using the same reviewed unit-of-work
pattern. Otherwise retain CLAIMED/UNCERTAIN and reconcile from original target
history; never resubmit blindly after a crash. No migration/refactor is performed
by this draft. If Step 44B excludes this persistence, it must remain read-only;
an in-memory dedupe cache is not the safe alternative for mutation endpoints.

For B calls: commit command claim before invoking the host; claim contains no
plaintext prompt. There is no cross-process/cross-store atomic transaction.
After confirmed success persist only safe result/ref metadata. Loss after claim
becomes UNCERTAIN on host loss/restart; do not rerun model, gateway submission or
continuation. Existing A history can aid explicit reconciliation; no reconciliation
HTTP endpoint is proposed. Missing original proposal/credential after restart
does not permit regeneration or automatic token rotation.

## 6. Pagination and bounded polling

Only task list, document list and timeline accept `limit` (strict integer 1..50,
default20) and `cursor` (opaque string <=2048). Other rows explicitly have no
pagination; unexpected cursor/filter parameters reject 422. Pending approval list
requires one task_ref and is bounded by A's five-approval ceiling; operation list
by A's 20-operation ceiling. Do not silently truncate either beyond those invariants.

Use keyset pagination: tasks `(created_at,task_ref)` descending, documents
`resource_ref` ascending, timeline audit ID ascending. Cursors bind owner, endpoint,
task/filter, snapshot high-water key, last key, limit and expiry (900 seconds),
authenticated with an ephemeral server HMAC key. Reject tampering, scope/limit
changes, expiry and restart-invalidated signatures with 400 INVALID_CURSOR.
Authorize again; a cursor is never a grant. Snapshot bounds new insertions, not
mutable state changes or deletion; list metadata is observational, not an
immutable DB snapshot. No count totals or arbitrary query/sort language.

Poll status/detail endpoints at >=2 seconds with one request per view in flight;
stop background polling on401, logout, unmounted view or terminal/reconciliation
state. On409 inspect status; never automatically repeat POST. There is no SSE,
WebSocket, server push or stream retry protocol in this draft.

## 7. Compatibility and implementation boundary

Old /api/control/v1, /api/gateway/v1 and legacy /api routes keep existing auth,
bodies/status codes and regression behavior. These new application DTOs are
projections, not replacements for ToolRequest/ToolResponse/WorkflowSnapshot.
Operation history is owner metadata access through a new service, not owner-token
substitution on an agent route. Actual document text and execution hints never
enter the app schema.

The new table, session adapter, typed projections, private host composition and
metadata/OpenAPI changes need explicit Step 44B approval. See
[03](03_TASK_AND_WORKFLOW_LIFECYCLE.md), [04](04_OPENAPI_REPAIR_PLAN.md),
[05](05_FRONTEND_SECURITY_BOUNDARIES.md) and the
[compatibility review](../integration/STEP44A_CONTRACT_COMPATIBILITY.md).
