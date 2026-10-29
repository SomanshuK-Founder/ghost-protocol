# Phase 5C — final publication approval review

Date: 2026-10-29. **REPOSITORY_BLOCKED. PUBLIC_DEMO_BLOCKED.** Technical verification passes, but rights-holder permission/license scope and the history-publication decision are not recorded. These are material release gates, not failing application tests. Neither repository nor demo is approved for public distribution. Public URL: **NOT CREATED**.

## Current Git state and scope

- Branch: `feat/member-b-agent`.
- HEAD: `75daa6ba02f5d83a25b3bb6af80e3c6ae34697ad`.
- 19 locally reachable commits, 711 blobs; no configured remote. No commit, staging, push, tag, remote change or history rewrite performed.
- The working tree is not clean: 11 pre-existing modified tracked files (root ignore file and Member A application/tests), plus untracked application, frontend, release and public-demo work. A clean HEAD does not represent the complete accepted application. No unrelated modifications are reverted or staged.
- Phase 5C changes only README release/discovery links, the active source allowlist and these three review documents. The 1,469-file pre-phase baseline is used to verify that all application code, security contracts, fixtures, earlier reports and prior evidence remain unchanged.

The updated [exact manifest](PHASE5C_EXACT_PUBLICATION_MANIFEST.md) covers the full accepted local application and isolated public demo. It is a **conditional review candidate**, not a claim of ownership, license permission or approval to upload. Earlier Phase 5A/B reports retain their dated verdicts; this review does not silently convert them into publication consent.

## Exact human decisions required

No teammate consent has been supplied in this session. The only Git author name is **Somanshu Kumar**; Git authorship and the machine account name do not establish sole copyright ownership. Member A/Member C legal names or any assignee/employer/entity rights are unknown.

| Decision | Exact information/approval needed | Current status |
| --- | --- | --- |
| O1 — original AI/backend work | Confirm the rights holder for `backend/`, applicable tests/docs and fixtures: Somanshu Kumar or the actual assignee/entity, with any additional authors. | Not confirmed |
| O2 — Member A/imported code | Full legal name(s) or rights-holding entity for `member_a_backend/nvidia backend/`, including imported starting code and subsequent modifications. Confirm origin and permission to publish/license those contributions. | Names and consent not provided |
| O3 — frontend/design/brand/assets | Full rights-holder names for `frontend/`, `public-demo/`, Ghost mark, original design, synthetic fixtures and selected screenshots; identify any employer/contractor/third-party ownership. | Not confirmed |
| O4 — license scope | Approve MIT for original project contributions, or select an alternative. Confirm the exact files covered and any exceptions; dependencies/fonts retain their own terms. | Review-only MIT draft; no operative root LICENSE |
| O5 — copyright notice | Approve `Copyright (c) 2026 [full approved holder names or actual rights-holding entity]`; confirm year(s) and names. Do not substitute an invented team entity or presume “all contributors” constitutes individual consent. | Placeholders unresolved |
| O6 — author/privacy/history | Approve public author/contact metadata and choose a new source-only repository or separately reviewed retained history. Consent to publish a name is distinct from a software license grant. | No decision recorded |
| O7 — source artifact/visibility | Approve the exact allowlist, repository owner/name/visibility, attribution and any future operative LICENSE change. Explicit commit/push authorization remains separate. | Not authorized |
| O8 — public demo rights | Confirm permission to publicly display/distribute the demo code, Ghost branding and synthetic content with retained font notices. This can be a separate hosting permission; adopting MIT for the whole repository is not inherently required to host an owner's own app. | Permission not recorded |
| O9 — hosting | Approve Cloudflare Pages Direct Upload (recommended) or Vercel, account/project ownership, artifact, visibility and deployment. No public action follows merely from selecting a provider. | Not authorized |

Recommended license remains MIT for original work, subject to all relevant rights holders' explicit approval. The [draft](license-proposals/MIT-LICENSE.DRAFT.txt) is deliberately non-operative. The official [MIT terms](https://opensource.org/license/mit) require retaining its copyright/permission notice; they cannot supply missing ownership rights. No root LICENSE was created or activated. A future approved LICENSE changes the exact source snapshot and must be added, hashed and reviewed before publication.

## Third-party and restricted material

