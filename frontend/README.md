# Ghost Protocol control room

Next.js App Router, strict TypeScript and Tailwind static export. Browser requests use the accepted `ghost-app-v1` contract and same-origin HttpOnly sessions/CSRF. No API proxy, trusted browser bearer, external execution or live inference is configured.

## Install and start

Use the [root setup instructions](../README.md) to create both hash-locked Python environments first. With Node 24.16.0 and npm 11.13.0, from this directory:

```powershell
npm ci
npm run generate:api
npm run typecheck
npm run lint
npm test
npm run build
```

The connected UI runs through `scripts/serve.py` around the unchanged public ASGI app at **http://127.0.0.1:3000**. Initialize/verify a fresh `ghost-offline-*` directory and run the documented private interactive `--pair` launcher from the root README. The one-use operator code expires after 120 seconds. Pairing is disabled without that flag; no browser API issues codes.

`npm run dev` binds `127.0.0.1:3001` for styling only. Connected acceptance uses the production static build and single loopback ASGI listener. Do not add CORS, a generic proxy, public binding or a tunnel.

## Screens and architecture

- `src/app/`: overview; task list, creation and workspace; approval center/detail; document metadata; operation history/detail; audit explorer; session/capability settings; local help.
- `src/components/`: responsive shell, labelled native dialogs, session boundary, Decision Rail, owner-safe metadata, status and feedback primitives.
- `src/features/`: route-level workflows using shared components and the typed client.
- `src/lib/api/schema.d.ts`: generated from the accepted [OpenAPI JSON](../docs/frontend-handoff/generated/ghost-app-v1.openapi.json). The generator removes only redundant boolean discriminator metadata in memory to preserve boolean constants; canonical JSON is unchanged.
- `src/lib/api/client.ts`: operation-derived types, same-origin/no-store requests, bounded reads, in-memory CSRF, safe errors and no mutation retry.
- [API_OPERATIONS.md](API_OPERATIONS.md): all 19 browser operation IDs, parameters, body/response schemas and security mappings.

Task and operation detail links use real query-string references to support static export. Lists and audit/catalog cursors are owner-scoped. Operation pages cover only the bounded returned set; the accepted endpoint has no cursor. Approval queue/dashboard counts cover loaded task pages.

Approval is scoped permission, never dispatch. Continuation is explicit and ends at **SAFE_STOPPED** (`RESUMED`); it does not read a protected document or submit an email. UNKNOWN/reconciliation prevents blind resend. Session-memory command locks clear on expiry/logout/full reload; durable backend authority/idempotency remains authoritative.

## Design and accessibility

The approved graphite Control Room uses locally bundled Inter/Space Grotesk, iris actions, cyan evidence and labelled state colors. A 248px desktop sidebar becomes a tablet rail and labelled mobile drawer; the six-stage Decision Rail becomes vertical on mobile. Keyboard focus, modal restoration/containment, reduced motion, 44px actions, token contrast and reference wrapping are tested. Curated [desktop/mobile screenshots](../README.md#frontend-screenshots) contain synthetic local evidence only.

## Browser checks

```powershell
npx playwright install chromium firefox webkit
npx playwright test --browser=all
npm audit
```

The suite uses disposable real SQLite application state and private pipes for pairing. It refuses an occupied port 3000. Video, traces and request-body logging are off. To preserve earlier temporary captures, release verification sets TEMP/TMP to a separate task directory before starting Playwright. The tests write only temporary image artifacts, not publication assets.

Chromium and Firefox qualify the tested local cookie behavior. Windows Playwright WebKit is UI/protocol coverage only: its observed Strict-cookie limitation is explicitly annotated, while real wire policy and backend CSRF/Origin/Host checks remain active. This is not Safari/macOS security acceptance.

See [dependency reproducibility](../docs/release/DEPENDENCY_REPRODUCIBILITY.md), [release audit](../docs/release/PHASE5A_RELEASE_AUDIT.md), [third-party attribution](../docs/release/THIRD_PARTY_ATTRIBUTION.md) and [public demo decision](../docs/release/PUBLIC_DEMO_DECISION.md). Historical phase reports/images remain private acceptance evidence outside the curated publication manifest. No public preview mode is implemented by this frontend.
