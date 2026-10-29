# Phase 5D-R1 — complete publication preparation

**GITHUB_READY_FOR_EXPLICIT_PUBLICATION_APPROVAL**

**CLOUDFLARE_READY_FOR_EXPLICIT_DEPLOYMENT_APPROVAL**

## Explicit rights approval

The project owner explicitly confirmed that Members A, B and C agreed to MIT licensing of their original Ghost Protocol code, publication of original team logos/icons/screenshots/visual assets, and public-demo redistribution of those original assets. The approved collective notice is:

**Copyright (c) 2026 Ghost Protocol Contributors**

This is recorded human authorization, not an inference from project membership. It resolves the prior Phase 5D rights holds; no repeated consent request is needed for the same scope. It does not approve a commit, push, tag or deployment, and it does not relicense third-party material.

## Operative license and third-party scope

Root [LICENSE](../../LICENSE) and [public-demo/LICENSE](../../public-demo/LICENSE) contain identical, complete standard MIT text with the exact approved notice. Original team-owned code/docs and approved team-owned visual assets are covered. The public demo has its own license input so its isolated build needs no parent repository access. Its packaged notices include the complete MIT text and both font OFL texts.

Framework MIT notices, Lucide ISC and both font OFL notices remain unchanged. The [attribution inventory](THIRD_PARTY_ATTRIBUTION.md) records the scope; dependencies, font binaries, provider/model terms and sponsor marks retain their own rights. No stock artwork, model weights, native OpenShell binary or installed dependency is added to the source snapshot. The earlier MIT draft remains dated, non-operative evidence.

## Existing staging reused

The sibling `Ghost_Protocol_Publication_Staging_5D_REVIEW_ONLY` is reused in place. Its fresh `main` remains unborn, with zero commits, no index entries, tags, remote, inherited objects, template hooks or local author identity. Original development history remains at `feat/member-b-agent`, HEAD `75daa6ba02f5d83a25b3bb6af80e3c6ae34697ad`.

All six held assets are restored byte for byte. Explicit additions to the 383-file Phase 5D staging set are six restored assets, root LICENSE, public-demo/LICENSE and the new R1 report: **392 source files including the staging manifest**, excluding Git metadata. No file is silently removed or added.

The current machine allowlist is `docs/release/phase5d-staging-files.json`; the default publication helper now selects it. The older Phase 5C JSON remains unchanged historical evidence. README/license/attribution/release instructions and the public notice generator have declared hash changes. Backend authorization, application/runtime code, migrations, fixtures and UI components are unchanged.

## Six-asset disposition

| Asset | Disposition / evidence |
| --- | --- |
| `docs/assets/frontend/dashboard-desktop.png` | INCLUDED; identical Phase 3 synthetic dashboard capture, visually inspected |
| `docs/assets/frontend/dashboard-mobile.png` | INCLUDED; identical Phase 3 synthetic mobile capture, visually inspected |
| `docs/assets/frontend/approval-mobile.png` | INCLUDED; identical Phase 3 synthetic approval dialog capture, visually inspected |
| `docs/assets/frontend/safe-stopped-desktop.png` | INCLUDED; identical Phase 3 synthetic SAFE_STOPPED capture, visually inspected |
| `frontend/src/app/icon.svg` | INCLUDED; existing project-generated mark, inspected SVG paths only, no script/external content |
| `public-demo/static/ghost.svg` | INCLUDED; byte-identical counterpart of the project mark |

Ownership is established by the explicit owner confirmation and existing project provenance, not by a hash alone. The screenshots are original team UI captures incorporating licensed Inter/Space Grotesk and Lucide renderings. Their third-party notices/terms remain in force; they are not claimed as exclusively team-authored font/icon artwork. No externally sourced stock image or unlicensed embedded artwork was identified. No pairing value, credential, private path or real document content is visible.

## Verification

- Actual clean `npm ci` performed inside the reused staging directory: frontend 386 installed packages / 387 audited, public demo 115 / 116. Both lockfiles remain unchanged.
- Staged frontend: strict TypeScript, ESLint, 38 unit tests and production static export pass.
- Staged public demo: strict TypeScript, ESLint, 38 unit/state/isolation/design tests, production build, strict artifact scan and 12 Chromium tests pass (13.9 seconds). All main screens cover 390/768/1440/1920px; synthetic labels, reset/reload, keyboard controls, reject/revoke/expiry/cancel/UNKNOWN and separate approval/continuation are exercised.
- Staged publication helper: 6 tests pass; staged static host: 12 tests pass. **106 tests passed total**, no focused test skipped.
- Staged OpenAPI validates 20 operations / 44 schemas / 282 references. No live API/wire-case validation is claimed.
- Focused staged Ruff: 5 Python files pass lint and format checks.
- Both previously qualified isolated Python environments pass `uv pip check` (3.11.18 / 55 distributions and 3.14.10 / 34). Staged manifests/locks match the qualified inputs; no new backend installation or full 741/859 backend-suite rerun is claimed.
- npm audit reports 0 known vulnerabilities for 466 frontend / 115 demo dependency records. Existing ESLint support warning and the Windows-only qualification/UNIX pytest advisory remain documented.
- Seven third-party notice copies match the freshly installed package license files; complete project MIT and both font OFL texts are packaged. Both unchanged font binaries match the licensed package files.
- Source secret scan: only two existing fixed synthetic idempotency UUID matches, not credentials; artifact scan: zero findings. No personal operator path, actual .env, database/checkpoint, private certificate, raw sensitive evidence or unrelated binary is included.
- New Git history remains empty on main: zero commits/index entries/remotes/tags; original history is unchanged. Current source inventory is exactly 392 non-Git files.
- Actual hosted HTTPS/provider response behavior, physical devices/native screen readers, production MySQL/OpenShell/live inference and other-platform fresh installation are not accepted by this local preparation. No infrastructure or video work occurs.

Build dependencies and generated QA output are kept out of the final source inventory. Only newly created, verified QA directories may be moved to private temporary storage after testing; no unknown resource is deleted. The 13-file public static artifact is separately retained for deployment review.

## Current handoff

See [R1 final release review](PHASE5D_R1_FINAL_RELEASE_APPROVAL.md), [source reconciliation](PHASE5D_STAGING_MANIFEST.md), [GitHub commands](PHASE5D_GITHUB_COMMANDS.md) and [Cloudflare instructions](PHASE5D_CLOUDFLARE_DEPLOYMENT.md). Rights are settled for the approved original-team scope. Future public Git author/account/visibility and hosting account/project are operational choices to approve with the corresponding explicit publication/deployment instruction; they are not new copyright prerequisites.

No commit, push, tag, deployment, live inference, real email, OpenShell or video is performed. Public URL: **NOT CREATED**.
