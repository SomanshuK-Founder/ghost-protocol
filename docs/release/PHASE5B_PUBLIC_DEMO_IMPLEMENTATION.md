# Phase 5B — public interactive demo implementation

**PUBLIC_DEMO_READY_FOR_DEPLOYMENT_REVIEW**

**Public URL: NOT CREATED.** No deployment, commit, push, tag, live inference, email, OpenShell or video work occurred.

## Completed experience

Implemented an independently built static app under `public-demo/`. It preserves the existing graphite Control Room, iris/cyan tokens, Inter/Space Grotesk typography, 248px desktop navigation, focused task card, human checkpoint and responsive Decision Rail. It uses native TypeScript/DOM components instead of importing private React/session/API features or introducing another framework. No private application source changed.

| Screen / interaction | Actual synthetic behavior |
| --- | --- |
| Overview | Empty-start introduction; after creation, focused task, derived pending count and state-backed Decision Rail |
| Task creation | Validated sample title, fixed document/email/denied-original scenario, explicit memory-only data note |
| Workspace | Deliberate simulated planning; exact authorization state; explicit separate continuation; cancellation and labelled alternate-state examples |
| Approval Center | Exact task/operation/approval/resource/action/purpose/recipient inspection; confirm approve/reject/revoke; unavailable actions disabled |
| Decision Rail | Derived solely from current synthetic state/events, active/blocked/denied/uncertain/safe states, responsive vertical rail, inspectors only for available synthetic events |
| Operation records | NOT_EXECUTED / UNKNOWN_EXAMPLE, NONE external effect and explicit SYNTHETIC_BROWSER_DEMO provenance |
| Audit explorer | Real events produced by the in-browser state machine, chronological step numbers, category filtering and metadata inspection; no backend timestamps or durable-event claims |
| Document catalog | Fixed synthetic metadata only; no document contents, paths or real ownership claims |
| About / boundaries | Separate private application integration, historical isolated Nemotron validation, no public live inference, native OpenShell unverified, no protected read or email |
| Reset / reload | Clears the single in-memory task and all event references; no persistence or real backend modification |

## Transition contract

`EMPTY → CREATED → PENDING → APPROVED → SAFE_STOPPED` requires separate user actions for create, plan, approval and continuation. A fixed original-sharing scenario takes `CREATED → DENIED` when planned. PENDING can reject/revoke/expire/cancel; APPROVED can revoke/expire/cancel or enter a labelled UNKNOWN example. These terminal states cannot continue or retry. Reset returns to EMPTY. There is no real execution transition.

The 10-minute review window is explicitly synthetic and advances only via Simulate expiry. Step numbers describe event order, not a wall clock. One active task is supported; reset before another scenario. Approval grants no real permission, and SAFE_STOPPED never means executed.

## Files created

- `public-demo/package.json`, exact `package-lock.json`, `.node-version`, `.gitignore`, strict `tsconfig.json`, ESLint/Playwright configuration and README.
- `src/state.ts`, `dom.ts`, `rail.ts`, `app.ts`: state model, safe native UI primitives, shared rail/record inspector and seven screens.
- `static/index.html`, `styles.css`, `ghost.svg`: isolated entry, existing design tokens and approved project identity.
- `scripts/build.mjs`, `guard.mjs`, `verify.mjs`, `policy.mjs`, `preview.mjs`: deterministic build, import/capability gate, fixed artifact/hash checks, shared headers and loopback-only QA server.
- Three unit test files and `tests/browser/demo.spec.mjs`; generated reviewable `vercel.json`.
- This report, [deployment guide](PHASE5B_DEPLOYMENT_GUIDE.md) and [security review](PHASE5B_SECURITY_REVIEW.md).

Generated `dist/`, Node dependencies and test output are ignored. Existing root/frontend `.gitignore`, manifests, code, fixtures, contracts, Phase 5A allowlist and prior evidence remain unchanged. A SHA-256 baseline of **1,441 existing files** confirms zero changed/deleted existing files.

## Final verification

