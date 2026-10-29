# GitHub publication checklist — human review required

Current status, Phase 5D-R1: original team rights, MIT attribution and asset redistribution are explicitly confirmed. The complete source-only snapshot is prepared for **explicit publication approval**; no commit, push or deployment is authorized or performed here. See [the R1 release review](PHASE5D_R1_FINAL_RELEASE_APPROVAL.md) and [current manifest](PHASE5D_STAGING_MANIFEST.md).

## Completed preparation

- [x] Read current acceptance, frontend/backend contracts, governing instructions and actual implementation.
- [x] Scan working/ignored files, archive configuration and all locally reachable Git commits; triage detector findings without publishing secret values.
- [x] Prepare a relative-path/hash publication allowlist and a non-destructive exporter; preserve original code, fixtures and evidence.
- [x] Prepare separate hash-locked Python environments and preserve the npm lockfile.
- [x] Actually install dependencies into clean isolated environments; run offline application, browser and contract regressions.
- [x] Inventory dependency licenses, retain core UI/font notices and prepare a review-only MIT draft.
- [x] Update portable README/setup instructions and document the separate synthetic public-demo route.

## Required before GitHub publication

- [x] Owner explicitly confirms Members A/B/C's original contributions and original team logo/icon/screenshot/demo redistribution rights; no repeat confirmation required for this scope.
- [x] Operative standard MIT LICENSE uses `Copyright (c) 2026 Ghost Protocol Contributors`; third-party notices and licenses remain unchanged.
- [x] Source-only strategy selected and existing empty staging Git repository reused; old history excluded.
- [x] Current `phase5d-staging-files.json` covers the complete prepared source. `tools/prepare_publication.py --check` now selects that manifest; the Phase 5C JSON is historical.
- [x] Final source/artifact secret/private-path checks and synthetic asset review complete.
- [x] Staged Windows builds/tests and documented platform/advisory limits verified; no universal platform claim.
- [ ] Select approved public Git author/contact metadata, repository owner/name/visibility and authorize commit/push separately. No individual identity is invented from the collective license attribution.
- [ ] Obtain explicit authorization for repository creation/commit/push, repository visibility and final content. No commit, push, tag or deployment has occurred in this phase.

If a real credential is later found in any retained history, stop publication, rotate/revoke the affected credential and agree remediation before proceeding. Deleting its current file is insufficient. Do not automatically rewrite history.

## Separate public-demo gate

- [x] Isolated public synthetic mode implemented and original team redistribution rights confirmed.
- [x] Staged interaction, synthetic-label, network/bundle, keyboard and responsive acceptance pass; MIT/OFL notices are packaged.
- [ ] Authorize the exact static artifact/account/project deployment separately, then verify the actual HTTPS URL and provider headers.

The complete public demo is prepared for explicit deployment approval; public URL remains NOT CREATED. Local pairing must never be tunneled or exposed as a shortcut.
