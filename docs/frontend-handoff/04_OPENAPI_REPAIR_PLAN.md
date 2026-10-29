# OpenAPI inventory and minimal repair plan

Contract: **ghost-app-v1, draft 0.1.0**. Step 44A, 2026-10-28.
**DESIGN ONLY. No existing route/schema/authentication behavior was changed.**

## 1. Inspection basis

Inspected current A routes, schemas, dependency parsers and the saved
[Step 43 OpenAPI](../integration/step43_logs/openapi.json). A fresh guarded
import with synthetic settings, private `.env` loading disabled and sockets
blocked produced an OpenAPI object **equal to the saved object**. No server was
started. FastAPI info.version=1.0.0; OpenAPI=3.1.0; 20 business method/path pairs.

The installed FastAPI represents include_router entries with lazy
_IncludedRouter wrappers. An initial inspection assuming every app.routes entry
had a path attribute failed; the corrected read-only inspector handled wrappers,
then compared generated OpenAPI. This was an inspector issue, not a runtime
backend test failure. No failed inspection is represented as a passing test.

## 2. Every existing business operation

O=owner bearer; G=task-agent bearer; Public=no auth. None of the protected
operations currently declares OpenAPI securitySchemes/security requirements;
all expose an optional authorization Header parameter. Runtime authentication
is still enforced. `MISSING` is a missing schema, not an absent runtime parser.

| Existing method / path | Runtime body | Current success schema | Required repair / audience |
| --- | --- | --- | --- |
| GET `/health` | None | HealthResponse | Public; no auth requirement; explicitly describe liveness only |
| POST `/api/consents` | ConsentRequest, documented | ConsentResponse | O; preserve legacy coercion/extra-field behavior; document actual errors |
| POST `/api/tool-permissions` | ToolPermissionRequest, documented | ToolPermissionResponse | O; preserve existing harmless tool allowlist behavior |
| POST `/api/tools/execute` | ToolExecuteRequest, documented | Generic object/additionalProperties | O; add exact LegacyToolResult wrapper; no protected handler expansion |
| GET `/api/audit-events` | None | list[AuditEventResponse] | O; describe latest100, untyped legacy detail and lack of cursor; not frontend timeline |
| POST `/api/gateway/v1/execute` | **MISSING ToolRequest** | ToolResponse | G; authorization-only profile and strict six/seven fields; private host spec |
| GET `/api/gateway/v1/operations/{request_id}` | None | OperationStatus | G; metadata-only, task-bound, private host spec |
| POST `/api/control/v1/tasks/{task_ref}/consents` | **MISSING ConsentCreate** | **MISSING** | O; add ConsentGrantResult, status201; private control spec |
| POST `/api/control/v1/tasks/{task_ref}/consents/{consent_ref}/revoke` | **MISSING EmptyObject/IdentityModel** | **MISSING** | O; add ConsentRevokeResult; private control spec |
| GET `/api/control/v1/approvals` | None; required query task_ref | **MISSING** | O; add PendingApprovalList; private owner spec |
| GET `/api/control/v1/approvals/{approval_ref}` | None | ApprovalReview | O; preserve no-store and exact private argument projection |
| POST `/api/control/v1/approvals/{approval_ref}/resolve` | **MISSING ApprovalResolution** | **MISSING** | O; add ApprovalResolutionResult; no execution |
| POST `/api/control/v1/approvals/{approval_ref}/revoke` | **MISSING EmptyObject/IdentityModel** | **MISSING** | O; add ApprovalRevokeResult including in_flight |
| POST `/api/control/v1/workflow-checkpoints` | **MISSING WorkflowPrepare** | WorkflowSnapshot | O trusted host; no cookie authentication |
| GET `/api/control/v1/workflow-checkpoints/{binding_ref}` | None | WorkflowSnapshot | O; private host identity metadata |
| POST `/api/control/v1/workflow-checkpoints/{binding_ref}/pause` | **MISSING WorkflowPause** | WorkflowSnapshot | O trusted host; attestation, not a browser checkpoint setter |
| POST `/api/control/v1/workflow-checkpoints/{binding_ref}/admit` | **MISSING WorkflowIdentity** | WorkflowSnapshot | O trusted host; fresh admission |
| POST `/api/control/v1/workflow-checkpoints/{binding_ref}/claim` | **MISSING WorkflowIdentity** | WorkflowSnapshot | O trusted host; exclusive continuation claim |
| POST `/api/control/v1/workflow-checkpoints/{binding_ref}/complete` | **MISSING WorkflowIdentity** | WorkflowSnapshot | O trusted host; metadata terminal acknowledgment |
| POST `/api/gateway/v1/operations/{request_id}/resume` | **MISSING ResumeExecution** | ControlledExecutionResult | G; disabled by default; separate v1.3 profile; never frontend dispatch |

