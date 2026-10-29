# Phase 5C — exact conditional publication manifest

**Not approved for public distribution.** Ownership/license/history decisions in [PHASE5C_PUBLICATION_APPROVAL.md](PHASE5C_PUBLICATION_APPROVAL.md) remain material gates.

## Two distinct artifacts

1. **Repository source candidate:** `docs/release/publication-files.json`, updated to Phase 5C, contains 383 relative file paths with exact SHA-256 hashes. It excludes its own hash and is copied separately by the existing exporter: **384 files total**. This includes the accepted local application, private frontend source (not credentials), isolated public-demo source, approved synthetic fixtures, portable contracts/docs, notices and curated images. The Phase 5A count of 353 describes that older snapshot, not this combined release.
2. **Public hosting artifact:** exactly 13 files under `public-demo/dist/`, described below. It contains no backend, private frontend, logs, screenshots, database, test suite or dependencies. Source approval does not permit uploading the repository as a web application.

The source manifest is an explicit allowlist, not a recursive “all untracked files” selection. SHA mismatches require review; do not bypass them. A new approved LICENSE or any content change requires a manifest refresh and re-scan. The new source-review export contains no `.git` and has no commits.

## Validate / export without publication

From the repository root, use the existing reviewed tool:

```powershell
.venv/Scripts/python.exe -B tools/prepare_publication.py --check
$reviewDirectory = Join-Path ([IO.Path]::GetTempPath()) ("ghost-phase5c-review-" + [guid]::NewGuid())
.venv/Scripts/python.exe -B tools/prepare_publication.py --directory "$reviewDirectory"
```

This validates all listed bytes and copies only the allowlist plus the manifest to a fresh outside directory. It refuses an existing destination, path escapes, symlinks and private environment paths, and performs no Git operation or deletion. The manifest is not a secret scanner, permission grant or signature. Review that copy after rights decisions; do not publish the complete working directory.

## Inclusion decisions

| Group | Decision |
| --- | --- |
| Original application/source/tests/migrations | Include exact existing bytes conditionally; rights/teammate approval required |
| Frontend source, package lock, generation/static-host/test scripts | Include source; build/dependency output excluded |
| Public-demo source/config/lock/tests | Include 25 nonignored source files; `dist` is a separate hosting artifact |
| Synthetic fixtures | Include unchanged approved synthetic data; confirm team rights |
| OpenAPI / safe handoff docs | Include canonical application contract and portable handoff pack |
| Historical-path schema fixture | Include only `docs/integration/step44d_option_a_logs/openapi.json`, required by existing contract regressions; not a runtime log |
| Four curated frontend images | Include existing synthetic captures under `docs/assets/frontend/`; originals and raw screenshot trees excluded |
| Locks, notice copies, draft license, Phase 5A/B/C release reports | Include for setup/review/attribution; draft does not become operative |

Excluded: `.git`, actual `.env` files, ignored backend archive, keys/certificates, databases/checkpoints, environments/node_modules/caches/build output, raw integration/OpenShell evidence, private Phase 1–4 reports and screenshot trees, traces/video/test results, native binaries and model weights. `.env.example` templates are explicitly included and contain public placeholders only. Ignore rules alone are insufficient; the exact allowlist controls copying.

No selected source file contains the actual private operator root path or known local credential. No database/key/archive/executable file is selected. The generic TLS rejection test's invalid key delimiter and generic `C:\\Users\\` privacy-test string are test data, not a real private key or an operator path. No individual source file exceeds 250 KB; the existing frontend npm lockfile is the largest. Fonts/dependency licensing and unresolved teammate rights are documented in the [approval review](PHASE5C_PUBLICATION_APPROVAL.md).

## Exact hosting file list

Only these 13 upload files are authorized for technical review, subject to separate rights/deployment approval:

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

Total 131,153 bytes. Artifact-manifest SHA-256: `9713cb92d88f2f564f6e0b6acf3f2568799fce7fabc73b568f7f4fe4d23e2d45`. Its map hashes the other 12 files. Cloudflare consumes `_headers` as configuration rather than serving it as an asset; Vercel uses the reviewed source `vercel.json` instead. Do not add a proxy, credentials or functions. See the [deployment review](PHASE5C_PUBLIC_DEMO_DEPLOYMENT_REVIEW.md).

