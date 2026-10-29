# Frontend/server security boundaries

Contract: **ghost-app-v1, draft 0.1.0**. Step 44A, 2026-10-28.
**PROPOSED controls and tests; no implemented authentication or isolation claim.**

## 1. Trust and capability map

| Principal/surface | May do | Must not do |
| --- | --- | --- |
| Browser user | Authenticate with local one-use pairing, hold HttpOnly session, use CSRF header, select fixed task profile, review exact proposal, make owner decision, request metadata continuation, inspect safe metadata | Read backend credentials, set owner/task scope, call legacy/gateway/control routes as a service, submit tool payloads, choose executor/provider/path/transport or directly dispatch |
| A application router | Map authenticated session to stored fixed owner; validate typed handlers; delegate to A services; supervise bounded B commands; create allowlisted projections | Forward arbitrary URL/method/headers, accept model consent, blindly serialize ORM/audit/detail/result objects, turn login/session into tool authority |
| A trusted services | Sole task/owner/consent/approval authority; durable operation/attempt history; dispatch-time checks | Trust UI booleans, cursor possession, model text, a B result or claimed provenance as authorization |
| Trusted B control host | Run existing orchestration/client/checkpointer interfaces with injected fixed configuration, exact task identity and bounded requests | Give host credentials to prompts/checkpoints/model outputs or an untrusted sandbox; select public execution from a browser field |
| Model/untrusted documents | Propose typed intent/actions; supply data | Grant/extend/revoke consent, change owner, authorize execution, control callback URLs or override policy |
| Separate trusted operator | Explicitly invoke an eligible controlled synthetic execution using existing task credential and exact completed binding | Add a browser dispatch endpoint, skip approvals, change original arguments, resend UNKNOWN or claim real delivery |

The B control process is trusted local application code; native sandbox isolation
is not established. Process separation solves the two Python `app` namespaces and
keeps credentials out of model interfaces; it is not an OS security boundary
against code running as the same host user. No universal prompt-injection or
host-compromise guarantee follows from sessions or strict DTOs.

## 2. Credential custody and ingress

| Value | Allowed location | Forbidden location |
| --- | --- | --- |
| Owner API bearer | Trusted A/B-control private memory/config outside model/sandbox | Browser JSON/JS/storage, task state, model request, checkpoint, audit |
| Task gpa bearer | Existing A hashed identity record + private trusted client injection | Browser or application DTO/command result, logs, checkpoints, prompts |
| Provider / DB / SMTP secret | Existing trusted service boundary only; unused live credentials in this demo | Frontend build environment, B graph, untrusted sandbox, evidence artifacts |
| Session ID | HttpOnly cookie and server-side digest | JSON/HTML/event payload, JS-readable storage, logs or browser Authorization header |
| CSRF token | Session/preauth private memory and same-origin response/JS memory | URL/query, persisted browser storage, downstream gateway header or grant |
| Pairing code | One private operator display and transient login input/body | Bundled fixed code, normal logs, URL, audit, fixtures, code-generation endpoint |
| Resume hint / nonce / checkpoint path | Existing trusted execution/checkpoint host only; existing attempt digest where required | Frontend schema, timeline, browser continuation request |

No credentials were imported/generated for this design. Future code must use
allowlisted child-process environment variables, not inherited private .env or
provider/DB credentials. Private IPC carries host/task credentials only between
trusted components; capture pipes without printing bodies or retaining a command
transcript. The graph gets task/user request/typed bindings, never host secrets.

Application handlers are an allowlist of 19 operations, not a reverse-proxy API.
Reject Authorization and identity headers on the app surface. Existing routes
retain their bearer parsing and role restrictions; never add a cookie-to-owner
fallback to /api/gateway/v1 or raw workflow claim/pause/complete routes.
Public ingress may expose only UI/static assets, /api/app/v1 and /health; old
bearer/documentation routes stay on the private backend listener. Test the edge
denies as well as the downstream role checks. CORS is not the edge or auth layer.

## 3. Per-request owner and object checks

Order: canonical origin/Host -> valid server session -> CSRF for POST -> strict
request validation -> owner-scoped object discovery -> durable command identity
-> delegated service/current authority checks -> explicit safe projection.
No cache/replay result may be returned before owner verification.

- Task queries require GatewayTask.owner_id=session owner and the successful
  application-create association. Scope/versions/profile come from stored A state.