Exactly **11 POST request bodies**, **five owner-control success schemas** and
**one generic legacy tool-result wrapper** need schema coverage. Do not describe
those as six missing response models: the legacy wrapper already has a generic
schema. Existing response defaults/nullable omission must remain wire-compatible.

## 3. Framework/documentation routes and excluded interfaces

| Existing route | Methods | OpenAPI inclusion / plan |
| --- | --- | --- |
| `/openapi.json` | GET, HEAD | Framework route, include_in_schema=false; currently public combined spec |
| `/docs` | GET, HEAD | Framework Swagger UI, excluded from business schema; currently public |
| `/docs/oauth2-redirect` | GET, HEAD | Framework Swagger helper; excluded; does not mean OAuth login is implemented |
| `/redoc` | GET, HEAD | Framework docs; excluded; currently public |

No business operation is currently intentionally excluded from the combined
schema. Internal Python dispatch_*, task/credential services, catalog helpers,
B orchestration/checkpointer and test IPC are **not routes** and must not be
converted to routes just to document them. There is no SSE/WebSocket/streaming
route to repair; older examples/demo JSONL do not establish one.

Propose separate schema audiences without changing existing protected URLs:

- Existing combined `/openapi.json` remains available to trusted development
  tooling on the private backend listener. Do not silently remove its routes.
- A new application-only schema is served to C at proposed GET
  `/api/app/v1/openapi.json` (documentation resource, not one of the 19 business
  operations); same-origin public schema in LOCAL_DEMO, no secrets or internal refs.
  It includes only app operations and optionally existing /health with Public auth.
- Private host schema includes bearer gateway/control routes and documents their
  disabled/default roles; it is a generated development artifact, not a new
  publicly reachable private-schema HTTP endpoint.
- The public edge allows only UI/static content, /api/app/v1 and /health; legacy,
  gateway/control and combined docs resources are not edge-published. Documentation
  filtering is not access control. Actual edge/auth denial tests are mandatory.

The app schema documentation resource is a **new proposal**, not a current route.
Its contract is GET with no body/query, 200 OpenAPI JSON, no session/CSRF or task
transition, safe idempotent read, no pagination; in DISABLED mode return 503
AUTH_NOT_CONFIGURED. It contains schema definitions only, never example secrets.
Publishing an application-only schema and restricting an eventual public edge are
deployment/audience decisions to review; they do not remove existing private API
contracts or establish today's network exposure.

## 4. Minimal typed repairs

Preserve the existing manually bounded parse_body implementation and errors.
Switching wholesale to ordinary Body parsing would change duplicate-JSON,
compression, byte/depth/header limits, validation details and potential input
leakage. Do not do that merely for documentation.

Generate requestBody schema metadata from the **actual Pydantic request model**
used by each dependency, referenced under application/json with required=true.
Use one small schema-generation function for component registration/collision
checking, not hand-copied JSON shapes. Include transitive models, correct $ref
resolution, strict required/nullability semantics and action/argument correlation
descriptions. Do not call private service code while generating OpenAPI.

Add these exact A response DTOs, preserving current dictionaries/status codes:

| Proposed DTO | Fields |
| --- | --- |
| ConsentGrantResult | consent_ref, state literal ACTIVE, expires_at |
| ConsentRevokeResult | state literal REVOKED, in_flight strict bool |
| PendingApprovalItem | approval_ref, operation_ref, request_id, state literal PENDING, expires_at |
| PendingApprovalList | approvals: list[PendingApprovalItem] |
| ApprovalResolutionResult | approval_ref, state existing ApprovalState, expires_at, audit_event_ref |
| ApprovalRevokeResult | ApprovalResolutionResult + in_flight |
| LegacyToolResult | result: dict[str, JsonValue]; current echo/text_stats return objects |

Do not add fields to current success bodies. response_model additions must be
checked against real serialized output, especially returned JSONResponse objects
which bypass normal FastAPI response validation. Existing model annotations alone
do not prove every emitted response matches a schema.

For auth metadata, describe two distinct HTTP bearer schemes, OwnerBearer and
TaskAgentBearer, with operation-level requirements and explicit role descriptions.
Do not let HTTPBearer's defaults replace require_bearer/agent_token behavior or
change existing 401/403 handling/duplicate-header checks. A documentation-only
SecurityBase marker or generated security metadata can leave existing parsers
untouched. New app operations use AppSession (apiKey in cookie) and, for POST,
CsrfHeader (apiKey in header), listed **together in one security requirement**
(AND, not alternative OR). Login uses the preauth cookie/CSRF; session bootstrap
is explicitly unauthenticated. Never advertise the owner scheme on app routes.

## 5. Error and parameter coverage

