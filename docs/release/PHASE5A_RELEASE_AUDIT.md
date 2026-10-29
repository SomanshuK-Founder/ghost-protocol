# Phase 5A release audit

Audit date: 2026-10-29. Scope: completed Windows local offline Ghost Protocol application, source publication preparation and reproducible installation. No feature expansion, public listener, production security change, paid inference, email, OpenShell, video, Git mutation or deployment.

**REPOSITORY_READY_FOR_PUBLICATION_REVIEW**

**PUBLIC_DEMO_IMPLEMENTATION_READY** — a separate synthetic static mode is specified, not implemented or deployed.

These verdicts do not grant a project license, authorize publication, qualify production hosting or claim that simulated planning is real external execution.

## Inspection and preservation

Reviewed governing instructions, README, final Phase 4 quality/visual/security/repository/hosting reports, Step 44F-R2 acceptance, generated OpenAPI and final frontend API/security specifications, actual source/routes/session wiring, Git history and dependency manifests. Existing implementation uses Next.js static export with a same-origin loopback FastAPI audience and durable SQLite records. Human approval, continuation and protected execution remain separate.

Installed frontend testing, React, Playwright and UI/UX instructions informed the accepted product review; Ponytail keeps this release increment small. Requested `frontend-design` and `web-design-guidelines` packages were unavailable; no outputs were invented. No UI component was redesigned in Phase 5A.

The pre-phase SHA-256 baseline covers 1,415 existing tracked/nonignored files. Only root README and frontend README are intentionally updated by this phase; application code, authoritative contracts, original synthetic fixtures, previous evidence and all 192 Phase 1–3 PNGs remain unchanged. Existing unrelated Git modifications predate this phase and are not cleaned up. `.gitignore` was reviewed and remains unchanged by Phase 5A.

## Secret/privacy audit

Gitleaks 8.30.1 was obtained from the official release with its published archive checksum verified. Redacted reports stay in task-owned temporary storage, not the publication manifest. Both detector exit status and manual triage matter: findings were not falsely reported as a zero-match scan.

| Scan | Exact result / disposition |
| --- | --- |
| All local reachable Git history | 19 commits, 711 blobs. 15 detector matches across source checksum manifests, all verified SHA-256 false positives; no confirmed historical credential. |
| Working tree including ignored files, archive scan enabled | 334 matches: 313 source checksum false positives, 11 excluded third-party environment fixture values, 8 excluded generated Next build keys, 2 fixed synthetic idempotency UUID occurrences. Final rerun also returns 334, with no new finding. No unresolved detector match. |
| Proposed 353-file source snapshot | 2 generic-key matches, both the same synthetic idempotency UUID in `frontend/tests/api-client.test.ts` at lines 28 and 45. Detector exits 1 for those matches; manual triage confirms no credential. No blanket suppression added. |
| Known private local credential comparison | Actual ignored operator value compared privately, including common encoded forms, against reachable blobs and proposed public source; no match. Values are never printed or copied. |
| Ignored archive | `nvidia backend.zip` is 26,976,967 bytes; contains an old `.env` and installed environments. Reviewed API/password examples match public template placeholders; public CA bundles are not private keys. No known local credential match. Entire archive excluded. |
| Private-key pattern | Deliberately invalid TLS test fixture contains a delimiter but no private key material. No real signing key identified in selected source. |
| Privacy | 21 of 711 reachable blobs match Windows user-path patterns; one Git author identity needs consent. Raw evidence/history excluded from source snapshot. Curated images and selected source reviewed separately. |

No verified credential-in-history STOP condition occurred. No credential was rotated or history rewritten because the confirmed findings do not establish a leaked credential. Actual ignored `.env` remains private. The audit covers locally reachable refs; unfetched remote refs, deleted external copies and arbitrary unknown secret encodings are not certified.

## Reproducibility and security adjustment

Created Windows-specific, exact-version SHA-256 Python locks: 55 Member B distributions and 34 Member A distributions. Existing manifests and compatible versions are preserved, with one justified patch: Member B certifi moves from 2026.7.22 to 2026.10.23 to resolve the [CA-root advisory](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2). Existing offline-guard imports `requests`/`httpx2` are explicit test-tool inputs, not application services. Separate environments avoid the two `app` namespaces colliding.

Fresh release verification uses CPython 3.11.18/3.14.10, uv 0.13.6, Node 24.16.0/npm 11.13.0. Python patch releases were installed in a task-owned directory without changing original environments or registry. npm's existing lock remains unchanged. Detailed commands and supported-platform limits are in [DEPENDENCY_REPRODUCIBILITY.md](DEPENDENCY_REPRODUCIBILITY.md).

## Final isolated verification

The release allowlist is exported without Git, ignored files, environments or secrets. Dependencies are installed anew in that source copy using hashes and `npm ci`; original environments are not reused as evidence of a fresh installation. Browser tests use disposable real offline backends and private pairing pipes, not a fake backend. Temporary screenshots remain outside the original evidence directories.

