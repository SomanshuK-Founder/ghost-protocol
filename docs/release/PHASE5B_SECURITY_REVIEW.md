# Phase 5B — public synthetic demo security review

Date: 2026-10-29. **PUBLIC_DEMO_READY_FOR_DEPLOYMENT_REVIEW** within the isolated synthetic static scope. **Public URL: NOT CREATED.** This is not a production-backend approval or a penetration-test certification.

## Boundary

`public-demo/` has independent manifests, lockfile, compiler, source, static assets and build/test scripts. Runtime consists of four native TypeScript/ES-module files. It does not import the private frontend, generated API client, backend, fixtures, runtime state or screenshots. There is no server function, proxy, login, local session, provider adapter or execution service.

The accepted frontend/backend and all 1,441 pre-phase tracked/nonignored files are SHA-256 preserved. Existing private authorization, pairing, CSRF, Host/Origin, gateway, migrations and enforcement contracts are not modified or repurposed. All new files are in `public-demo/` or the three Phase 5B release reports. The Phase 5A source publication manifest remains unchanged; a future source release must separately review/add these new files rather than silently treating its old snapshot as complete.

## Controls and evidence

| Surface | Implemented control / actual evidence |
| --- | --- |
| Import boundary | Build accepts exactly four runtime files and imports only between their named relative `.js` modules. External/private imports and dynamic imports fail. Runtime modules have no package dependency. Negative tests exercise private, external and unreviewed imports. |
| Credentials/config | No `.env` is used; any project-root `.env*` fails build. Runtime `process`, environment/private-service markers are rejected. No environment values are substituted into output. No real credential was imported for this demo. |
| Network | Runtime AST rejects fetch/XHR/socket/event-stream/worker/beacon APIs. CSP `connect-src 'none'` independently blocks connections. Normal browser workflows observe only same-origin static GETs. An intentional same-origin synthetic CSP probe is blocked before request routing; no backend/service call is made. |
| Persistence/auth | No cookie/session/pairing or browser storage API. Storage APIs are rejected by the guard. Tests confirm localStorage/sessionStorage are empty and document.cookie is empty throughout the synthetic flow. State resets on reload/reset. |
| HTML/user text | Native DOM creation and text nodes; no raw HTML injection API or inline handlers. Eval/Function constructors are rejected and CSP permits neither unsafe-eval nor unsafe-inline. Browser test renders an HTML-looking title literally without creating an image or executing a handler. |
| State transitions | Pure typed transition function, current-phase preconditions, exact fixed scenario metadata, sequential synthetic event references. Duplicate/invalid actions throw without adding events. Approval and continuation are distinct; no automatic retry, progression or timer. |
| Expiry/UNKNOWN | Explicitly labelled scenario controls. Synthetic time advances only via Simulate expiry. UNKNOWN is an illustrative stop/reconciliation example with no attempted real operation, not a fabricated delivery result. |
| Filesystem/static serving | Browser has no filesystem interface. Local preview reads only a fixed allowlist under `dist`, binds loopback and returns 404 for private/API/source/traversal-like paths and POSTs. This QA server is not deployed. |
| Output | 13-file allowlist and SHA-256 artifact manifest. No .env, backend modules, private logs, screenshots, source maps, database, binaries or Node dependencies enter `dist`. Unexpected files/symlinks/hash mismatches fail verification. |
| CSP/headers | Self-only scripts/styles/fonts/images; no connection, form, object, worker or framing capability. Shared policy generates preview headers, Cloudflare `_headers` and Vercel configuration. Hosted enforcement is a separate acceptance gate. |
| Transparency | Persistent exact public synthetic banner, synthetic record provenance, no-backend explanation and explicit boundaries for separate real local integration, historical live Nemotron probes, unverified native OpenShell and zero real external effects. |

The build guard is a targeted accidental-import/capability gate, not a general proof against malicious source code or every unknown secret format. Reviewed source, strict artifact scope, dependency/secret scans and browser network/CSP testing complement it. Hosting or browser extensions outside this artifact are not certified.

## Verification results

- Public demo TypeScript, ESLint, production build and `npm run scan`: **pass**.
- **38 unit checks pass:** 15 state-machine tests, 21 isolation/negative capability tests and 2 design/contrast tests.
- **12 Chromium tests pass**, including four complete responsive workflows, denial/rejection/revocation, explicit expiry/UNKNOWN, cancellation, literal untrusted text, form validation, cancelled confirmation, actual CSP denial, navigation, reload/reset and static-only 404/method checks.
- Fresh source-only `npm ci` actually executed; same final tests/build/scan pass there. All 13 artifact files match the working build's manifest byte for byte. No dependencies or assets were copied from the original frontend to fake a fresh installation.
- Gitleaks 8.30.1 redacted scans of final runtime source and production artifact: **zero findings, exit 0**. Reports remain in task-owned temporary storage. No new Git history exists to audit because no commit/push/tag occurred; Phase 5A history evidence remains unchanged.
- npm audit: **0 known vulnerabilities across 115 dependencies** at audit time. Known nonblocking tool warning: accepted-compatible ESLint 9.39.5 is deprecated/unsupported; no silent major upgrade.
- Existing private frontend: TypeScript, ESLint and **38 unit tests pass**. Full private browser/backend acceptance was not unnecessarily repeated because its source/contracts/fixtures are unchanged and the demo has no import/transport dependency on them.

## Attribution and release gates

Only Inter/Space Grotesk OFL font binaries from the pinned Fontsource 5.3.0 packages are redistributed as dependencies in the static output. Their complete license texts are included in `THIRD_PARTY_NOTICES.txt`. The logo matches the existing Ghost project mark; navigation SVG paths are locally authored. Build/test dependency license metadata contains 78 MIT, 18 Apache-2.0, 8 ISC, 2 OFL-1.1, 1 Python-2.0, 6 BSD-2-Clause, 1 BSD-3-Clause and 1 BlueOak-1.0.0 entry; none is UNKNOWN. Installed tooling is not part of `dist`.

No root project license is applied. Existing team ownership/license, author metadata and publication decisions still require review. Passing technical acceptance does not grant rights to project or third-party material.

## Findings / limits

- **P0/P1 technical defects: none outstanding in this static-demo scope.**
- Fixed during QA: explicit dialog Tab/Shift+Tab containment; keyboard skip-link behavior; a full-page screenshot artifact from an offscreen skip link; minimum 12px labels and 44px interactive targets. Earlier failing focus tests were rerun successfully.
- P3: ESLint support warning; separate toolchain maintenance review remains appropriate.
- Not certified: Firefox/WebKit public-demo behavior, physical mobile devices, native screen readers, fresh Linux/macOS installation, provider build images, real deployed headers/HTTPS, hosting infrastructure logs, production backend or actual public URL.

Next: review the [deployment guide](PHASE5B_DEPLOYMENT_GUIDE.md), exact static artifact, license/ownership and provider plan, then obtain separate deployment authorization. Never expose private pairing as a shortcut.
