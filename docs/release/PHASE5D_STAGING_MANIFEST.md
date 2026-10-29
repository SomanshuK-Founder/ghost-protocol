# Phase 5D-R1 — final source staging manifest

Rights approval is recorded in [the R1 report](PHASE5D_R1_FINAL_RELEASE_APPROVAL.md). Publication and deployment still require separate explicit instructions.

## Exact reconciliation

The existing 383-file private Phase 5D copy is reused; its Git directory is preserved. The Phase 5C starting manifest remains archived in place at `docs/release/publication-files.json` (SHA-256 `381cfbc5367cb5129ffcaf850d1993a20e1f830c97484f9c4a32ac8b9358b24b`). Its old hashes are historical and are not the current validation target.

| Change from Phase 5D | Count |
| --- | --- |
| Existing source/review files retained, with explicit release-file hash updates | 383 |
| Restored authorized screenshots | 4 |
| Restored authorized SVG marks | 2 |
| Added operative root `LICENSE` | 1 |
| Added self-contained `public-demo/LICENSE` | 1 |
| Added `docs/release/PHASE5D_R1_FINAL_RELEASE_APPROVAL.md` | 1 |
| Removed paths | 0 |
| Final source files including the machine manifest | **392** |

The [machine manifest](phase5d-staging-files.json) holds 391 exact relative paths/SHA-256 hashes and is copied separately as file 392, avoiding a self-hash cycle. It records all restored assets, additions and changed paths. `withheld` is empty. Status becomes `RIGHTS_CONFIRMED_FINAL_REVIEW` after validation. It is an inventory/workflow record, not permission to run public actions.

Declared hash changes include root/public README, active attribution/publication checklist, the four Phase 5D reports, staging JSON, the release helper default selection and public notice generator. The app's state machine, UI, API contract, trusted backend, migrations and original fixtures remain unchanged. The new standard MIT files do not replace any third-party notice.

## Restored six files

```text
docs/assets/frontend/approval-mobile.png
docs/assets/frontend/dashboard-desktop.png
docs/assets/frontend/dashboard-mobile.png
docs/assets/frontend/safe-stopped-desktop.png
frontend/src/app/icon.svg
public-demo/static/ghost.svg
```

All six match their prior reviewed hashes. Original team rights are expressly approved. Licensed fonts/icons rendered in the screenshots retain their original terms and notices. No extra artwork or arbitrary untracked asset is included.

## Validation / future source export

From the complete staging copy or original source root, with a verified Python 3.11+ available:

```powershell
python -B tools/prepare_publication.py --check
```

The helper now defaults to `docs/release/phase5d-staging-files.json`. It refuses changed bytes, path escapes, private environment paths and symlinks. A future outside export uses the same manifest; it refuses an existing destination. The present prepared staging directory was updated only after its prior complete inventory/hashes were verified. Its existing `.git` was not replaced or reinitialized.

## Source-only exclusions

No old `.git`, actual `.env`, credentials, certificates, database/checkpoints, ignored archive, raw private-path evidence/logs, uncurated screenshots, Node/Python environment, build cache/output, browser video/trace, model weight or OpenShell executable enters the source inventory. Public `.env.example` placeholders and synthetic fixtures remain intentionally included.

New QA dependencies/build outputs are excluded and relocated after validation. The final directory has exactly 392 non-Git source files plus its empty fresh Git metadata. The separate public-demo distribution has exactly 13 reviewed static files, not the whole repository.

The original Git history is not copied or rewritten. No local author name/email, remote or commit is invented. Existing personal absolute filesystem paths are absent from the publication source; generic privacy-test path patterns are intentional test data.