| Check | Result |
| --- | --- |
| Hash-enforced clean Python installation | Member B 55 / Member A 34 distributions; both `uv pip check` compatible |
| Clean frontend install | `npm ci` succeeds; 386 installed packages / 387 audited; unchanged lockfile |
| Generated API / OpenAPI | 19 browser operations mapped; OpenAPI 3.1 document, 18 paths / 20 total operations / 44 schemas / 282 resolved references valid |
| TypeScript / ESLint / production export | All pass |
| Frontend unit tests | 38 passed |
| Static-host Python tests | 12 passed |
| Chromium / Firefox / Windows WebKit integration | 45 passed in 4.6 minutes: 15 per engine, no retry; genuine local backend |
| Member B guarded offline suite | 741 passed in 68.11 seconds, 1 paid-live case skipped |
| Member A guarded offline suite | 859 passed in 197.71 seconds, 313 MySQL integration cases deselected; one inherited Starlette deprecation warning |
| Publication exporter tests | 6 passed |
| Focused Ruff | Release tool/tests and frontend Python host/tests pass lint and format checks; application-focused existing targets also pass |
| Approved SQLite bootstrap | Fresh fixed-drive synthetic initialization and verification pass |
| Frontend dependency advisory scan | npm audit reports 0 known vulnerabilities |
| Python dependency advisory scan | Member B release lock: 0 known vulnerabilities. Member A: 2 records for 1 unique UNIX-only pytest advisory, explicitly retained for Windows qualification. |

Offline runners report no external calls. Supported workflow remains authentication → task → simulated planning → authorization → approve/reject/revoke → explicit continuation → genuine SAFE_STOPPED → durable audit. Existing suites cover expiry, replay, cancellation, cross-owner denial and UNKNOWN/reconciliation. Browser continuation never dispatches protected execution or sends mail. Windows WebKit is UI/protocol coverage only: its Strict-cookie limitation is annotated; Chromium/Firefox qualify tested cookie behavior. No Safari/macOS security acceptance is claimed.

Total final passing tests across the six suites above: **1,701** (741 + 859 + 12 + 38 + 45 + 6). The one paid skip and 313 MySQL deselections are excluded from that total. Preliminary full-copy installation also passed; the figures above are the final allowlisted-source run with the patched interpreters and certifi release lock. Final report/README/inventory edits do not change any tested application, test or lockfile bytes.

Focused Ruff covers 35 application/frontend/release Python files; the portable README command checks the five frontend/release Python files directly, without requiring an excluded historical target-list file.

The browser rerun covers 390/768/1280/1440/1920px and preserves the earlier screenshots. The four README images were inspected as unchanged synthetic captures. Release README/Markdown links resolve within the allowlisted snapshot, all selected text is UTF-8, and no actual operator root path, private operator credential or database/key/archive/executable file is included. A private exact/common-encoding credential check also covers all 101 generated frontend export files, with zero matches.

## Findings and release gates

| Priority | Finding | Disposition |
| --- | --- | --- |
| P1 publication gate | Project/teammate ownership and license are not yet approved | Explicit human review required; draft MIT is non-operative. This blocks publication, not preparation for review. |
| P1 publication gate | Complete workspace/history contains private config and machine/author metadata | Publish only reviewed allowlisted snapshot after consent; no wholesale workspace/history push. |
| P2 resolved | Original Member B certifi trust-root advisory and old interpreter patch levels | Release locks / isolated patched interpreters verified; originals preserved, not silently upgraded. |
| P2 platform limit | pytest 8.4.2 [UNIX temporary-directory advisory](https://github.com/advisories/GHSA-6w46-j5rx-g56g) | One unique advisory retained under existing `<9` constraint for Windows-only target. Other platforms require new acceptance. |
| P2 platform limit | Windows Playwright WebKit Strict-cookie behavior | UI/protocol only; do not certify Safari or weaken server policy. |
| P3 existing | Broad repository Ruff debt outside the focused change | Not a clean global Ruff claim; prior 64 diagnostics in 8 unchanged files remain out of scope. |
| P3 tool maintenance | npm reports ESLint 9.39.5 deprecated/unsupported | Current lint and npm advisory checks pass. A major lint-tool upgrade is deferred for separate compatibility review, rather than changing the accepted toolchain silently. |

No unresolved P0/P1 application defect was found in the accepted local-demo scope. Publication/legal gates above remain mandatory; “ready for publication review” does not mean “ready to push now.” Third-party native/bundle redistribution and provider/model terms require their own artifact review.

## Files and next actions

Added six requested Phase 5A release documents; Python lock/test-tool inputs; `.node-version`; dependency inventory and seven preserved UI/font notices; review-only MIT draft; four curated image copies; publication JSON allowlist, small exporter and six tests. Updated root/frontend README. No other existing source change is part of this phase.

Review the [publication manifest](PUBLICATION_MANIFEST.md), [attribution](THIRD_PARTY_ATTRIBUTION.md) and [checklist](GITHUB_PUBLICATION_CHECKLIST.md); approve owners/license/author metadata and exact artifact before separately authorizing any Git publication. For a public URL, authorize the isolated synthetic mode in [PUBLIC_DEMO_DECISION.md](PUBLIC_DEMO_DECISION.md), implement/test it, review its distributable, then separately approve hosting. The existing local pairing must not be exposed.

Not checked/claimed: fresh Linux/macOS installation, production MySQL/HTTPS, paid application inference, real email, native OpenShell enforcement, unreachable/unfetched Git history, or a deployed public URL. No video work was performed.