The [attribution inventory](THIRD_PARTY_ATTRIBUTION.md) and dependency locks remain authoritative evidence for their reviewed versions. Core framework MIT notices, Lucide ISC and both OFL font notices are retained. The public artifact includes the two unchanged font binaries and their full OFL texts; no npm tooling is shipped in it. Fonts retain their own license, including reserved-name conditions; do not relicense them as project MIT. See the [official OFL text](https://openfontlicense.org/open-font-license-official-text/).

Source-only publication does not redistribute installed Sharp/libvips LGPL binaries or certifi/MPL packages. Any later installed bundle/container/native binary distribution needs review of that exact material and its license obligations. No unknown teammate/copied-code ownership is declared cleared. Sponsor names do not grant logo/trademark/model-weight/service rights. No model weights, OpenShell binary or provider entitlement is included.

Never publish actual `.env`, the old backend ZIP, environments/dependencies/build caches, databases/checkpoints, secrets/keys, raw host/integration logs, uncurated screenshots or `.git`. Historical paths and author metadata remain private unless separately approved. Source files in the allowlist are technically reviewed but **withheld from public distribution until O1–O7 are resolved**; public demo distribution additionally needs O8–O9.

## Fresh security/history result

- Gitleaks 8.30.1 history scan of all local refs: 15 matches, manually re-verified as source SHA-256 checksum entries across six manifest paths; exit 1 means detector findings, not a clean zero-match scan. No confirmed credential.
- Known private ignored operator credential, including common encodings, compared privately against all 711 reachable blobs and the proposed public snapshot; no match. No credential values are logged or copied.
- Full working/ignored scan with archive inspection: 334 matches, no added finding since Phase 5A. Categories: 313 checksum false positives, 11 excluded third-party fixture values, 8 excluded generated Next keys, 2 fixed synthetic test UUID occurrences.
- 21 reachable blobs contain Windows user-path patterns; one Git author identity needs consent. Old history is **not cleared for public upload**, even though no actual credential was found.
- Recommended intended public history is a new source-only repository after approval. It has not been initialized; there are no future public commits to certify. Existing history is not rewritten, copied into the review export or silently approved. If history must be retained, stop and approve a separate privacy/remediation plan.

The scan scope is locally reachable refs and current proposed files; it does not certify unreachable objects, external deleted copies, unfetched refs or every possible unknown encoding. If a credential is later confirmed, stop publication, rotate/revoke it and agree remediation before continuing.

## Verification performed in Phase 5C

| Check | Current result |
| --- | --- |
| Private frontend TypeScript / ESLint / production build | Pass |
| Private frontend unit suite | 38 passed |
| Public demo TypeScript / ESLint / production build / scan | Pass; unchanged 13-file artifact |
| Public demo state/isolation/design tests | 38 passed |
| Public demo Chromium suite | 12 passed, 13.2 seconds; four requested widths and all main screens |
| Additional direct-link probe | 7 cold fragment links + 7 refreshes pass; correct JS/CSS/WOFF2 MIME types; API/.env/non-fragment workspace paths return 404 |
| Static-host tests / publication exporter tests | 12 passed / 6 passed |
| OpenAPI validation | 20 operations, 44 schemas, 282 references; no wire-case rerun claimed |
| Focused Ruff lint / format | Pass, 5 frontend/release Python files |
| npm audit | 0 known vulnerabilities for 466 private / 115 public-demo dependency records |
| pip-audit, release locks | Member B 0; Member A exit 1: `pytest==8.4.2`, two identical `PYSEC-2026-1845` records / `CVE-2025-71176` / `GHSA-6w46-j5rx-g56g`, fixed in 9.0.3; retained UNIX-only issue |
| Current snapshot and artifact scans | Proposed source: only two known synthetic UUID matches; public static artifact: zero findings |

Total suite tests freshly passed: **106** (38 + 38 + 12 + 12 + 6), plus the separately described link/protocol assertions. No suite test was skipped in these focused runs. Full 741/859 backend suites, MySQL, private cross-engine browser suite, fresh installation and infrastructure checks are not repeated: code is unchanged and prior results are separately dated evidence. No paid/live inference, real email, OpenShell or video.

Nonblocking technical limitations remain: Windows-only backend locks, pytest UNIX advisory, ESLint support warning, private Windows WebKit cookie limitation, native screen readers/physical devices and actual hosted HTTPS/headers not certified. No P0/P1 technical regression found in the accepted local/static scopes. **P1 release gates remain O1–O8 and the history decision; deployment also needs O9.** Missing operational authorization is not treated as a failing test, but missing distribution rights are material.

The [pytest advisory](https://github.com/advisories/GHSA-6w46-j5rx-g56g) concerns UNIX temporary-directory handling; this lock is qualified only for Windows. Fixing it by overriding Member A's `<9` constraint requires a separate tested compatibility change. It is reported explicitly, not suppressed or described as a vulnerability-free Python dependency set.

## Next actionable step

Have the actual rights holders supply O1–O6/O8 names, scope and consent; select MIT or an alternative and the source-only history strategy. Then prepare the approved copyright/LICENSE and refreshed exact manifest for final artifact review. Explicit Git publication and hosting authorization come afterward. Do not push this existing branch or upload the workspace. No approval is inferred from this report's filename.
