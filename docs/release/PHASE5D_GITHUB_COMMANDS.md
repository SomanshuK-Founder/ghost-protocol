# Phase 5D-R1 — exact GitHub publication procedure

**Prepared for explicit publication approval; no add, commit, push or tag has been performed.** Team rights/MIT/asset approval is already confirmed and must not be requested again for this scope.

## Existing source-only repository

Reuse `Ghost_Protocol_Publication_Staging_5D_REVIEW_ONLY` outside the original project. It is already initialized on unborn `main`, with empty index, zero commits/tags, no remote or inherited objects. Do not reinitialize it or run these steps against the original development repository. Local `core.autocrlf=false` preserves reviewed bytes.

Read-only checks from staging:

```powershell
git rev-parse --show-toplevel
git symbolic-ref --short HEAD
git rev-list --all --count
git ls-files
git remote
python -B tools/prepare_publication.py --check
```

Expected: staging root, `main`, zero commits, empty tracked-file and remote output, 391 validated paths plus the manifest. Root/public-demo LICENSE files must contain the approved collective notice and full MIT body. All six assets are present; no rights hold remains.

## After separate explicit commit/publication authorization

The remaining commands are reference only and were not executed. Confirm the exact prepared artifact, GitHub account/repository name/visibility and public Git author metadata with that instruction. License attribution is already **Copyright (c) 2026 Ghost Protocol Contributors**; it does not fabricate a Git author email.

From the verified staging root:

```powershell
$releaseManifestPath = 'docs/release/phase5d-staging-files.json'
$releaseManifest = Get-Content -LiteralPath $releaseManifestPath -Raw | ConvertFrom-Json
if ($releaseManifest.approval_status -ne 'RIGHTS_CONFIRMED_FINAL_REVIEW' -or $releaseManifest.withheld.Count -ne 0) { throw 'Review metadata is not complete.' }
if (-not (Test-Path -LiteralPath LICENSE)) { throw 'Operative LICENSE missing.' }
python -B tools/prepare_publication.py --check
if ($LASTEXITCODE -ne 0) { throw 'Reviewed source hashes do not match.' }

$approvedPaths = @($releaseManifest.files.path) + @($releaseManifestPath)
$pathspecFile = Join-Path ([IO.Path]::GetTempPath()) ('ghost-approved-paths-' + [guid]::NewGuid() + '.nul')
[IO.File]::WriteAllBytes($pathspecFile, [Text.Encoding]::UTF8.GetBytes(($approvedPaths -join [char]0) + [char]0))
git --literal-pathspecs add --pathspec-from-file="$pathspecFile" --pathspec-file-nul
if ($LASTEXITCODE -ne 0) { throw 'Git add failed.' }
$indexedPaths = @(git -c core.quotepath=false diff --cached --name-only)
if (@(Compare-Object ($approvedPaths | Sort-Object) ($indexedPaths | Sort-Object)).Count -ne 0) { throw 'Unexpected or missing indexed paths.' }
foreach ($relativePath in $approvedPaths) {
    $indexObject = (git rev-parse ":$relativePath").Trim()
    $workingObject = (git hash-object --no-filters -- "$relativePath").Trim()
    if ($LASTEXITCODE -ne 0 -or $indexObject -ne $workingObject) { throw 'Index bytes differ from reviewed working bytes.' }
}
git diff --cached --stat
```

Do not use `git add .` or `git add -A`. A JSON field is not publication authorization; the explicit human instruction is required. If any path/hash differs, stop for review rather than silently adding, deleting or normalizing content.

Only after the authorized index review:

```powershell
$approvedAuthorName = Read-Host 'Approved public Git author name'
$approvedAuthorEmail = Read-Host 'Approved public email or verified GitHub noreply address'
if ([string]::IsNullOrWhiteSpace($approvedAuthorName) -or [string]::IsNullOrWhiteSpace($approvedAuthorEmail)) { throw 'Verified Git identity required.' }
git config --local user.name "$approvedAuthorName"
git config --local user.email "$approvedAuthorEmail"
git commit -m 'Initial Ghost Protocol source-only release'
```

Create the authorized empty GitHub repository with the approved owner/name/visibility; do not auto-create another README/license/gitignore or import the original history. Once push is explicitly authorized:

```powershell
$approvedRepositoryUrl = Read-Host 'Approved empty GitHub HTTPS repository URL'
if ($approvedRepositoryUrl -notmatch '^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?$') { throw 'Use a verified credential-free GitHub repository URL.' }
git remote add origin "$approvedRepositoryUrl"
git remote -v
git push --set-upstream origin main
```

Use the normal credential manager, never a token embedded in source or a URL. Do not force-push, tag or rewrite the original repository. For later Windows clones use `git -c core.autocrlf=false clone` when checking exact manifest bytes. Verify remote visibility, source inventory, license/notices and absence of old history after publication. No remote or public repository has been created in this phase.
