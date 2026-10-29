# Member B — six-phase Codex roadmap

Dates are target milestones based on October 12–29, 2026. Codex implements **one phase per approved prompt** and stops.

## Phase B0 — Repository prep + contract agreement (Oct 12)
**Build:** inspect repo, create B-owned directories and contract-first stubs, establish test conventions. Agree action names and the strict gateway mock with A. Send task/event samples to C.
**Pass:** imports work; no teammate files modified; contracts documented.

## Phase B1 — NVIDIA/Nebius model adapter (Oct 13–14)
**Build:** verify console model IDs and account access; real Nemotron Super call, optional Nano; JSON/tool-call capability checks; timeouts, bounded retry and token/latency telemetry.
**Pass:** 10/10 structured-output fixture calls parse, tool-call feature behavior documented, no secrets leaked.
**Hard dependency:** A separately proves OpenShell host, sandbox and secret-isolated inference. Escalate immediately if blocked by end Oct 14.

## Phase B2 — LangGraph personal agent + mock gateway (Oct 15–17)
**Build:** typed task state and state transitions, model tool-selection, strict tool allowlist, mock gateway, pause/resume on approval, denial/error handling.
**Pass:** multi-step mock task works; injection text cannot turn gateway-denied action into a side effect; tests pass.

## Phase B3 — Persistent personal memory + consent proposals (Oct 18–20)
**Build:** structured memory repository protocol, scoped preference retrieval, corrections/superseding, provenance, typed *consent proposals* for user review.
**Pass:** preference persists over distinct sessions (using approved storage integration), correction changes behavior, no model-generated auto-approvals.

## Phase B4 — Three real skills (Oct 20–23)
**Build:** Morning Brief (A-owned scheduler triggers), Private Document Assistant (gateway file tools), Smart Email Assistant (draft/approved Mailpit send). Versioned approved skill definitions.
**Pass:** all three work on approved fixtures; explicit denial produces no email side effect; task and approval events visible to C.

## Phase B5 — Evaluation + production integration (Oct 24–26)
**Build:** replace mock adapter with A gateway, test on verified OpenShell runtime, write adversarial fixtures/runner, benchmark model/agent paths, assist UI integration.
**Pass:** actual end-to-end authorized send, unauthorized denial, revoked-consent denial, memory persistence, honest evaluation with recorded failure cases.

## Final submission preparation (Oct 27–29)
Freeze features; fix bugs, document model usage, aid demo rehearsal, provide reproducible benchmark and sponsor-feedback notes. Submission target Oct 29.

## Shared milestones
- **Oct 14:** OpenShell and Nemotron viable, otherwise team-level pivot decision.
- **Oct 19:** full real vertical slice: model -> gateway -> permitted/denied action.
- **Oct 23:** Personal AI memory and three skills complete.
- **Oct 26:** tested deployed demo.
- **Oct 29:** submission ready.