- Approval paths resolve A's original owner/task/operation and exact reconstructed
  request. UI sends only resolution, never replacement reviewed content.
- Workflow discovery uses the owned task's binding. The browser cannot attest a
  UUID/thread/checkpoint or provide expected_authorization_version.
- Operation/history joins require owner and exact task/ref equality, including
  linked approval/attempt. Do not relax an agent endpoint to accept the owner token.
- Catalog reads are owner management metadata over registered active synthetic
  rows. No protected file content/read, registration, uploads or storage path is
  exposed; management metadata does not become file consent.
- Cursor payloads are signed and scope-bound, but every page reruns owner filters.
  References, digests, IDs and cursors are correlations, not authorization grants.

Existing `_owned_task`, `_owner_operation`, `authenticated_task`, catalog ownership,
workflow history and deterministic consent checks remain authoritative. New owner
read projections need their own negative-owner tests; DTO construction alone is
not enforcement. Unknown/foreign objects have indistinguishable404 responses.

## 4. Protected execution cannot originate in browser handlers

The application router's planning command may only call the authorization-only
gateway client. Approval handlers only resolve/revoke. Continue invokes the
existing reference-only workflow and ends at SAFE_STOPPED/RESUMED. No callback,
queue, finally block, response background task or React effect dispatches after
these operations. This deliberate operator-assisted demo avoids an implicit
execution-contract change.

The independent trusted operator can explicitly use the existing controlled
client only after workflow completion and exact owner approval. The backend
capability is off by default and can enable only the reviewed synthetic/fake
profile in this application version. A rechecks task/credential/approval/consent,
versions/expiry, original request/key/digest and completed workflow, reserves one
durable attempt, then applies its existing nonce fence. No owner-token execution,
model-generated modes, replacement arguments, shell, arbitrary file path or SMTP.

Session/idempotency keys are not substituted for operation request_id/key or
resume hints. Unknown outcome, ambiguous DB/HTTP acknowledgment, DISPATCHING and
lost host/checkpoint completion stop progression. No retries, takeover lease,
new key, new credential or replacement task can authorize a resend. Revocation
after the dispatch commit cannot guarantee physical cancellation; preserve
in_flight and distinguish historical observation from current authority.

## 5. Safe projections and honest provenance

Use named typed DTOs from [02](02_APPLICATION_API_CONTRACT.md), never
`model_dump()` on operational ORM objects or passthrough `AuditEvent.detail`.
Timeline mapping has a closed event-kind/state/reason allowlist. Only real A
audit IDs with verified task membership generate event_ref. Unrecognized legacy
events are omitted; no invented progress events or prompt text.

Current source mapping: gateway.authorization without an attempt ->AUTHORIZATION;
with attempt_ref and DISPATCHING ->EXECUTION_ADMISSION; with a genuine terminal
attempt ->EXECUTION_OUTCOME. gateway.approval.transition/viewed and
gateway.workflow.transition map to their named kinds after typed state/ref checks.
Uncorrelated catalog/legacy audit rows are omitted from a task timeline; display
catalog metadata separately rather than inventing a task association.

Exact approval detail is the only application response containing reviewed email
subject/body/recipient, and only the fixed synthetic template is supported. It
is owner-private, no-store, escaped text, outside audit/timeline/telemetry. It is
not a result or authorization grant. Raw document content is absent everywhere.
Operation history omits raw result, receipt/draft payload, hint, nonce, digests,
storage/configuration paths and credentials. A terminal state can be observed
without disclosing a protected/expired result or regenerating it.

Provenance fields describe configured versus observed evidence explicitly:

| Evidence | Allowed display |
| --- | --- |
| Fixed profile selected; no attempt | CONFIGURED, mode=null, effect=NONE; not a completed action |
| Validated mock TaskPlan | MOCK_MODEL; actual structured plan metadata, never "live Nemotron" |
| A authorization record | Genuine decision/ref; NOT_EXECUTED remains nonexecution |
| Correlated simulated attempt/outcome | SIMULATED; fixed operation completed, no document read |
| Correlated synthetic draft | EMAIL_DRAFT / NO_MESSAGE_SUBMISSION; no email submitted |
| Correlated controlled result plus trusted fake-adapter observation | MAILPIT_SEND is the existing mode name; application effect FAKE_SMTP_ONLY; no Mailpit network or external delivery |
| A mode/result with missing trusted host provenance | UNATTESTED / UNCONFIRMED; mode alone cannot prove adapter identity or delivery |
| UNKNOWN / DISPATCHING | Uncertain effect; no sent/delivered/success claim or resend |

