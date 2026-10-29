# Dependency reproducibility — Phase 5A

The release target is **Windows x64 on a fixed local drive**. Keep separate Member B and Member A environments because both trees use the Python package name `app`. No backend authorization, application schema or production infrastructure change is required.

## Qualified inputs

| Input | Release choice |
| --- | --- |
| Member B interpreter | CPython 3.11.18 |
| Member A interpreter | CPython 3.14.10 |
| Installer/lock tool | uv 0.13.6; requirements-format locks usable independently of a uv project |
| Frontend | Node 24.16.0, npm 11.13.0; root `.node-version` and unchanged `frontend/package-lock.json` |
| Member B packages | `requirements/member-b-windows-py311.lock.txt`: 55 exact versions with distribution SHA-256 hashes |
| Member A packages | `requirements/member-a-windows-py314.lock.txt`: 34 exact versions with distribution SHA-256 hashes |

CPython patch updates are deliberate: the original working environments used 3.11.0 and 3.14.7. The release interpreters include the October 2026 security updates documented by [Python 3.11.18](https://www.python.org/downloads/release/python-31118/) and [Python 3.14.10](https://www.python.org/downloads/release/python-31410/). They were obtained into a task-owned directory without registering/changing the original interpreters. Original environments remain untouched.

The locks derive from the existing project manifests and accepted installed versions. The only application dependency patch adjustment is Member B `certifi` 2026.7.22 → 2026.10.23, already used by Member A, to remove the affected trust roots. Test-only `requests` and `httpx2` are explicit inputs in `requirements/member-b-test-tools.in` because the existing offline guard imports them; they were previously installed but undeclared for that runner. No application framework, database or new service is added.

## Fresh installation

Install uv 0.13.6 and the stated Node/npm prerequisites from official distributions. In a new checkout with neither `.venv` directory present:

```powershell
uv python install 3.11.18 3.14.10 --no-bin --no-registry
uv venv --python 3.11.18 .venv
uv pip sync --python .venv/Scripts/python.exe --require-hashes --only-binary=:all: --default-index https://pypi.org/simple requirements/member-b-windows-py311.lock.txt
uv venv --python 3.14.10 'member_a_backend/nvidia backend/.venv'
uv pip sync --python 'member_a_backend/nvidia backend/.venv/Scripts/python.exe' --require-hashes --only-binary=:all: --default-index https://pypi.org/simple requirements/member-a-windows-py314.lock.txt
uv pip check --python .venv/Scripts/python.exe
uv pip check --python 'member_a_backend/nvidia backend/.venv/Scripts/python.exe'

Push-Location frontend
npm ci
npm run generate:api
npm run typecheck
npm run lint
npm test
npm run build
Pop-Location
```

Do not run the environment-creation/sync commands over a teammate's existing environment. Use a fresh checkout or the reviewed publication copy. `sync` intentionally matches the selected lock; it is not a general command for an unknown shared environment. No application `.env` or provider credential is required. Installation downloads dependencies; offline acceptance means the subsequently tested application path uses no live provider/network service.

The exact dependency locks are platform/interpreter-targeted. Linux/macOS, other Python minor versions, MySQL deployment and native OpenShell are not qualified by this Windows setup. Maintain separate locks and run acceptance before claiming another target.

## SQLite setup and private authentication

From the repository root after the build:

```powershell
$demoDirectory = Join-Path ([IO.Path]::GetTempPath()) ("ghost-offline-demo-" + [guid]::NewGuid())
Push-Location 'member_a_backend/nvidia backend'
.venv/Scripts/python.exe -B -m app.offline_demo init --offline --directory "$demoDirectory"
.venv/Scripts/python.exe -B -m app.offline_demo verify --offline --directory "$demoDirectory"
Pop-Location
& 'member_a_backend/nvidia backend/.venv/Scripts/python.exe' -B frontend/scripts/serve.py --directory "$demoDirectory" --pair
```

Run the last command in a private interactive terminal. Pair at **http://127.0.0.1:3000** within 120 seconds; never capture the code. The initializer creates the approved SQLite ORM snapshot and synthetic catalog, not production MySQL migrations. Reuse the directory to retain records, or initialize a new unique directory for reset. Do not overwrite/delete previous state.

`npm run dev` is styling-only on port 3001. The connected path is static build plus the same-origin ASGI composition, not a second API listener, CORS or a generic proxy.

## Offline tests

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
$env:PYTHONIOENCODING = 'utf8'
.venv/Scripts/python.exe -B backend/tests/run_offline_suite.py
Push-Location 'member_a_backend/nvidia backend'
.venv/Scripts/python.exe -B tests/run_offline_suite.py tests -m 'not integration' -ra -p no:cacheprovider
.venv/Scripts/python.exe -B -m pytest ../../frontend/tests/test_static_host.py -q -p no:cacheprovider
Pop-Location
.venv/Scripts/python.exe -B -m pytest tools/tests/test_prepare_publication.py -q -p no:cacheprovider
.venv/Scripts/python.exe -B tools/validate_openapi.py docs/frontend-handoff/generated/ghost-app-v1.openapi.json
Push-Location frontend
npx playwright install chromium firefox webkit
npx playwright test --browser=all
Pop-Location
```

The root guarded runner imports both HTTP client transports and `requests` to prevent accidental networking. Member A's runner blocks networking/MySQL. Paid inference is explicitly skipped; integration-marked MySQL cases are deselected. No OpenShell/Docker/SMTP resource is needed.

Browser binaries are external QA tooling, not source publication assets. Test pairing travels through private pipes. To preserve earlier captures, run acceptance with TEMP/TMP scoped to a new task-owned temporary directory; do not change global system settings. Windows WebKit remains UI/protocol coverage only because of the observed Strict-cookie limitation.

## Advisory results and limits

- Frontend `npm audit`: no known vulnerability reported at audit time. Clean `npm ci` preserves the lockfile; platform-optional entries explain why installed-package count differs from all 466 lock records.
- The original Member B certifi advisory [GHSA-6q48-6c7w-9gw2](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2) is addressed by the release pin. Final Member B lock audit reports no known vulnerability.
- Member A's compatible pytest 8.4.2 test pin is still reported by pip-audit for [CVE-2025-71176](https://github.com/advisories/GHSA-6w46-j5rx-g56g), a UNIX temporary-directory issue. The scan returns duplicate records for the same advisory; count one unique issue. It is retained explicitly for this Windows-only target rather than silently overriding the existing `<9` test constraint. Do not use this lock as UNIX security acceptance. A pytest-major/other-platform change needs separate compatibility review.
- Dependency advisories are time-specific, not proof of universal security. The original ignored environments are not silently upgraded; use the new release setup before future live/provider work.
- `npm ci` warns that the locked ESLint 9.39.5 is deprecated/unsupported. Lint and the current vulnerability scan pass. An ESLint major upgrade is intentionally deferred to a separate compatibility change; no unreviewed major tool upgrade is performed for release preparation.

## Lock maintenance

[uv's official requirements-lock documentation](https://docs.astral.sh/uv/pip/compile/) describes compile/sync behavior. Regenerate from the existing manifests while constraining already reviewed pins:

```powershell
uv pip compile pyproject.toml requirements/member-b-test-tools.in --extra dev --constraint requirements/member-b-windows-py311.lock.txt --generate-hashes --no-header --no-annotate --python-version 3.11.18 --python-platform windows --default-index https://pypi.org/simple --output-file requirements/member-b-windows-py311.lock.txt
uv pip compile 'member_a_backend/nvidia backend/pyproject.toml' --extra dev --constraint requirements/member-a-windows-py314.lock.txt --generate-hashes --no-header --no-annotate --python-version 3.14.10 --python-platform windows --default-index https://pypi.org/simple --output-file requirements/member-a-windows-py314.lock.txt
```

A planned version update must first change the reviewed constraints, then regenerate, audit and rerun relevant acceptance. Do not remove pins to obtain an unreviewed upgrade. The generator excludes absolute command/header paths and private indexes. npm uses `npm ci`, not an unlocked install or automatic `audit fix`.

Actual fresh-install/regression outcomes, including the final patched-interpreter candidate, are recorded in [PHASE5A_RELEASE_AUDIT.md](PHASE5A_RELEASE_AUDIT.md). No clean-install pass is inferred solely from the original accepted environments.
