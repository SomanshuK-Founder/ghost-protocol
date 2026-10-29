# Ghost application authentication contract

Contract: **ghost-app-v1, draft 0.1.0**. Step 44A, 2026-10-28.
**PROPOSED — not implemented, approved for deployment, or runtime verified.**
This is a new application-layer contract. It does not amend the existing owner
bearer, agent bearer, gateway v1.3 or workflow v1.2 contracts. Implementation and
A/B/C sign-off are separate Step 44B work.

## 1. Inspected identity and selected boundary

Current A `app/security.py::require_bearer` compares one configured owner bearer
and returns `local-user`. `agent_auth.py` converts that principal to OwnerContext.
There is no password database, login, identity provider, cookie session or CSRF
service. `agent_identity.py` separately creates task-bound agent credentials,
stores token digests, and checks owner/task/epoch/expiry/revocation on every use.
No production identity/account system can be inferred from the synthetic users.

Select a **same-origin application router inside Member A's FastAPI process** as
the BFF. Its new prefix is `/api/app/v1`. The browser sees the React UI, this
prefix and public `/health` at one explicitly configured origin. A future dev
proxy may forward that prefix to A; it is not a credential-bearing generic proxy.
No new service, framework or external identity provider is required for this demo.

```text
Browser: session cookie + CSRF header
    -> A application router: session -> fixed owner -> object ownership checks
       -> A existing authoritative services / owner-safe read projections
       -> private supervised B host (separate app namespace)
          -> existing authenticated A gateway / workflow routes
```

The B host is a trusted control process, separate from model inputs and any
future untrusted sandbox. It holds credentials only in private memory. The
application router delegates directly to A services, so it need not forward the
owner bearer on local calls. Where B's existing WorkflowControlClient or gateway
client uses HTTP, A injects owner/task credentials server-side over private IPC;
the clients retain their existing fixed-origin and authentication requirements.
No browser identity header or JSON field becomes an OwnerContext.

## 2. Explicit authentication modes

| Mode | Contract |
| --- | --- |
| DISABLED | Default. Protected app routes and session bootstrap/login return 503 AUTH_NOT_CONFIGURED. Never auto-login the local owner |
| LOCAL_DEMO | Explicit trusted startup configuration, loopback-only listener, one configured public origin, existing `local-user`, one-use operator pairing, one active owner session |
| Production/shared remote use | Unsupported in draft 0.1.0. Fail startup if LOCAL_DEMO is combined with a non-loopback public origin/listener. A future approved identity provider requires a separate contract; no invented users, passwords, registration or provisioning |

The one configured origin may use HTTP on literal loopback `127.0.0.1` or `::1`,
or HTTPS on an explicitly qualified loopback origin. No wildcard hostname,
arbitrary forwarded Host, `Origin: null`, non-loopback HTTP, or LAN exposure.
An HTTPS environment uses the secure cookie policy below. This demo mode is not
an identity solution for a public hackathon deployment.

## 3. Local demo login: possession of a one-use operator code

Only an explicit trusted operator action creates a code: 32 random bytes,
URL-safe encoding (43 characters), expiry 120 seconds, one use. Keep only its
SHA-256 digest in the bounded in-memory auth store. Constant-time compare and
consume under one lock. Creating another code invalidates the previous code.

Display the code once on a private interactive operator terminal, outside normal
application logs. No login response, URL, query string, environment dump,
browser bundle, fixture or evidence file contains it. The human types it into the
local login form; the form sends it only in the login JSON body, clears the field
on submission, and never stores it. It is a short-lived demo login credential,
not API_BEARER_TOKEN, an agent credential, a production password or an account.
No code was generated or credential imported in Step 44A.

The operator, not an anonymous browser, may mint/reissue a code. There is no HTTP
code-generation endpoint, automatic login link or fallback to a backend secret.
No user ID/role/return URL is accepted. Successful pairing binds the session to
server-configured `local-user`; the synthetic fixture user list is not a login DB.

## 4. Sessions and cookies

Use an opaque 32-random-byte session identifier; store its digest, fixed owner,
independent CSRF token (SecretStr in server memory only), creation/last-activity/expiry times and server generation in
memory. Do not use a cookie containing a bearer, owner claims, serialized model
state or a reusable signed authorization grant. No session DB/Redis dependency
is needed for this explicitly single-process demo.

