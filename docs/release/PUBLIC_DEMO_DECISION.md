# Public demo decision — Phase 5A

**PUBLIC_DEMO_IMPLEMENTATION_READY** means the smallest safe design is specified for a separately approved implementation. It does not mean a public demo already exists, works or has been deployed.

## Decision

Choose **A: a separately built interactive synthetic browser demonstration with no trusted backend connection**. It is the shortest safe path to a working public URL. The existing local application cannot simply be hosted: it requires private pairing and refuses non-loopback origin/host/listener access. Option B, properly secured public deployment of the real application, is not already supported or realistically qualified within this release-preparation phase.

Keep the accepted local application as genuine backend evidence. Do not tunnel it, copy its session model to a public endpoint, weaken Origin/Host checks, or claim that public synthetic events came from its stored audit database.

## Minimal separate implementation

| Requirement | Concrete implementation boundary |
| --- | --- |
| Delivery | Static browser assets from a separate build/entry point. No FastAPI listener, pairing UI, API route, backend database, server credential or provider key. |
| Identity | Persistent visible banner: **INTERACTIVE SYNTHETIC DEMO — no backend execution**. Page title and result panels retain the same distinction. Local pairing cannot appear functional. |
| Interaction | Create a bounded synthetic task, request a deterministic simulated plan, inspect a synthetic authorization request, explicitly approve/reject/revoke, explicitly continue, observe simulated SAFE_STOPPED and inspect a simulated event log. Controls must change real browser state rather than play a canned animation. |
| State | Small explicit browser state machine with fixed synthetic fixtures. No claims of persistence, real ownership enforcement or authenticated tenant isolation. Reset clears demo state. No tokens or credentials in browser storage. |
| Time/expiry | Show actual demo deadlines or a clearly labelled “simulate expiry” action. Never present accelerated simulated time as an observed backend expiry. |
| Uncertainty | A labelled UNKNOWN example stops progression and offers inspection/reset. It must not show successful execution or automatic retry. |
| Record labels | Every operation/event detail is labelled synthetic. Do not reuse real local task references as if reachable publicly. Explain that real durable audit/session checks belong to the separately accepted local product. |
| Assets | Reuse approved visual tokens/components where practical, with separate synthetic data adapters. Include reviewed font/icon/framework notices. No unreviewed real content or private local paths. |
| Network | No `/api/app/v1`, private gateway, inference, SMTP, arbitrary fetch, analytics or backend URL. Production validation must inspect network activity and generated bundles, not rely only on source labels. |
| Accessibility | Native labelled controls/dialogs, explicit focus management, keyboard tests, reduced motion and no overflow at 390/768/1280/1440/1920px. |

Do not pass synthetic data through the real production API client and silently fabricate successful responses. The synthetic state machine must be an explicit separate product mode with its own tests and labels. The existing Decision Rail semantics remain: permission and safe continuation are not execution.

## Acceptance before any public URL

1. Implement that separate entry/build with functional task/review/continuation/reset interactions.
2. Unit-test state transitions, reject/revoke/expiry/cancel/UNKNOWN and prevention of automatic progression.
3. Browser-test the complete synthetic path, controls, labels, keyboard behavior and responsive layouts.
4. Confirm no local-auth/backend/provider calls or credentials in bundles, browser storage or network requests. Ensure the static artifact contains only reviewed synthetic assets and notices.
5. Review the exact static artifact and hosting plan, including HTTPS/CSP/resource policy and provider terms, under separate deployment approval.
6. Deploy only after explicit instruction; then verify the actual public URL separately. A local passing preview does not establish a working public URL.

## Option B remains blocked

Real public interaction requires replacement public identity/session handling, secure HTTPS/proxy trust, tenant isolation, quotas, secret custody, durable database/recovery acceptance and any separately authorized live inference/execution. Current SQLite/single-owner pairing tests do not qualify those capabilities. Native OpenShell enforcement, production MySQL and live inference through the application remain unverified.

## What remains

The design is ready for implementation; **no public-demo code or URL was created in Phase 5A**. Next steps are separate approval to implement option A, passing its explicit synthetic-mode tests, license/content review, deployment approval and actual hosted verification. No existing local authentication is exposed by this decision.
