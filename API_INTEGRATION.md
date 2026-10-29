# API integration: use source, never guess

## Authoritative input
- `docs/frontend-handoff/generated/ghost-app-v1.openapi.json` (generated from FastAPI; OpenAPI 3.1; reported all 19 browser operations documented).
- `docs/frontend-handoff/02_APPLICATION_API_CONTRACT.md`, `06_VERIFIED_API_INVENTORY.md`, final Step 44F acceptance.
- Inspect current app routes and response models when documentation and implementation diverge.

## Known verified task routes ONLY (relative to `/api/app/v1`)
- `POST /tasks` — create.
- `GET /tasks` — list.
- `GET /tasks/{task_ref}` — detail.
- `POST /tasks/{task_ref}/planning` — plan.
- `GET /tasks/{task_ref}/planning` — planning status/result.

**All other endpoint paths and exact request/response fields MUST be imported from the OpenAPI artifact.** Do not assume guessed `/approvals`, `/workflow`, or `/session` names.

## API client requirements
- Typed operation-specific functions based on generated OpenAPI types.
- Same-origin base URL and `credentials: 'same-origin'` when applicable.
- CSRF token attached to state-changing operations per actual 44B implementation.
- Structured errors preserve HTTP status and backend reason without exposing raw details.
- Abort signals for UI navigation, but do not interpret aborted network requests as cancelled backend mutations.
- Idempotency keys for contracted mutations; stable across retry attempts, generated per user intent.
- Cache invalidation after confirmed changes; no optimistic approval success.
- Bounded polling only for endpoints supporting status reads; stop on terminal or session expiry.
- Protect against double-submit, 409/replay conflict, UNKNOWN; do not auto-resend protected operations.

## Source-generation gate
1. Validate JSON syntax and OpenAPI references.
2. Inspect paths and security schemes.
3. Generate TypeScript types in an approved offline toolchain.
4. Compile typecheck and run schema parity tests.
5. Commit generated types only after reviewed, if user authorizes.

## Mapping artifact
Codex must create a verified per-screen operation map from exact operation IDs, schemas and security requirements. If an operation does not exist, render read-only information or disable that action with explanatory text. Avoid placeholder API successes.
