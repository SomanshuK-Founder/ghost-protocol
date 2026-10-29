# Phase 5B — static hosting preparation

**Public URL: NOT CREATED. No deployment is authorized or performed by this guide.**

The deployable product is only the isolated `public-demo/` synthetic application. Never connect the private local FastAPI listener, expose pairing, use a tunnel, add an API proxy or deploy the repository root as an application.

## Reproducible build and local inspection

Qualified build environment: Windows x64, Node **24.16.0**, npm **11.13.0**. No Python, backend, database, provider account or environment file is needed. From the repository root:

```powershell
Push-Location public-demo
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

Open **http://127.0.0.1:4310** for local review. Ctrl+C stops preview; `Pop-Location` returns to the root. Browser tests start their own preview and refuse an occupied port, so stop manual preview before running them. This URL is loopback QA, not a public deployment.

Fresh `npm ci`, build, scan and all tests were actually executed in a separate source-only copy. Its final artifact manifest matches the working-copy artifact byte for byte. `npm ci` installs 115 dependencies (116 packages audited including the root); npm audit reports zero known vulnerabilities at audit time. The existing-compatible ESLint 9.39.5 emits a deprecation/unsupported warning; a major tool upgrade is deferred rather than silently changing the accepted toolchain.

## Exact hosting inputs

| Setting | Value |
| --- | --- |
| Project/source root | `public-demo` only |
| Framework preset | Other / static; no Next.js adapter or SSR |
| Install command | `npm ci` |
| Build command | `npm run build` |
| Publish/output directory | `public-demo/dist` from repository root, or `dist` from the demo root |
| Runtime environment variables | **None**. Do not add provider, SMTP, database, session or backend URL values. |
| Build runtime | Reviewed Node 24 toolchain; `.node-version` pins 24.16.0. Provider availability/build behavior must be verified during deployment review. |
| Functions / workers / proxy / middleware | None |
| Server entry point | None; `scripts/preview.mjs` is local QA only and is not deployed |
| Artifact | 13 named static files, 131,153 bytes in the validated build; no source maps, logs, screenshots or dependencies |

The release artifact contains `index.html`, `404.html`, `styles.css`, `ghost.svg`, two WOFF2 fonts, four ES modules, `_headers`, `THIRD_PARTY_NOTICES.txt` and `artifact-manifest.json`. The manifest hashes the other 12 files. `npm run scan` rejects missing, extra, changed or symlinked output and checks isolated runtime capabilities. Inspect unexpected files; do not delete unknown resources automatically.

## Routes

All user-facing navigation is fragment routing from the document root:

`/`, `/#overview`, `/#workspace`, `/#approvals`, `/#operations`, `/#audit`, `/#documents`, `/#about`.

Fragments never reach a server. No SPA catch-all rewrite is needed. Unknown HTTP paths should return 404; `/api/...`, `/.env`, `/src/...` and private paths must not resolve. `404.html` intentionally prevents a generic unknown-path fallback. Serve with correct HTML/JS/CSS/SVG/WOFF2 MIME types over HTTP(S), never `file://`. No API operations are exposed.

## Hosting alternatives, after separate approval

**Shortest route: Cloudflare Pages static artifact upload.** Review the existing local `dist/` and notices, then separately authorize uploading only that artifact. This does not require publishing the private repository or configuring a backend. A future Git-based Pages project must use root `public-demo`, the commands above and output `dist`. The generated `_headers` belongs in that output directory and applies to static assets; no Pages Functions are used. See Cloudflare's official [static HTML guide](https://developers.cloudflare.com/pages/framework-guides/deploy-anything/) and [header configuration](https://developers.cloudflare.com/pages/configuration/headers/).

**Vercel alternative:** a separately reviewed source project with root `public-demo`, static/Other preset and the generated `public-demo/vercel.json`. It declares `framework: null`, `npm ci`, `npm run build`, `dist` and all response headers. See the official [vercel.json configuration](https://vercel.com/docs/project-configuration/vercel-json). The file is generated deterministically from `scripts/policy.mjs`; do not point the project at the accepted private frontend.

Provider dashboards, build images, account access and actual deployed responses have not been tested. Disable preview-toolbar/script injection, analytics and integrations that require external scripts or network access; do not weaken CSP to accommodate them. A provider may retain infrastructure access logs; application-level no-storage/no-analytics claims are not a promise about provider retention. Rights-holder/license approval from Phase 5A still applies.

## Security headers

`scripts/policy.mjs` is the shared source for the preview server, Cloudflare `_headers` and Vercel configuration:

```text
Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self'; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; worker-src 'none'; manifest-src 'none'
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: no-referrer
Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=()
Strict-Transport-Security: max-age=31536000
Cache-Control: no-cache
```

The HTML meta CSP also blocks connections/scripts/styles as a fallback. Framing protection requires the actual HTTP headers; meta does not enforce `frame-ancestors`. HSTS is meaningful only on the eventual HTTPS site. Never add `unsafe-inline`, `unsafe-eval`, backend connect destinations or privileged API routes.

## Deployment-review / eventual hosted acceptance

1. Approve the exact artifact, ownership/license/notices, provider/account, visibility and hosting plan. Obtain explicit deployment authorization; none is implied by a passing local build.
2. Upload/deploy only the reviewed static artifact/source project. Never copy `.git`, `.env`, the private frontend/backend, runtime databases, logs, tests or screenshots into the publish directory.
3. Inspect actual HTTPS responses for CSP, framing policy, MIME types, absence of Set-Cookie, API-path 404s and intended caching. Confirm the provider has not injected scripts.
4. Repeat Chromium workflow and 390/768/1440/1920px checks against the actual URL. Inspect network requests: only same-origin static assets, no API/auth/inference/SMTP/analytics traffic.
5. Verify synthetic banner, separate approval/continuation, denial/revocation/expiry/cancel/UNKNOWN, empty storage, reset/reload, keyboard focus and notices. Only then record the public URL as created and accepted.

No deployment command was run, account provisioned, repository pushed or URL created in Phase 5B.
