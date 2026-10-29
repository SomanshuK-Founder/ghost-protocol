# Verified API inventory — Step 44E

Date: 2026-10-29. Source: the actual FastAPI application and its registered route contexts.
Historical Step 43/44A contracts remain unchanged; this is the current implementation overlay.

## Counts and audiences

| Audience | Registered entries / method-path pairs | Machine-readable audience |
| --- | --- | --- |
| A: public liveness | 1 / 1 | Combined and frontend schemas |
| B: browser business API | 19 / 19 | Combined and frontend schemas |
| C: trusted owner/agent API | 19 / 19 (16 owner, 3 task-agent) | Private combined schema only |
| D: framework development documentation | 4 / 8 (GET and HEAD) | Registered, excluded from business schemas and public listener |
| D: browser schema resource | 1 / 1 | Registered GET /api/app/v1/openapi.json; excluded from its own schema |
| Total | **44 entries / 48 method-path pairs** | **39 combined / 20 frontend operations** |

E is the exclusion view: all 19 trusted operations and all five documentation resources
are absent from frontend OpenAPI. The documentation resource remains publicly readable only
under the configured loopback Origin/Host policy; default DISABLED returns 503.
There are no duplicate method/path registrations or conflicting operation IDs.
Step 43 had 20 business operations; Steps 44B–44D added 19. Step 44E adds one
documentation resource, not a twentieth browser business operation. Distinct methods
sharing a path (for example task GET/POST) are intentional.

The browser listener is `app.main:public_app`; the explicit `python -m app.local_demo`
launcher now serves this audience. `app.main:app` remains the trusted private backend.
ASGI tests deny every internal/development route at the public audience even with valid
owner and task-agent credentials. Schema filtering alone is not the access control.
No real listener, proxy, TLS service or deployment was started or qualified.

## Business operation inventory

The ID column preserves approved A01–A19 identifiers; existing generated operationIds
also remain unchanged. Full operationIds, field types, enums, required/optional/null
rules and errors are in the generated artifacts. POST bodies are required JSON.

