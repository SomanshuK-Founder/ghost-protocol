# Publication manifest — Phase 5A

**Do not publish the complete working directory or assume its existing Git history is the release artifact.** The positive release verdict means ready for human publication review, not permission to push.

## Reviewed source snapshot

[`publication-files.json`](publication-files.json) is the exact relative-path/SHA-256 allowlist. It includes application/test source, unchanged migrations, approved synthetic fixtures, manifests/locks, the browser contract, selected portable setup/security documentation, four curated screenshots, attribution notices and these release documents. The JSON excludes its own hash to avoid recursion; the exporter copies that fixed manifest separately.

The reviewed snapshot has **353 files including the manifest**, approximately 3.6 MiB; its largest individual file is the existing npm lockfile, below 250 KB. It is a source distribution, not an installed environment or production binary bundle.

One intentionally included historical-path file is `docs/integration/step44d_option_a_logs/openapi.json`: it is an unchanged schema fixture required by the existing OpenAPI regression. It contains no runtime log, credential or session. All other historical integration/host evidence is omitted from this source snapshot. It remains untouched in the original workspace.

Validate and prepare a **fresh directory outside this repository**:

```powershell
.venv/Scripts/python.exe -B tools/prepare_publication.py --check
$reviewDirectory = Join-Path ([IO.Path]::GetTempPath()) ("ghost-publication-review-" + [guid]::NewGuid())
.venv/Scripts/python.exe -B tools/prepare_publication.py --directory "$reviewDirectory"
```

The small standard-library tool verifies hashes, rejects path escapes/symlinks/private environment paths, refuses an existing destination and performs no Git operation or deletion. Its six regression cases cover contained paths, changed bytes, explicit copying and preservation of unknown local files. Re-review/regenerate the allowlist after any source change; do not bypass a hash mismatch. The tool is not a secret scanner or license approval mechanism.

## Exclusions and disposition

| Category | Publication handling | Existing workspace |
| --- | --- | --- |
| `.git/` | Exclude. Existing history is not silently rewritten or copied. | Preserved; 19 reachable commits audited separately. |
| Actual `.env`, pairing/session values, credentials | Exclude. `.env.example` templates contain placeholders only. | Private ignored values retained; never printed in release evidence. |
| `nvidia backend.zip` | Exclude; includes an old environment/configuration and unnecessary installed dependencies. | Preserved, not deleted; archive metadata/config reviewed privately. |
| Virtual environments, `node_modules`, caches, `.next`, `out`, browser binaries | Exclude; install through reviewed locks. | Preserved; fresh acceptance used task-owned temporary directories. |
| SQLite/MySQL/checkpoint data, debug/session logs and private terminal evidence | Exclude, including ignored runtime state. | Preserved. Use approved initializer to create new synthetic state. |
| Historical `docs/integration` / `docs/openshell` raw evidence | Exclude except the explicit OpenAPI fixture above. Contains machine/operator paths and internal diagnostics. | All original evidence preserved. |
| Phase 1–4 reports and screenshot trees | Exclude from this public snapshot; selected portable conclusions live in Phase 5A docs. | Original 192 PNG captures and reports preserved. |
| Four `docs/assets/frontend/*.png` screenshots | Include unchanged copies with synthetic-mode context in README. | Original captures preserved. |
| OpenShell binaries, model weights, infrastructure artifacts | Exclude; no runtime admission or license permission inferred. | No resource started or removed. |

The existing root/frontend `.gitignore` rules already cover environments, secrets, keys, databases, caches, Node/build/test output and archives; no Phase 5A change is required. An ignore rule does not remove a tracked file or history entry. The allowlist is intentionally stricter than `.gitignore` and includes no large installed environment/archive.

## History and privacy

The local reachable history scan found no confirmed credential. Generic detector matches were verified source SHA-256 values, not ignored silently. This is not proof that every possible secret format is detectable. Historical source/evidence contains absolute private machine paths, and author metadata has one identity requiring consent. Public release from existing history therefore needs a separate privacy decision and review of every retained historical artifact. No remote refs were fetched or hidden/unreachable objects certified.

The shortest safe publication route is to review the allowlisted **source snapshot** as a new repository after owner/license/author consent. That is a recommendation; no repository was initialized, rewritten, committed or pushed. If preserving existing history is required, approve a separate history/privacy remediation plan first. Do not push this working repository wholesale.

See the [audit](PHASE5A_RELEASE_AUDIT.md), [attribution review](THIRD_PARTY_ATTRIBUTION.md) and [publication checklist](GITHUB_PUBLICATION_CHECKLIST.md) before any public action.