## Exact repository paths

The following complete list is generated from the same reviewed source manifest, including its separately copied JSON file. SHA-256 values live in that JSON; this Markdown does not embed a hash of itself or the manifest, avoiding circular hashes.

<!-- PHASE5C_PATHS -->

```text
.env.example
.gitignore
.node-version
AGENTS.md
API_INTEGRATION.md
ARCHITECTURE.md
AUTH_SECURITY.md
CODEX_WORKFLOW.md
COMPONENTS.md
DECISIONS_AND_RISKS.md
DEMO_STORYBOARD.md
FRONTEND_AGENT_INSTRUCTIONS.md
IMPLEMENTATION_PLAN.md
INTEGRATION_CONTRACTS.md
MEMBER_B_SCOPE.md
PHASE_PLAN.md
PRODUCT_SCOPE.md
PROJECT_CONTEXT.md
PUBLIC_DEMO.md
QA_ACCEPTANCE.md
README.md
README_START_HERE.md
SCREENS.md
SECURITY_RULES.md
SKILLS_AND_INSTALL.md
STATE_UX.md
SUBMISSION_CHECKLIST.md
TESTING_AND_ACCEPTANCE.md
backend/app/agent/__init__.py
backend/app/agent/application_host.py
backend/app/agent/approval_workflow.py
backend/app/agent/controlled_contracts.py
backend/app/agent/controlled_execution.py
backend/app/agent/demo_execute.py
backend/app/agent/demo_plan.py
backend/app/agent/execution_contracts.py
backend/app/agent/gateway_protocol.py
backend/app/agent/graph.py
backend/app/agent/http_gateway.py
backend/app/agent/integration_runtime.py
backend/app/agent/mock_gateway.py
backend/app/agent/mock_model_provider.py
backend/app/agent/orchestration.py
backend/app/agent/planning_contracts.py
backend/app/agent/state.py
backend/app/agent/workflow_checkpointer.py
backend/app/agent/workflow_contracts.py
backend/app/agent/workflow_transport.py
backend/app/llm/__init__.py
backend/app/llm/config.py
backend/app/llm/contracts.py
backend/app/llm/errors.py
backend/app/llm/live_validation.py
backend/app/llm/nebius_provider.py
backend/app/llm/telemetry.py
backend/app/llm/validation.py
backend/app/memory/__init__.py
backend/app/memory/protocols.py
backend/app/skills/__init__.py
backend/app/skills/contracts.py
backend/app/tls.py
backend/tests/agent/__init__.py
backend/tests/agent/asgi_backend_worker.py
backend/tests/agent/demo_runtime.py
backend/tests/agent/demo_runtime_controller.py
backend/tests/agent/demo_runtime_guard.py
backend/tests/agent/demo_runtime_worker.py
backend/tests/agent/integrated_demo.py
backend/tests/agent/test_application_host.py
backend/tests/agent/test_approval_workflow.py
backend/tests/agent/test_contracts.py
backend/tests/agent/test_controlled_execution.py
backend/tests/agent/test_fastapi_gateway_integration.py
backend/tests/agent/test_gateway_orchestration.py
backend/tests/agent/test_http_gateway.py
backend/tests/agent/test_integrated_demo.py
backend/tests/agent/test_nebius_live_controls.py
backend/tests/agent/test_nebius_provider.py
backend/tests/agent/test_planning_graph.py
backend/tests/agent/test_step41_validation.py
backend/tests/agent/test_tls.py
backend/tests/evaluations/__init__.py
backend/tests/live/__init__.py
backend/tests/live/step41_validation.py
backend/tests/live/test_nebius_live.py
backend/tests/run_offline_suite.py
design.md
docs/assets/frontend/approval-mobile.png
docs/assets/frontend/dashboard-desktop.png
docs/assets/frontend/dashboard-mobile.png
docs/assets/frontend/safe-stopped-desktop.png
docs/frontend-handoff/01_AUTHENTICATION_CONTRACT.md
docs/frontend-handoff/02_APPLICATION_API_CONTRACT.md
docs/frontend-handoff/03_TASK_AND_WORKFLOW_LIFECYCLE.md
docs/frontend-handoff/04_OPENAPI_REPAIR_PLAN.md
docs/frontend-handoff/05_FRONTEND_SECURITY_BOUNDARIES.md
docs/frontend-handoff/06_VERIFIED_API_INVENTORY.md
docs/frontend-handoff/generated/ghost-app-v1.openapi.json
docs/integration/step44d_option_a_logs/openapi.json
docs/release/DEPENDENCY_REPRODUCIBILITY.md
docs/release/GITHUB_PUBLICATION_CHECKLIST.md
docs/release/PHASE5A_RELEASE_AUDIT.md
docs/release/PHASE5B_DEPLOYMENT_GUIDE.md
docs/release/PHASE5B_PUBLIC_DEMO_IMPLEMENTATION.md
docs/release/PHASE5B_SECURITY_REVIEW.md
docs/release/PHASE5C_EXACT_PUBLICATION_MANIFEST.md
docs/release/PHASE5C_PUBLICATION_APPROVAL.md
docs/release/PHASE5C_PUBLIC_DEMO_DEPLOYMENT_REVIEW.md
docs/release/PUBLICATION_MANIFEST.md
docs/release/PUBLIC_DEMO_DECISION.md
docs/release/THIRD_PARTY_ATTRIBUTION.md
docs/release/dependency-licenses.json
docs/release/license-proposals/MIT-LICENSE.DRAFT.txt
docs/release/licenses/inter-OFL-1.1.txt
docs/release/licenses/lucide-ISC.txt
docs/release/licenses/next-MIT.txt
docs/release/licenses/react-MIT.txt
docs/release/licenses/react-dom-MIT.txt
docs/release/licenses/space-grotesk-OFL-1.1.txt
docs/release/licenses/tailwind-MIT.txt
docs/release/publication-files.json
fixtures/ghost_demo/MANIFEST.json
fixtures/ghost_demo/README.md
fixtures/ghost_demo/consents/README.md
fixtures/ghost_demo/consents/example_memory.json
fixtures/ghost_demo/consents/example_policies.json
fixtures/ghost_demo/documents/private/bank_statement_demo.txt
fixtures/ghost_demo/documents/private/personal_notes.txt
fixtures/ghost_demo/documents/private/tax_statement_2026.txt
fixtures/ghost_demo/documents/shareable/meeting_summary.txt
fixtures/ghost_demo/documents/shareable/project_report.txt
fixtures/ghost_demo/documents/shareable/project_schedule.txt
fixtures/ghost_demo/emails/ambiguous_request.txt
fixtures/ghost_demo/emails/consent_request.txt
fixtures/ghost_demo/emails/forged_consent_email.txt
fixtures/ghost_demo/emails/injection_in_shareable_report.txt
fixtures/ghost_demo/emails/legitimate_email.txt
fixtures/ghost_demo/emails/malicious_email.txt
fixtures/ghost_demo/fixtures/resources.json
fixtures/ghost_demo/fixtures/tasks.json
fixtures/ghost_demo/fixtures/test_clock.json
fixtures/ghost_demo/fixtures/test_users.json
fixtures/ghost_demo/scenarios/index.json
fixtures/ghost_demo/scenarios/scn-001.json
fixtures/ghost_demo/scenarios/scn-002.json
fixtures/ghost_demo/scenarios/scn-003.json
fixtures/ghost_demo/scenarios/scn-004.json
fixtures/ghost_demo/scenarios/scn-005.json
fixtures/ghost_demo/scenarios/scn-006.json
fixtures/ghost_demo/scenarios/scn-007.json
fixtures/ghost_demo/scenarios/scn-008.json
fixtures/ghost_demo/scenarios/scn-009.json
fixtures/ghost_demo/scenarios/scn-010.json
fixtures/ghost_demo/scenarios/scn-011.json
fixtures/ghost_demo/scenarios/scn-012.json
fixtures/ghost_demo/scenarios/scn-013.json
fixtures/ghost_demo/scenarios/scn-014.json
fixtures/ghost_demo/scenarios/scn-015.json
frontend/.gitignore
frontend/.prettierignore
frontend/API_OPERATIONS.md
frontend/README.md
frontend/eslint.config.mjs
frontend/next-env.d.ts
frontend/next.config.ts
frontend/package-lock.json
frontend/package.json
frontend/playwright.config.ts
frontend/postcss.config.mjs
frontend/scripts/generate-api.mjs
frontend/scripts/operation-map.mjs
frontend/scripts/serve.py
frontend/src/app/approvals/detail/page.tsx
frontend/src/app/approvals/page.tsx
frontend/src/app/audit/page.tsx
frontend/src/app/documents/page.tsx
frontend/src/app/globals.css
frontend/src/app/help/page.tsx
frontend/src/app/icon.svg
frontend/src/app/layout.tsx
frontend/src/app/not-found.tsx
frontend/src/app/operations/detail/page.tsx
frontend/src/app/operations/page.tsx
frontend/src/app/page.tsx
frontend/src/app/settings/page.tsx
frontend/src/app/tasks/detail/page.tsx
frontend/src/app/tasks/new/page.tsx
frontend/src/app/tasks/page.tsx
frontend/src/components/audit-events.tsx
frontend/src/components/decision-rail.tsx
frontend/src/components/evidence-ui.tsx
frontend/src/components/operation-records.tsx
frontend/src/components/review-primitives.tsx
frontend/src/components/session.tsx
frontend/src/components/shell.tsx
frontend/src/components/task-cancel.tsx
frontend/src/components/task-scope-picker.tsx
frontend/src/components/task-table.tsx
frontend/src/components/ui.tsx
frontend/src/components/workflow-control.tsx
frontend/src/features/approval-center.tsx
frontend/src/features/approval-detail.tsx
frontend/src/features/audit.tsx
frontend/src/features/dashboard.tsx
frontend/src/features/documents.tsx
frontend/src/features/operations.tsx
frontend/src/features/settings.tsx
frontend/src/features/task-detail.tsx
frontend/src/features/tasks.tsx
frontend/src/lib/api/client.ts
frontend/src/lib/api/schema.d.ts
frontend/src/lib/api/types.ts
frontend/src/lib/approval-review.ts
frontend/src/lib/evidence.ts
frontend/src/lib/owner-commands.ts
frontend/src/lib/presentation.ts
frontend/src/lib/rail-records.ts
frontend/src/lib/task-evidence.ts
frontend/src/lib/use-cursor-page.ts
frontend/src/lib/use-resource.ts
frontend/tests/api-client.test.ts
frontend/tests/approval-review.test.ts
frontend/tests/browser/control-room.spec.ts
frontend/tests/browser/human-control.spec.ts
frontend/tests/browser/product-experience.spec.ts
frontend/tests/browser_worker.py
frontend/tests/decision-rail.test.ts
frontend/tests/design.test.ts
frontend/tests/evidence.test.ts
frontend/tests/owner-commands.test.ts
frontend/tests/review-fixture.ts
frontend/tests/schema.test.ts
frontend/tests/test_static_host.py
frontend/tsconfig.json
member_a_backend/nvidia backend/.dockerignore
member_a_backend/nvidia backend/.env.example
member_a_backend/nvidia backend/.gitignore
member_a_backend/nvidia backend/Dockerfile
member_a_backend/nvidia backend/alembic.ini
member_a_backend/nvidia backend/app/__init__.py
member_a_backend/nvidia backend/app/agent_auth.py
member_a_backend/nvidia backend/app/agent_schemas.py
member_a_backend/nvidia backend/app/application_contracts.py
member_a_backend/nvidia backend/app/browser_auth.py
member_a_backend/nvidia backend/app/config.py
member_a_backend/nvidia backend/app/controlled_contracts.py
member_a_backend/nvidia backend/app/database.py
member_a_backend/nvidia backend/app/gateway_contracts.py
member_a_backend/nvidia backend/app/local_demo.py
member_a_backend/nvidia backend/app/main.py
member_a_backend/nvidia backend/app/models.py
member_a_backend/nvidia backend/app/offline_demo.py
member_a_backend/nvidia backend/app/openapi.py
member_a_backend/nvidia backend/app/openapi_contracts.py
member_a_backend/nvidia backend/app/public.py
member_a_backend/nvidia backend/app/routes/__init__.py
member_a_backend/nvidia backend/app/routes/api.py
member_a_backend/nvidia backend/app/routes/application_interfaces.py
member_a_backend/nvidia backend/app/routes/application_tasks.py
member_a_backend/nvidia backend/app/routes/gateway.py
member_a_backend/nvidia backend/app/routes/health.py
member_a_backend/nvidia backend/app/routes/session.py
member_a_backend/nvidia backend/app/routes/workflow.py
member_a_backend/nvidia backend/app/schemas.py
member_a_backend/nvidia backend/app/security.py
member_a_backend/nvidia backend/app/services/__init__.py
member_a_backend/nvidia backend/app/services/agent_identity.py
member_a_backend/nvidia backend/app/services/application_host.py
member_a_backend/nvidia backend/app/services/application_interfaces.py
member_a_backend/nvidia backend/app/services/application_tasks.py
member_a_backend/nvidia backend/app/services/approvals.py
member_a_backend/nvidia backend/app/services/controlled_execution.py
member_a_backend/nvidia backend/app/services/document_catalog.py
member_a_backend/nvidia backend/app/services/document_reader.py
member_a_backend/nvidia backend/app/services/email_profile.py
member_a_backend/nvidia backend/app/services/fixture_storage.py
member_a_backend/nvidia backend/app/services/mailpit_email.py
member_a_backend/nvidia backend/app/services/operation_ledger.py
member_a_backend/nvidia backend/app/services/policy.py
member_a_backend/nvidia backend/app/services/resource_catalog.py
member_a_backend/nvidia backend/app/services/scoped_consent.py
member_a_backend/nvidia backend/app/services/secure_fixture_io.py
member_a_backend/nvidia backend/app/services/synthetic_executor.py
member_a_backend/nvidia backend/app/services/tools.py
member_a_backend/nvidia backend/app/services/trusted_execution.py
member_a_backend/nvidia backend/app/services/workflow_resume.py
member_a_backend/nvidia backend/app/workflow_contracts.py
member_a_backend/nvidia backend/compose.yaml
member_a_backend/nvidia backend/migrations/env.py
member_a_backend/nvidia backend/migrations/script.py.mako
member_a_backend/nvidia backend/migrations/versions/0001_initial.py
member_a_backend/nvidia backend/migrations/versions/0002_agent_identity.py
member_a_backend/nvidia backend/migrations/versions/0003_scoped_consent.py
member_a_backend/nvidia backend/migrations/versions/0004_operation_ledger.py
member_a_backend/nvidia backend/migrations/versions/0005_durable_approvals.py
member_a_backend/nvidia backend/migrations/versions/0006_trusted_execution.py
member_a_backend/nvidia backend/migrations/versions/0007_document_catalog.py
member_a_backend/nvidia backend/migrations/versions/0008_secure_document_reading.py
member_a_backend/nvidia backend/migrations/versions/0009_mailpit_email.py
member_a_backend/nvidia backend/migrations/versions/0010_workflow_resume.py
member_a_backend/nvidia backend/migrations/versions/0011_controlled_execution.py
member_a_backend/nvidia backend/migrations/versions/0012_application_commands.py
member_a_backend/nvidia backend/migrations/versions/0013_application_interfaces.py
member_a_backend/nvidia backend/pyproject.toml
member_a_backend/nvidia backend/requirements.txt
member_a_backend/nvidia backend/scripts/export_openapi.py
member_a_backend/nvidia backend/scripts/register_synthetic_resources.py
member_a_backend/nvidia backend/tests/conftest.py
member_a_backend/nvidia backend/tests/integration/__init__.py
member_a_backend/nvidia backend/tests/integration/conftest.py
member_a_backend/nvidia backend/tests/integration/provisioning.py
member_a_backend/nvidia backend/tests/integration/test_approval_mysql.py
member_a_backend/nvidia backend/tests/integration/test_catalog_mysql.py
member_a_backend/nvidia backend/tests/integration/test_controlled_mysql.py
member_a_backend/nvidia backend/tests/integration/test_document_linux.py
member_a_backend/nvidia backend/tests/integration/test_document_mysql.py
member_a_backend/nvidia backend/tests/integration/test_execution_mysql.py
member_a_backend/nvidia backend/tests/integration/test_identity_mysql.py
member_a_backend/nvidia backend/tests/integration/test_mailpit_mysql.py
member_a_backend/nvidia backend/tests/integration/test_mysql.py
member_a_backend/nvidia backend/tests/integration/test_operation_mysql.py
member_a_backend/nvidia backend/tests/integration/test_operation_validation_mysql.py
member_a_backend/nvidia backend/tests/integration/test_setup_safety.py
member_a_backend/nvidia backend/tests/integration/test_workflow_mysql.py
member_a_backend/nvidia backend/tests/offline_demo_worker.py
member_a_backend/nvidia backend/tests/run_offline_suite.py
member_a_backend/nvidia backend/tests/test_agent_identity.py
member_a_backend/nvidia backend/tests/test_api.py
member_a_backend/nvidia backend/tests/test_application_flush.py
member_a_backend/nvidia backend/tests/test_application_interfaces.py
member_a_backend/nvidia backend/tests/test_application_tasks.py
member_a_backend/nvidia backend/tests/test_approvals.py
member_a_backend/nvidia backend/tests/test_browser_auth.py
member_a_backend/nvidia backend/tests/test_config.py
member_a_backend/nvidia backend/tests/test_controlled_execution.py
member_a_backend/nvidia backend/tests/test_document_catalog.py
member_a_backend/nvidia backend/tests/test_document_reading.py
member_a_backend/nvidia backend/tests/test_mailpit_email.py
member_a_backend/nvidia backend/tests/test_offline_demo.py
member_a_backend/nvidia backend/tests/test_openapi.py
member_a_backend/nvidia backend/tests/test_operation_ledger.py
member_a_backend/nvidia backend/tests/test_scoped_consent.py
member_a_backend/nvidia backend/tests/test_trusted_execution.py
member_a_backend/nvidia backend/tests/test_workflow_resume.py
public-demo/.gitignore
public-demo/.node-version
public-demo/README.md
public-demo/eslint.config.mjs
public-demo/package-lock.json
public-demo/package.json
public-demo/playwright.config.mjs
public-demo/scripts/build.mjs
public-demo/scripts/guard.mjs
public-demo/scripts/policy.mjs
public-demo/scripts/preview.mjs
public-demo/scripts/verify.mjs
public-demo/src/app.ts
public-demo/src/dom.ts
public-demo/src/rail.ts
public-demo/src/state.ts
public-demo/static/ghost.svg
public-demo/static/index.html
public-demo/static/styles.css
public-demo/tests/browser/demo.spec.mjs
public-demo/tests/design.test.mjs
public-demo/tests/isolation.test.mjs
public-demo/tests/state.test.ts
public-demo/tsconfig.json
public-demo/vercel.json
pyproject.toml
requirements/member-a-windows-py314.lock.txt
requirements/member-b-test-tools.in
requirements/member-b-windows-py311.lock.txt
tests/openshell/policies/ghost-deny-os1.yaml
tests/openshell/workload/.gitignore
tests/openshell/workload/Dockerfile
tests/openshell/workload/README.md
tests/openshell/workload/image-inventory.json
tests/openshell/workload/prepare.py
tests/openshell/workload/probe.s
tests/openshell/workload/test_prepare.py
tools/prepare_publication.py
tools/tests/test_prepare_publication.py
tools/validate_openapi.py
```