| Property | Exact proposed requirement |
| --- | --- |
| HTTPS cookie | `__Host-ghost_session`; HttpOnly; Secure; SameSite=Strict; Path=/; no Domain |
| HTTP loopback exception | `ghost_demo_session`; HttpOnly; SameSite=Strict; Path=/; no Domain; Secure=false only for explicitly selected literal-loopback HTTP mode |
| Lifetime | Idle 900 seconds; absolute 3600 seconds; `now >= deadline` is expired; cookie Max-Age never exceeds remaining absolute lifetime |
| Anonymous bootstrap | Same cookie name, unrelated random ID, no owner, TTL 120 seconds; at most 64 live preauth records; overflow 429 |
| Login | Atomically consume code, rotate the presented preauth/current session ID and CSRF token, invalidate any old owner session, create the sole current owner session |
| Logout | Invalidate session and CSRF server-side; expire the exact cookie with matching Path/flags; no GET logout |
| Restart/operator invalidation | Drop every session/preauth/code and rotate server generation. Stolen/old cookies do not survive restart. No session resurrection |
| Duplicate cookies | Reject ambiguous/malformed session cookie input; never select a convenient first/last credential |
| Cookie delivery | Credentials only through Set-Cookie; never echo session ID in JSON, HTML, events or errors |

Idle refresh is allowed after a valid authenticated request, capped by absolute
expiry. Repeated session polling cannot extend the absolute deadline. Authenticate
and authorize again before every mutating command, including idempotent replays.
Recheck expiry/generation before releasing a private response; if logout/expiry
won during a bounded command, return401 without its private payload. An already
admitted command may have committed metadata/owner decision; do not roll it back,
claim nondispatch from that401, or invoke it again on a new login.
In-memory sessions mean a single worker/replica is mandatory; multiple workers
must be rejected in demo configuration, not silently given divergent stores.

Logout terminates browser authority; it does not revoke durable consent, cancel
tasks, undo an admitted effect or promise interruption of an already admitted
metadata command. Task cancel and approval revoke are explicit owner actions.
Independent trusted operator execution still requires existing gateway checks;
it is not authorized by possession of a stale application command or cookie.

## 5. CSRF, origins and request validation

GET `/api/app/v1/session` establishes a bounded preauth cookie when needed and
returns an independent 32-byte CSRF token. This bootstrap creates no owner or tool
authority. The token is readable only in same-origin JSON and held in JS memory;
it is not a backend credential. It is bound to the server-side preauth/session.
All app JSON GETs validate Host and any supplied Origin. If Fetch Metadata is
present, accept only same-origin (or none for direct navigation), rejecting
same-site/cross-site values before cookie changes or private reads. In particular
a foreign navigation must not overwrite an owner cookie with a preauth cookie.
For session bootstrap/CSRF disclosure require either exact Origin or accepted
Fetch Metadata as well as Host; if both context headers are absent, reject 403
ORIGIN_FORBIDDEN. Modern same-origin fetch supplies this context; nonbrowser
tests/clients must explicitly provide the configured Origin.

All application POSTs, **including login and logout**, require:

1. Exact configured Origin, valid configured Host/public-origin handling, and a
   non-cross-site Fetch Metadata value when present. Reject missing/null/foreign
   Origin; do not derive the trusted origin from arbitrary forwarded headers.
2. The current cookie and `X-Ghost-CSRF` matching its independent token using a
   constant-time check. Reject missing/mismatched/stale tokens with 403 CSRF_INVALID.
3. `Content-Type: application/json`; no compressed request bodies; strict bounded
   JSON objects; no duplicate keys, nonfinite numbers or extra fields. Logout uses `{}`.

Use exact same-origin browser fetches. Application routes grant no cross-origin
credentialed CORS access. Keep existing bearer-router CORS behavior unchanged.
Trusted proxy headers, if later needed for HTTPS termination, are accepted only
from explicitly configured proxy addresses; the edge strips client-supplied
forwarding headers. These are later deployment requirements, not changes now.

Check origin/auth/CSRF before looking up idempotency results or touching owner
objects. Reject browser Authorization/service-token headers on the new app API;
an agent bearer cannot substitute for a session. GETs never approve, continue,
create a planning run or dispatch; harmless bootstrap/view-audit bookkeeping is
not an authorization mutation. JSON responses use Cache-Control: no-store.

## 6. Authentication endpoints (all NEW)

