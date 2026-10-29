# Phase 5D-R1 — Cloudflare Pages Direct Upload

Rights/MIT/original asset redistribution are confirmed. **Deployment remains subject to separate explicit approval. Public URL: NOT CREATED.**

## Isolated approved-content artifact

The complete staged public-demo build contains exactly 13 static files. No backend imports, private API client, local pairing/session, credentials, database, proxy, function, inference, email or protected execution is present. State is deterministic synthetic browser memory, with a persistent public synthetic banner, separate approval/continuation and SAFE_STOPPED / NOT_EXECUTED.

```text
404.html
THIRD_PARTY_NOTICES.txt
_headers
artifact-manifest.json
assets/app.js
assets/dom.js
assets/rail.js
assets/state.js
fonts/inter.woff2
fonts/space-grotesk.woff2
ghost.svg
index.html
styles.css
```

Build size: **132,287 bytes**. Artifact-manifest SHA-256: `e8a9068a46cb23cb8c00f164281c07c667b095e7bdbe9b387042ddc8288970a7`. The manifest hashes the other 12 files. Only the notices/manifest differ from Phase 5B/C because the complete approved MIT text is now packaged; application JS, styles, fonts and logo are unchanged. Full original font OFL notices remain in the same file. The two font binaries retain their third-party license and are not relicensed under project MIT.

The final 13-file distribution is retained separately in the sibling `Ghost_Protocol_Public_Demo_5D_R1_STATIC_REVIEW`; it is not copied into Git source staging. Source dependencies/build caches are not public upload assets.

## Exact future upload procedure — not executed

1. Obtain separate deployment authorization identifying the Cloudflare account/project and the exact reviewed artifact. Do not re-request the settled team licensing/asset approval.
2. If rebuilding, use Node 24.16.0/npm 11.13.0, `npm ci`, `npm run typecheck`, `npm run lint`, `npm test`, `npm run build`, `npm run scan`, `npm run test:e2e` in `public-demo/`. Approve any resulting byte/hash change before upload.
3. In Cloudflare dashboard choose **Workers & Pages → create a Pages application → Direct Upload / Upload assets** (current UI labels may vary). Select the authorized project name.
4. Upload only the 13 reviewed files/folders from the static artifact root, with `index.html` at the public document root. Do not upload the repository or an enclosing source directory.
5. There is no cloud build, framework adapter, runtime environment variable, Worker/Pages Function, private backend URL or privileged proxy. Do not enable analytics or injected scripts that would weaken CSP.
6. Record the actual returned HTTPS URL only after the post-deployment checks below pass. No speculative public URL is supplied here.

Cloudflare [Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/) accepts prebuilt static assets. It cannot later be converted to Git integration within that same project; a separate Git-integrated project is needed for automatic builds. The output `_headers` is parsed as configuration and is not served as an ordinary asset, per the [official header documentation](https://developers.cloudflare.com/pages/configuration/headers/).

## Routes and HTTP policy

Root and fragment links: `/`, `/#overview`, `/#workspace`, `/#approvals`, `/#operations`, `/#audit`, `/#documents`, `/#about`. No SPA rewrite or server-side framework is needed. Unknown real paths including `/workspace/`, `/api/app/v1/session`, `/.env` and `/src/app.ts` must remain 404. Serve at the domain root with correct JS/CSS/WOFF2/SVG MIME types.

```text
Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self'; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; worker-src 'none'; manifest-src 'none'
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: no-referrer
Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=()
Strict-Transport-Security: max-age=31536000
Cache-Control: no-cache
```

The actual HTTP headers enforce framing restrictions; meta CSP is only a fallback. HSTS/provider behavior must be checked after authorized HTTPS hosting. Provider infrastructure access logs/account terms are distinct from the app's no-storage/no-analytics behavior.

## Post-deployment verification — not performed now

```powershell
$approvedPublicUrl = Read-Host 'Actual deployed HTTPS URL'
$publicUri = [uri]$approvedPublicUrl
if ($publicUri.Scheme -ne 'https' -or $publicUri.UserInfo -ne '' -or $publicUri.Query -ne '' -or $publicUri.Fragment -ne '' -or $publicUri.AbsolutePath -ne '/') { throw 'Use the verified public HTTPS origin without credentials/query/fragment/subpath.' }
$approvedPublicUrl = $publicUri.GetLeftPart([UriPartial]::Authority)
curl.exe --head "$approvedPublicUrl/"
curl.exe --head "$approvedPublicUrl/assets/app.js"
curl.exe --head "$approvedPublicUrl/styles.css"
curl.exe --head "$approvedPublicUrl/fonts/inter.woff2"
curl.exe --head "$approvedPublicUrl/api/app/v1/session"
curl.exe --head "$approvedPublicUrl/.env"
```

- [ ] Valid intended HTTPS certificate/origin; no unexpected redirect or Set-Cookie.
- [ ] CSP, framing/nosniff/referrer/permissions/HSTS policy present; no injected script or external connection destination.
- [ ] Only same-origin static assets in normal network activity; API/private/source paths remain 404 and never reach trusted services.
- [ ] All fragment routes cold-load/refresh; reset/reload clears synthetic task/events/storage.
- [ ] Full synthetic create/plan/authorize/review/approve-or-reject/explicit-continue/SAFE_STOPPED/audit flow works; revoke/expiry/cancel/UNKNOWN remain labelled and cannot retry external execution.
- [ ] 390/768/1440/1920px layouts, keyboard dialogs/focus, reduced motion and touch targets pass on the actual host.
- [ ] Full MIT/font notices are accessible and uploaded bytes match the reviewed artifact.
- [ ] Live AI inference through the public demo is never claimed; native OpenShell remains unverified and no real email/read occurs.

No account provisioning, upload, deploy, inference, email, sandbox or video occurs during preparation.
