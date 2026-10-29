# Frontend implementation plan — deadline-first

## Phase 0 — Gate and inventory (no implementation guesswork)
Verify backend acceptance, locate real generated OpenAPI, inspect package manager/runtime, existing frontend directories, and same-origin constraints. Verify `design.md` and skill installation. Record exact 19 operation IDs, requests, responses and errors. STOP if OpenAPI unavailable.

## Phase 1 — Design system and visual prototype
Initialize frontend only after checking existing project layout. Establish fonts, CSS tokens, responsive AppShell, the signature Decision Rail (fixture-only visual state clearly labeled preview), keyboard navigation, loading and error components. Take desktop/mobile screenshots; critically refine visual hierarchy before adding pages.

## Phase 2 — Auth and typed API
Generate types from actual OpenAPI, implement same-origin client, session/pairing, CSRF, logout, and expiry. Exercise browser runtime with local FastAPI. Don't disable security to make local dev convenient.

## Phase 3 — Main flows
Implement task list/create/detail, planning, pending approvals and decisions, workflow continuation, audit and operation detail. Integrate real local SQLite demo via documented bootstrap.

## Phase 4 — Supporting screens
Catalog metadata, settings, responsive navigation, stable empty/error states, consistent provenance. No empty clickable nav sections.

## Phase 5 — QA and capture
Test at 1366×768 and 390×844, accessibility, TypeScript lint/build, real ASGI E2E, restart, replay and denial scenarios; verify screenshots and record complete 150–170 second demo footage. No hidden red errors.

## Phase 6 — Submission
README/license, public code sanitization, working demo URL (separate safe public synthetic demo if needed), under-3-minute YouTube, specific Nebius/NVIDIA feedback, team invitation acceptance, final form review.

## Stop rules
- Any user-facing credential exposure, broken ownership or falsified security state blocks release.
- Missing backend route: do not fake a success; show a clear unsupported state.
- No production deploy of local-only pairing auth. No OpenShell/native enforcement claims.

## Handoff between phases
At each milestone Codex reports changed files, screenshots/checks, exact tests, observed failures, known limitations, and next command. Do not generate an endless phase series; build within the deadline.