| ID/audience | Method | Exact path | Request component | Success status / component |
| --- | --- | --- | --- | --- |
| A09 | GET | `/api/app/v1/approvals` | None | 200 AppSuccess_ApprovalList_ |
| A10 | GET | `/api/app/v1/approvals/{approval_ref}` | None | 200 AppSuccess_ApprovalDetail_ |
| A11 | POST | `/api/app/v1/approvals/{approval_ref}/decision` | ApprovalDecision | 200 AppSuccess_ApprovalMutation_ |
| A12 | POST | `/api/app/v1/approvals/{approval_ref}/revoke` | IdentityModel | 200 AppSuccess_ApprovalMutation_ |
| A18 | GET | `/api/app/v1/documents` | None | 200 AppSuccess_AppPage_DocumentMetadata__ |
| A01 | GET | `/api/app/v1/session` | None | 200 SessionSuccess |
| A02 | POST | `/api/app/v1/session/login` | LoginRequest | 200 SessionSuccess |
| A03 | POST | `/api/app/v1/session/logout` | IdentityModel | 204 empty body |
| A05 | GET | `/api/app/v1/tasks` | None | 200 AppSuccess_TaskPage_ |
| A04 | POST | `/api/app/v1/tasks` | TaskCreate | 200 AppSuccess_TaskDetail_; 201 AppSuccess_TaskDetail_ |
| A06 | GET | `/api/app/v1/tasks/{task_ref}` | None | 200 AppSuccess_TaskDetail_ |
| A19 | POST | `/api/app/v1/tasks/{task_ref}/cancel` | IdentityModel | 200 AppSuccess_CancelResult_ |
| A15 | GET | `/api/app/v1/tasks/{task_ref}/operations` | None | 200 AppSuccess_OperationList_ |
| A16 | GET | `/api/app/v1/tasks/{task_ref}/operations/{operation_ref}` | None | 200 AppSuccess_OperationView_ |
| A08 | GET | `/api/app/v1/tasks/{task_ref}/planning` | None | 200 AppSuccess_PlanningView_ |
| A07 | POST | `/api/app/v1/tasks/{task_ref}/planning` | PlanningStart | 200 AppSuccess_PlanningView_ |
| A17 | GET | `/api/app/v1/tasks/{task_ref}/timeline` | None | 200 AppSuccess_AppPage_TimelineItem__ |
| A13 | GET | `/api/app/v1/tasks/{task_ref}/workflow` | None | 200 AppSuccess_WorkflowView_ |
| A14 | POST | `/api/app/v1/tasks/{task_ref}/workflow/continue` | IdentityModel | 200 AppSuccess_WorkflowView_ |
| C / OwnerBearer | GET | `/api/audit-events` | None | 200 array[AuditEventResponse] |
| C / OwnerBearer | POST | `/api/consents` | ConsentRequest | 200 ConsentResponse |
| C / OwnerBearer | GET | `/api/control/v1/approvals` | None | 200 PendingApprovalList |
| C / OwnerBearer | GET | `/api/control/v1/approvals/{approval_ref}` | None | 200 ApprovalReview |
| C / OwnerBearer | POST | `/api/control/v1/approvals/{approval_ref}/resolve` | ApprovalResolution | 200 ApprovalResolutionResult |
| C / OwnerBearer | POST | `/api/control/v1/approvals/{approval_ref}/revoke` | IdentityModel | 200 ApprovalRevokeResult |
| C / OwnerBearer | POST | `/api/control/v1/tasks/{task_ref}/consents` | ConsentCreate | 201 ConsentGrantResult |
| C / OwnerBearer | POST | `/api/control/v1/tasks/{task_ref}/consents/{consent_ref}/revoke` | IdentityModel | 200 ConsentRevokeResult |
| C / OwnerBearer | POST | `/api/control/v1/workflow-checkpoints` | WorkflowPrepare | 200 WorkflowSnapshot |
| C / OwnerBearer | GET | `/api/control/v1/workflow-checkpoints/{binding_ref}` | None | 200 WorkflowSnapshot |
| C / OwnerBearer | POST | `/api/control/v1/workflow-checkpoints/{binding_ref}/admit` | WorkflowIdentity | 200 WorkflowSnapshot |
| C / OwnerBearer | POST | `/api/control/v1/workflow-checkpoints/{binding_ref}/claim` | WorkflowIdentity | 200 WorkflowSnapshot |
| C / OwnerBearer | POST | `/api/control/v1/workflow-checkpoints/{binding_ref}/complete` | WorkflowIdentity | 200 WorkflowSnapshot |
| C / OwnerBearer | POST | `/api/control/v1/workflow-checkpoints/{binding_ref}/pause` | WorkflowPause | 200 WorkflowSnapshot |
| C / TaskAgentBearer | POST | `/api/gateway/v1/execute` | ToolRequest | 200 ToolResponse |
| C / TaskAgentBearer | GET | `/api/gateway/v1/operations/{request_id}` | None | 200 OperationStatus |
| C / TaskAgentBearer | POST | `/api/gateway/v1/operations/{request_id}/resume` | ResumeExecution | 200 ControlledExecutionResult |
| C / OwnerBearer | POST | `/api/tool-permissions` | ToolPermissionRequest | 200 ToolPermissionResponse |
| C / OwnerBearer | POST | `/api/tools/execute` | ToolExecuteRequest | 200 LegacyToolResult |
| A / Public | GET | `/health` | None | 200 HealthResponse |

## All documentation registrations

| Methods | Exact path | Public audience |
| --- | --- | --- |
| GET, HEAD | `/openapi.json` | Denied with 404 |
| GET, HEAD | `/docs` | Denied with 404 |
| GET, HEAD | `/docs/oauth2-redirect` | Denied with 404 |
| GET, HEAD | `/redoc` | Denied with 404 |
| GET | `/api/app/v1/openapi.json` | Origin/Host-qualified schema only |

## Coverage and runtime qualifications

**Request bodies:** 22/22 POST operations documented. The 11 original missing bodies now
use the actual ToolRequest, ConsentCreate, IdentityModel, ApprovalResolution, WorkflowPrepare,
WorkflowPause, WorkflowIdentity and ResumeExecution models. Existing bounded parsers remain
in place: duplicate keys, malformed/nonfinite JSON, compression, media, depth, size,
strict types and extra fields retain their existing outcomes. Owner reference syntax is
described without adding validators that would turn historical 404 responses into 422.

Gateway action/argument and app profile/resource correlations are expressed conditionally.
Consent resource uniqueness/count and canonical workflow checkpoint UUID syntax are also
documented. Stateful authorization and all remaining model validators still run server-side.
Legacy ConsentRequest/ToolPermissionRequest preserve their original coercion and ignored
extra-field behavior; schemas describe canonical JSON types, not a new strict parser.