Trusted operator observation metadata may be retained only after correlating
operation/attempt/audit refs and validating the exact mode/result against the
configured adapter and its bounded observation. Use the proposed app command
record's safe_result, not B checkpoints or A audit payloads. If this evidence is
lost, show UNATTESTED; do not change historical execution status or rerun a tool.
Contradictory mode/effect values fail projection validation and become sanitized
read failure, never a conveniently relabelled success.

Historical live Nemotron Step 41 and local Mailpit Steps 28/36/39 evidence may be
linked as archives. They do not become observations for a newly created app task.
Do not claim live model availability, email delivery or end-to-end safety from
those separate components.

## 6. React/browser and operational requirements

- Keep trusted config out of frontend build inputs, including NEXT_PUBLIC and
  source maps. The client needs only same-origin paths, public schema and labels.
- Fetch with same-origin credentials; hold CSRF only in memory; no token in URLs,
  local/sessionStorage or analytics. On401 stop polling and rebootstrap/login.
- Escape model/document/approval text with ordinary React text rendering; no
  dangerouslySetInnerHTML, executable markdown, automatic remote-image/URL fetch
  or untrusted attachment preview. Approved fixture text is still untrusted data.
- Require a deliberate owner click for approval/rejection/revocation/continue;
  do not auto-approve in component effects, cached state or model-response handlers.
- Apply a restrictive CSP: default-src 'none', connect-src 'self', object-src
  'none', base-uri 'none', frame-ancestors 'none', form-action 'self'; script/style
  allowances only same-origin assets or per-response nonces as required by C's
  chosen build. No unsafe-eval or blanket unsafe-inline workaround. Set
  X-Content-Type-Options:nosniff and Referrer-Policy:no-referrer.
- Cache-Control:no-store on session, app JSON and exact review responses;
  service workers/CDNs must not cache them. Do not include request/response body
  tracing or credential-bearing headers in telemetry.
- Bound concurrent planning to one host command globally for this local demo;
  reject429 rather than accumulate an unbounded queue. Browser reads are bounded
  and paginated as specified; POST retries are manual status-first decisions.

These are implementation acceptance requirements, not claims that frontend,
headers, ingress, session middleware or deployment currently exists. No actual
browser or deployment test was performed in Step 44A.

## 7. Security acceptance cases for Step 44B

| Case | Required assertion |
| --- | --- |
| Login/session fixation/CSRF | Wrong/replayed/expired code denied; concurrent redemption one winner; old preauth ID invalid; missing/foreign Origin, stale CSRF, duplicate cookie and credential substitution denied |
| Cross-owner reference | Foreign task, approval, workflow, operation or catalog ref ->404; zero model/authority/executor calls; cursor cannot cross scope |
| Parameter smuggling | Extra owner/role/purpose/URL/tool/recipient/executor/body/version fields reject; no downstream request before validation |
| Untrusted text | Prompt/document fake consent cannot approve, change task or choose handler; out-of-profile plan stops before admission |
| Approval race | Revocation/expiry after GET and before decision/continue/dispatch is freshly enforced; no stale replay grants authority |
| Continue boundary | Genuine SQLite continuation returns safe metadata and **zero execution/SMTP calls**, including retries/crashes |
| Replay/crash | Same app command identity stable; changed body409; one planning call/task; interrupted command UNCERTAIN, no automatic rerun/resend |
| Projection privacy | No actual test bearer/code/cookie/prompt/body/result markers in history/timeline/checkpoints/logs; fixed email text only in owner review |
| Provenance | Mock/fake/simulated cannot become live; mode alone insufficient; UNKNOWN never sent; observation loss never triggers regeneration |
| Ingress/schema | Private bearer routes denied at public edge; application schema has cookie+CSRF only and no internal execution interface |

## 8. OpenShell boundary retained

Keep OS30 **DEFER_LIVE_SANDBOX**. Installation, reviewed policy/image, static
tests and historical TCP/TLS callback checks are not native agent isolation.
**NOT VERIFIED:** native admission, Landlock enforcement, full agent isolation,
end-to-end execution within OpenShell, robust failure cleanup and distributed
exactly-once guarantees. No Docker/OpenShell/WSL configuration or runtime work is
part of these contracts. A later application readiness verdict cannot promote
these classifications.
