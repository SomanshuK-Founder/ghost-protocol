# Ghost Protocol — frontend workspace pack

**Purpose:** Build a distinctive, demo-ready Personal AI interface on top of the accepted **offline** Ghost Protocol application backend.

## Status and evidence
- Step 44F-R2 verdict reported: `APPLICATION_BACKEND_READY_FOR_FRONTEND` for **local offline** use.
- Member A: 859 passing offline tests (313 MySQL tests deselected); Member B: 741 passing (one paid-inference test skipped); 117 mock-harness tests; 19 browser-facing application operations and 60 wire cases accepted.
- Native OpenShell sandbox admission/enforcement, real MySQL migrations 0012–0013, deployed HTTPS, new live Nemotron through app APIs, and public email delivery **not verified**.
- This pack is a **project specification**, not a copy of live source or proof that the frontend runs. Actual field names, routes, and statuses MUST be derived from `docs/frontend-handoff/generated/ghost-app-v1.openapi.json` and the current source; this pack deliberately does not invent them.

## How to place
Copy this entire folder inside your existing Ghost repository (for example `frontend-workspace/`). Do **not** overwrite your existing `AGENTS.md`, backend, `.env`, contracts, or migrations. In Antigravity, open the repository root and have Codex read `frontend-workspace/README_START_HERE.md`, `design.md`, and `IMPLEMENTATION_PLAN.md`.

## Required existing source, not included in this ZIP
`docs/frontend-handoff/generated/ghost-app-v1.openapi.json`, `docs/integration/STEP44F_R2_FINAL_ACCEPTANCE.md`, the approved `docs/frontend-handoff/01...06` contracts, and backend source. If unavailable, STOP before wiring APIs; create only visually honest fixtures in a separately labeled preview mode.

## Read in this order
1. `design.md` — visual identity, layout, motion and demo aesthetics.
2. `PRODUCT_SCOPE.md` — what actually works / must not be claimed.
3. `ARCHITECTURE.md` and `API_INTEGRATION.md` — stack and contract binding.
4. `AUTH_SECURITY.md` — local-only pairing / CSRF rules.
5. `SCREENS.md`, `COMPONENTS.md`, `STATE_UX.md` — implementation specs.
6. `IMPLEMENTATION_PLAN.md`, `QA_ACCEPTANCE.md` — build/test milestones.
7. `DEMO_STORYBOARD.md`, `SUBMISSION_CHECKLIST.md` — hackathon finish line.

## Non-negotiable
Do not expose trusted agent credentials, enable remote local-pairing, fabricate backend events, claim OpenShell enforcement, or present mock planning as live NVIDIA inference. Keep approval and execution separate. Never silently fill API schema gaps with guessed payloads.