**Responses:** every business operation has a non-generic success contract. Five original
control responses are now named DTOs, and the legacy harmless-tool result has its exact
result wrapper. Control JSONResponse paths preserve historical timestamp serialization.
Nullable fields and required serialization defaults are retained; task creation now also
documents its existing 200 replay response alongside 201 creation. Logout is a bodyless 204.
Observed bodies are checked against emitted schemas, including explicit JSONResponse paths.

**Errors:** browser responses use the existing AppFailure-compatible outer shape; reason_code
is currently null. Fixed closed business denial reasons remain in planning/operation and
trusted authorization DTOs. Owner authentication and legacy HTTPException detail strings,
framework validation detail arrays, and GatewayError are documented separately, including
their actual unions. Private unhandled 500 remains text/plain; no fabricated JSON promise.
Browser unexpected 500 is sanitized INTERNAL_ERROR; POST marks command uncertainty and
reconciliation without inventing an execution result. No authoritative reason enum changed.

**Authentication:** public bootstrap/liveness have no session requirement. Browser POST
security is cookie **AND** X-Ghost-CSRF, plus mandatory exact Origin/Host/peer checks.
The cookie is HttpOnly/SameSite=Strict; HTTPS uses Secure __Host-ghost_session, explicit
HTTP loopback uses ghost_demo_session. The static artifact describes that HTTP loopback
profile; runtime HTTPS schema uses its configured cookie name. Login/logout use preauth
or current cookie/CSRF, never an owner bearer. Pairing remains explicit, one-use and disabled
by default. Private OwnerBearer and TaskAgentBearer are absent from frontend artifacts.

**Pagination and provenance:** task/catalog/timeline use the same limit 1–50/default 20
and bounded opaque cursor shape. Approval lists and operation lists remain bounded without
a cursor. Existing OFFLINE_DEMO, mock/simulated/fake/unconfirmed provenance is preserved.
A18 remains the approved six-field owner metadata policy; it grants no protected access.

## Generated artifacts and reproduction

- [Frontend OpenAPI](generated/ghost-app-v1.openapi.json): 20 operations, 44 reachable schema components; no trusted bearer schemes or private execution/checkpoint/storage components.
- [Private combined OpenAPI](../integration/step44e_logs/trusted-backend.openapi.json): 39 operations, 84 schema components; trusted development audience only.
- [Raw registered inventory](../integration/step44e_logs/route-inventory.json) and [coverage](../integration/step44e_logs/coverage.json).

From repository root, using installed interpreters only:

```powershell
& 'member_a_backend/nvidia backend/.venv/Scripts/python.exe' -B 'member_a_backend/nvidia backend/scripts/export_openapi.py'
.venv/Scripts/python.exe -B tools/validate_openapi.py docs/integration/step44e_logs/trusted-backend.openapi.json
.venv/Scripts/python.exe -B tools/validate_openapi.py docs/frontend-handoff/generated/ghost-app-v1.openapi.json
```

The exporter clears private application environment/configuration, preserves required OS
profile settings, blocks sockets/MySQL and never connects an engine. OpenAPI remains 3.1.0;
combined info.version remains 1.0.0; the new frontend artifact identifies ghost-app-v1.
FastAPI OpenAPI model validation, structural/security/reference checks and installed
Draft 2020-12 JSON Schema validation run offline. No external schema fetch is permitted.

No openapi-typescript/TypeScript compiler is installed in the inspected toolchain.
No TypeScript declarations were invented or package installed. When Member C has its
approved local generator available, the exact schema-to-types command is:

```powershell
openapi-typescript docs/frontend-handoff/generated/ghost-app-v1.openapi.json --output docs/frontend-handoff/generated/ghost-app-v1.d.ts
```

Record/pin that existing generator version in C's toolchain before comparing generated output.
The command was not executed here; TypeScript compilation is not claimed. The generated
OpenAPI already covers sessions, tasks/planning, approvals, workflow/continuation, operation
history, timeline, catalog, errors, pagination and provenance.

See [Step 44E acceptance](../integration/STEP44E_OPENAPI_ACCEPTANCE.md) for final tests,
preservation evidence, remaining limitations and Step 44F readiness.