Envelope and shared validation/errors are defined in
[02_APPLICATION_API_CONTRACT.md](02_APPLICATION_API_CONTRACT.md). These endpoints
have no task/model/transport provenance; `mode` is explicitly LOCAL_DEMO.

| ID / method / URL | Request | Response | Checks / statuses | Idempotency / lifecycle |
| --- | --- | --- | --- | --- |
| A01 GET `/api/app/v1/session` | No body/query | 200 AppSuccess[SessionView] | Same-origin read policy; no bearer; 503 AUTH_NOT_CONFIGURED, 429 AUTH_RATE_LIMITED | Safe read; creates/returns anonymous bootstrap or inspects current owner session; no pagination |
| A02 POST `/api/app/v1/session/login` | LoginRequest `{pairing_code: SecretText43}` | 200 AppSuccess[SessionView authenticated=true], rotated Set-Cookie | Preauth/current cookie + CSRF + Origin; 401 LOGIN_FAILED for expired/used/wrong code; missing/malformed field ->422 INVALID_REQUEST; 403 ORIGIN_FORBIDDEN/CSRF_INVALID; 429 AUTH_RATE_LIMITED; common malformed/config errors | One-use, **not replayable**; Idempotency-Key rejected. Lost response requires a fresh operator code; no retry with the used code |
| A03 POST `/api/app/v1/session/logout` | EmptyObject `{}` | 204, expired Set-Cookie, no JSON body | Current bootstrap/owner cookie + CSRF + Origin; 403 on failed CSRF/origin | Repeating with a still-valid cookie safely invalidates; after invalidation rebootstrap session and log out if desired; no Idempotency-Key, no pagination |

`SessionView` is a discriminated union, all listed fields required:

- Anonymous: `{authenticated:false, mode:"LOCAL_DEMO", csrf_token:SecretText43,
  owner:null, idle_expires_at:null, absolute_expires_at:null}`.
- Authenticated: same shape with `authenticated:true`, owner
  `{display_name:"Local demo owner"}` and aware UTC expiry timestamps.

No public owner ID, bearer, session ID, DB identity or login code is returned.
SecretText43 is a strict string matching `^[A-Za-z0-9_-]{43}$`, with repr/input
error values suppressed. The server retains the current CSRF token in private
memory so a same-origin page reload can inspect the session without rotating it.
Session status after an invalid/expired cookie clears it and returns an anonymous
bootstrap; protected app routes instead return 401 SESSION_REQUIRED/SESSION_EXPIRED.
Expiry responses do not echo whether a foreign account exists.

Rate limits: login attempts at most five per bootstrap and five per direct peer
address per rolling 60 seconds; global at most 30/minute. Use bounded in-memory
counters; forwarded client IP is not trusted by default. Reject with 429 and
Retry-After; limits do not consume or reveal another user's pairing code. No
password reset, signup, refresh bearer or account provisioning endpoint exists.

## 7. Owner checks and bypass prevention

Session middleware is a new trusted authentication adapter, not a second consent
engine. It constructs OwnerContext from its stored principal; A's services still
perform `_owned_task`, `_owner_operation`, catalog ownership, exact consent and
workflow history checks. Read projections always query by that owner and verify
task membership. Foreign references return generic 404 before private data.

Only enumerated application handlers may call fixed services with typed values.
There is no `/proxy`, arbitrary path/URL/method, SQL filter, downstream headers,
tool JSON, credential issuance or protected execution API. New read-only owner
operation/catalog/timeline projections require implementation review; they are
not obtained by removing task authentication from existing gateway routes.

Keep owner/provider/DB credentials out of the React build environment and B
planning context. Disable body/header tracing for pairing/session/approval data.
SameSite/CSRF do not defend a compromised same-origin application against XSS;
React renders untrusted text without HTML interpretation, with a restrictive CSP
as specified in [05_FRONTEND_SECURITY_BOUNDARIES.md](05_FRONTEND_SECURITY_BOUNDARIES.md).

## 8. Implementation acceptance

Step 44B must test mode-disabled startup, exact loopback/Host/Origin restrictions,
pairing TTL/single-use/races/rate limits, fixation rotation, cookie flags, CSRF on
all POSTs, expiry/logout/restart invalidation, credential-role substitution,
owner/task/approval isolation, and absence of credentials in responses/logs.
No production authentication choice is left implicit: remote/shared use stays
disabled until separately designed. This draft removes design ambiguity for a
local demo, but does not close Step 43 F01 until implemented and tested.