Existing custom GatewayError DTO: error_code, message, correlation_ref,
nullable request_id/audit_event_ref, execution_uncertain. Preserve current bodies.
Owner/legacy authentication can instead emit `{detail:string}`; default FastAPI
validation emits HTTPValidationError/detail array. Document those distinct shapes
with appropriate oneOf where actually emitted; do not standardize them by changing
legacy runtime handlers. New app endpoints alone use the new sanitized AppFailure.

| Existing route family | Status/error coverage to add |
| --- | --- |
| Legacy consents | 401/503 detail auth; 422 framework validation; 500 detail storage failure |
| Legacy tool-permissions | Same plus400 Unknown tool; no protected tool bypass |
| Legacy tools/execute | 401/503 auth, 404 unknown tool, 403 consent/permission, 422 input/argument validation (detail variants), 500/504 failure/timeout |
| Legacy audit-events | 401/503 auth, actual framework/database error behavior; do not promise a sanitized domain503 absent a handler |
| Gateway admission/status | 400 malformed/duplicate JSON where body applies; 401 AUTH_REQUIRED/AUTH_INVALID; 403 TASK_SCOPE_MISMATCH/RESULT_ACCESS_DENIED; 404 NOT_FOUND; 409 IDEMPOTENCY_CONFLICT/LOGICAL_OPERATION_EXISTS/OPERATION_IN_PROGRESS/RESUME_REQUIRED; 410 RESULT_EXPIRED; 413/415/422 parse limits; 429 CAPACITY_EXCEEDED; 503 GATEWAY_UNAVAILABLE, execution_uncertain where applicable |
| Consent/approval control | Current owner detail auth + custom parse/domain GatewayError; 404 NOT_FOUND, 409 APPROVAL_ALREADY_RESOLVED, 422 INVALID_REQUEST, 503 GATEWAY_UNAVAILABLE; actual service reason categories scoped per operation |
| Workflow control | Owner auth + parse errors; 404 NOT_FOUND; eight closed workflow409 codes from v1.2; 503 GATEWAY_UNAVAILABLE |
| Controlled execution resume | Agent auth + parse errors; 403 ACTION_DISABLED and current denial categories; 404, 409 NOT_RESUMABLE/OPERATION_IN_PROGRESS/conflicts, 410 RESULT_EXPIRED, 429 CAPACITY_EXCEEDED, 503 GATEWAY_UNAVAILABLE with conservative uncertainty |

This is a repair inventory, not a claim that every listed family member emits
every status. Step 44B must derive closed per-operation response declarations
from actual branches/tests; do not publish speculative error behavior. Existing
unhandled DB errors are generic server failures, not reliable zero-effect proof.

All current path/query references are declared plain strings. Gateway GET/resume
validate request_id through OpaqueReference at runtime; several owner references
instead reach owner-scoped lookup and generic404. Describe expected syntax without
silently adding pattern validators that change 404 to422. Keep required query
task_ref on pending approvals; do not move it into a body or invent pagination.
Document exact lowercase header names/scheme semantics, required resume_ref,
canonical checkpoint UUID, UTC dates and version defaults. Preserve existing
operationIds; name new app operations by stable A01–A19 identifiers. Metadata
changes affecting generated clients require a schema diff/review even if HTTP
serialization is unchanged.

## 6. Required compatibility checks before API freeze

1. Inventory exact method/path pairs: 20 old business operations unchanged;
   framework docs distinguished; 19 new app operations plus the new app-schema
   resource explicitly classified. No accidental public internal execution route.
2. Generate both specs with private configuration/network disabled; validate all
   references, request/response examples and union/required/null behavior using
   installed JSON Schema tools. No unresolved $ref/component name collisions.
3. Submit existing valid/invalid fixtures and compare exact old status, JSON,
   Content-Type, no-store/auth headers, role behavior and disabled capability.
   Keep strict malformed/duplicate/deep/oversized/compressed-body tests.
4. Verify every real emitted success/error payload against the declared schema,
   including JSONResponse paths and auth/framework variants. Do not leak rejected
   input in new application errors.
5. Assert owner/agent schemes on correct operations, cookie+CSRF AND semantics on
   app POSTs, and explicit public bootstrap/liveness. Auth documentation cannot
   replace runtime negative-role and cross-owner tests.
6. Preserve old ToolRequest/ToolResponse fields and serialization fixtures,
   workflow v1.2 and separate controlled v1.3 result schemas byte-for-byte where
   currently contract-tested; no terminal status accepted by the v1.1 adapter.
7. Check the application-only schema contains no bearer scheme, resume hint,
   nonce, checkpoint path, provider config, raw document result, private route or
   unimplemented stream. Public edge attempts against old private routes deny.
8. After approved implementation run A/B guarded offline suites and affected
   Ruff checks. Step 43's 640/726 results are historical baselines, not new Step
   44A execution results. A TypeScript client smoke check belongs to C's future
   environment; no package installation or client build occurred here.

No OpenAPI runtime generator, Pydantic model, route, middleware or authoritative
contract was modified during this design phase.
