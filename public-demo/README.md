# Ghost Protocol public interactive demo

**PUBLIC INTERACTIVE DEMO — SYNTHETIC DATA**

A separate static TypeScript application. No private frontend imports, backend, pairing, session, database, provider, email or protected execution is attached. One task and its synthetic records live only in browser memory. Refresh/reset clears them.

## Local review

Use Node 24.16.0 and npm 11.13.0. From this directory:

```powershell
npm ci
npm run typecheck
npm run lint
npm test
npm run build
npm run scan
npx playwright install chromium
npm run test:e2e
npm run preview
```

Open **http://127.0.0.1:4310**. Stop preview with Ctrl+C. No `.env` is needed or allowed. Do not start the private application. Browser tests manage their own static preview and require port 4310 free.

1. Create a sample task (document, synthetic email, or denied original-sharing example).
2. Generate a fixed simulated plan.
3. Inspect scope in Approval Center; deliberately approve/reject/revoke.
4. An approval leaves the workflow paused. Return to the task workspace to continue explicitly.
5. Observe **SAFE_STOPPED / NOT_EXECUTED**, then inspect synthetic operation/audit records.
6. Use labelled expiry/UNKNOWN examples or cancel before continuation. Reset before another scenario.

Routes use URL fragments: `/#overview`, `/#workspace`, `/#approvals`, `/#operations`, `/#audit`, `/#documents`, `/#about`. They all load `index.html`; no server-side routing or SPA rewrite is needed. Serve over HTTP(S), not `file://`, for ES modules.

## Build isolation

`npm run build` type-checks and scans four allowed runtime modules, compiles them without runtime framework dependencies, copies only approved static files and two local fonts, creates security headers/notices, and verifies the 13-file hash manifest. Private imports/configuration, environment files, network/storage/unsafe-HTML APIs and unexpected output files fail validation. Unknown output files are not silently deleted; inspect them before rebuilding.

`dist/` is the entire static hosting artifact. `scripts/preview.mjs` is a loopback QA file server, **not deployed code**. No API proxy, serverless function, middleware or database is included.

Screenshots are saved outside source at `%TEMP%/ghost-phase5b/screenshots/` on Windows (or the OS temporary directory on another host). Only synthetic states are captured; no video/traces are recorded. See [implementation report](../docs/release/PHASE5B_PUBLIC_DEMO_IMPLEMENTATION.md), [security review](../docs/release/PHASE5B_SECURITY_REVIEW.md) and [deployment guide](../docs/release/PHASE5B_DEPLOYMENT_GUIDE.md).

## License / hosting status

Inter and Space Grotesk retain their SIL OFL licenses. Complete notices are copied from pinned Fontsource packages into `dist/THIRD_PARTY_NOTICES.txt`. Build/test dependencies are not shipped in the static artifact. The Ghost brand SVG matches the existing project mark; nav paths are local SVG code. No stock imagery, private screenshot, model weight or OpenShell binary is included.

Original team-owned demo code and approved original team assets are covered by the local [MIT LICENSE](LICENSE): **Copyright (c) 2026 Ghost Protocol Contributors**. Explicit Phase 5D-R1 team authorization resolves the earlier rights holds. Fonts and other third-party materials retain their own licenses; this grant does not relicense them. The built notices include the complete project MIT text and both font OFL texts. See [current release review](../docs/release/PHASE5D_R1_FINAL_RELEASE_APPROVAL.md). **Public URL: NOT CREATED.** Deployment and Git publication still require separate explicit approval; build/tests perform neither.