| Check | Result |
| --- | --- |
| Demo TypeScript / ESLint | Pass |
| State / isolation / design tests | 38 passed: 15 + 21 + 2 |
| Production build / artifact scan | Pass; 13 files, 131,153 bytes, no runtime framework packages |
| Chromium browser suite | 12 passed; includes every main screen at four requested widths |
| Fresh install | Actual source-only `npm ci`: 115 dependencies installed, no copied node_modules; final type/lint/38 unit/12 browser/build/scan pass |
| Deterministic output | Fresh and working build artifact manifests identical; no timestamp/environment injection |
| Browser network/storage | Normal flows request only same-origin static assets; no API/auth/inference/external calls, empty cookies/localStorage/sessionStorage. Intentional CSP probe blocked before dispatch. |
| Secret scan | Gitleaks 8.30.1: final runtime source and static artifact both zero findings, exit 0 |
| npm advisory scan | 0 known vulnerabilities; ESLint support warning documented |
| Private frontend regressions | TypeScript, ESLint and 38 unit tests pass; private source unchanged |

Artifact-manifest SHA-256: `9713cb92d88f2f564f6e0b6acf3f2568799fce7fabc73b568f7f4fe4d23e2d45`. The manifest hashes the other 12 files; deployment review must recheck it after rebuilding/changing anything.

## Browser and accessibility evidence

Browser plugin unavailable; used the installed Playwright Chromium workflow against **http://127.0.0.1:4310**. Verified page title/identity, meaningful rendering, no framework overlay, no app console warnings/errors, action outcomes and actual screenshots. There is no fake backend or live inference behind this URL.

Complete create → plan → inspect scope → approve → remain paused → explicitly continue → SAFE_STOPPED/NOT_EXECUTED → audit/operation inspection → reset/reload passed at **390, 768, 1440 and 1920px**, height 1000px. Tests check no horizontal overflow at every screenshot and dialog bounds within the viewport. Tablet/mobile navigation is a labelled keyboard-accessible drawer.

Keyboard checks cover skip-to-content, labelled form inputs, initial dialog focus, explicit Tab/Shift+Tab containment, Escape/cancel, trigger restoration and route-heading focus. Native semantic controls, live announcements, status text alongside color, minimum 12px labels, 44px targets and reduced-motion rules are present. All text/status tokens pass 4.5:1 contrast against canvas/panel/raised surfaces. Actual assistive-technology certification and physical-device testing are not claimed.

QA fixed a real dialog-focus containment issue. Visual review also corrected an offscreen skip-link artifact in full-page captures and raised tiny labels to the existing design minimum. Final screenshots were recaptured and inspected; no outstanding P0/P1 layout or interaction defect was found.

## Screenshot index

The browser suite saves **42 PNGs** outside the repository in `%TEMP%/ghost-phase5b/screenshots/` on Windows (OS temp directory elsewhere). Open that path in Windows File Explorer; files can also be opened from the editor file picker. Captures contain only this demo's synthetic data, not private application records or pairing values. They are excluded from the static build by its strict allowlist.

For each width **390 / 768 / 1440 / 1920**:

| Filename pattern | Demonstrates |
| --- | --- |
| `overview-{width}.png` | Entry composition, synthetic banner, responsive navigation |
| `task-creation-{width}.png` | Labelled scenario/title form and dialog bounds |
| `planning-{width}.png` | Simulated plan, pending authorization, state-derived rail |
| `pending-approval-{width}.png` | Exact synthetic review context |
| `approval-dialog-{width}.png` | Confirmation, scope, focus ring, separate approval semantics |
| `safe-stopped-{width}.png` | SAFE_STOPPED with operation NOT_EXECUTED and no external effect |
| `audit-{width}.png` | Chronological synthetic events and category filtering |
| `operations-{width}.png` | Operation status/provenance and metadata |
| `documents-{width}.png` | Metadata-only catalog and restricted-resource labels |
| `about-{width}.png` | Capability status, simulation and security limitations |

`documents.png` and `about.png` add the suite's default 1280px browser viewport. All main screens also have the four requested widths above. Screenshot files can be regenerated with `npm run test:e2e`.

## Remaining gates and next action

No unresolved P0/P1 technical defect within the static synthetic scope. The public app is demonstrative, not a real multi-user service or live AI product. Existing project ownership/license approval remains required; font notices are packaged, and no project license is silently applied. Firefox/WebKit, native screen readers, Linux/macOS clean install and actual provider hosting remain unverified. Backend/Ruff suites were not rerun because no Python/backend code changed; Phase 5A acceptance remains separate evidence.

Review the exact `public-demo/dist/`, notices and [hosting plan](PHASE5B_DEPLOYMENT_GUIDE.md). Then authorize the provider and deployment separately. Do not expose the private pairing system. Stop here for deployment review; **public URL remains NOT CREATED**.
