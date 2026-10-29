# Phase 5C — public-demo deployment review

**PUBLIC_DEMO_BLOCKED for public distribution pending rights-holder consent and provider authorization.** Technical deployment preparation passes. **Public URL: NOT CREATED.** This status does not indicate a failed build; it avoids treating unrecorded ownership/branding permission as approved.

## Actual reviewed artifact

- Separate `public-demo/` TypeScript application; four emitted ES modules and no runtime framework dependency.
- Exact `dist/` allowlist: 13 files, 131,153 bytes. Manifest SHA-256: `9713cb92d88f2f564f6e0b6acf3f2568799fce7fabc73b568f7f4fe4d23e2d45`.
- No backend/private frontend imports, generated application API client, pairing, local session, real identity, provider key, SMTP/database configuration, privileged proxy, protected execution or sandbox creation.
- All records are synthetic browser-memory state. Exact public synthetic banner, deterministic planning, approval separate from continuation, SAFE_STOPPED/NOT_EXECUTED, labelled rejection/revocation/expiry/cancellation/UNKNOWN and reset/reload remain intact.
- Two unchanged local font binaries have complete OFL notices. No private image/log/screenshot or model weight enters output. Original project/brand distribution rights remain unconfirmed; MIT approval for the whole repository is a separate decision from permission to host the demo.

## Recommended provider and precise configuration

**Cloudflare Pages Direct Upload is the simplest compatible route:** it accepts prebuilt static assets, so no Git publication, backend, cloud build or server credential is needed for this demo. After separate approval, upload only the reviewed contents of `public-demo/dist/` with `index.html` at the hosting document root. Do not upload the enclosing repository or private app. This recommendation is based on the official [Direct Upload documentation](https://developers.cloudflare.com/pages/get-started/direct-upload/), not a performed deployment. Direct Upload cannot later be converted to Git integration in that same project; choose a separate Git-integrated project if automatic builds are required.

| Setting | Cloudflare Direct Upload | Vercel alternative |
| --- | --- | --- |
| Input | Locally reviewed `public-demo/dist/` only | Separately approved source project rooted at `public-demo` |
| Framework | Static assets, no functions | Other, `framework: null` |
| Install | Local `npm ci` | `npm ci` |
| Build | Local `npm run build` | `npm run build` |
| Output | `public-demo/dist` at repository root | `dist` relative to project root |
| Runtime environment | None | None |
| Toolchain | Local Node 24.16.0/npm 11.13.0 | Reviewed Node 24 target; provider image/patch support still requires hosted acceptance |
| Routes | Root document + hash routes | Same; no SSR or Next adapter |
| API/proxy/functions | None | None |
| Headers | Generated `dist/_headers` | Generated `public-demo/vercel.json` |
| Deployment performed | No | No |

Cloudflare parses `_headers` from static output and does not serve it as an ordinary file; no Pages Functions are used. See its official [headers documentation](https://developers.cloudflare.com/pages/configuration/headers/). Vercel's supported static/Other and header settings are documented in [vercel.json configuration](https://vercel.com/docs/project-configuration/vercel-json). No provider account/project was selected or authenticated in this review.

## Production paths and direct links

Use a domain/document root, not a private backend URL or an assumed subpath mount. Entry references `./assets/app.js`, `./styles.css`, `./ghost.svg` and local font URLs; ES modules import only their sibling modules. No API base URL or secret environment is substituted.

Expected routes: `/`, `/#overview`, `/#workspace`, `/#approvals`, `/#operations`, `/#audit`, `/#documents`, `/#about`. All seven fragment routes passed fresh navigation and refresh in Chromium, with zero page errors. Fragments do not reach a server; no catch-all SPA rewrite is required. `404.html` is supplied. `/workspace/` is intentionally **404**, not an alternative route; API, `.env`, source and traversal-like paths must also remain unavailable. Static JS/CSS/WOFF2 responses have the correct MIME types in the tested preview.

Refresh/reset clears the single tab's synthetic task/events. No account/session or durable database is claimed. The preview server at `127.0.0.1:4310` is a local file allowlist used for QA, not deployed code.

## Required HTTP policy

The actual rebuilt `_headers` and `vercel.json` match `scripts/policy.mjs`:

```text
Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self'; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; worker-src 'none'; manifest-src 'none'
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: no-referrer
Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=()
Strict-Transport-Security: max-age=31536000
Cache-Control: no-cache
```

HTML meta CSP provides a connection/script/style fallback; framing protection requires HTTP headers. The actual CSP probe blocks a synthetic same-origin connection before network routing. Do not add unsafe-inline/eval, external connect destinations, analytics, preview toolbar injection or integrations. HSTS and provider header behavior cannot be certified before actual authorized HTTPS hosting. Provider access-log retention/account terms also need review; app-level no-storage claims do not describe provider infrastructure.

## Current verification

TypeScript, ESLint, build and strict artifact scan pass. Public unit/isolation/design suite: **38 passed**. Chromium: **12 passed**, all main screens at 390/768/1440/1920px, keyboard dialogs, synthetic labels, approved-but-paused state, explicit continuation, denial/revoke/expiry/cancel/UNKNOWN, literal untrusted text, storage/network checks and reset. Additional cold-link/refresh and MIME/404 probe passes. Gitleaks production output: **zero findings**. npm audit: **zero known vulnerabilities in 115 dependencies**; inherited ESLint support warning remains documented.

Private frontend/backend imports and code are unchanged. The public artifact matches the accepted Phase 5B manifest, so no implementation redesign or security contract change is needed. No P0/P1 technical issue found in this static artifact. Rights to distribute/display project code/brand/content are a **P1 release gate**, and deployment remains unauthorized.

## Exact next step

Obtain decisions O8/O9 in [the approval review](PHASE5C_PUBLICATION_APPROVAL.md), review the exact 13 files/notices/provider plan, then separately authorize upload. After that future action, verify real HTTPS headers, API 404s, no Set-Cookie/injected scripts/external calls, direct links and the full workflow against the actual URL. Only then change NOT CREATED to a verified public URL. No deployment command is executed here.
