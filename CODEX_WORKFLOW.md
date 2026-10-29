# Codex prompting workflow

## Setup
Place all these Markdown files **in your project root**, including `AGENTS.md`. Work on a dedicated feature branch (`feat/member-b-agent`) and start Codex at the repository root. Codex should inspect actual code, not assume it matches plans.

## Reusable controlled phase prompt
```text
You are implementing Ghost Protocol v2.1 as Member B.
Read AGENTS.md, PROJECT_CONTEXT.md, MEMBER_B_SCOPE.md,
ARCHITECTURE.md, INTEGRATION_CONTRACTS.md, SECURITY_RULES.md,
PHASE_PLAN.md, TESTING_AND_ACCEPTANCE.md,
DECISIONS_AND_RISKS.md, and CODEX_WORKFLOW.md.

First inspect git status and existing repository files.
Work ONLY on phase [B0 / B1 / B2 / B3 / B4 / B5].
Before edits, state your plan, ownership boundaries, and dependencies.

Implement the minimum complete, secure, typed solution with relevant
tests. Do not edit A/C files, invent a policy engine, run sensitive tools
outside the gateway, or expose API secrets. Do not claim an unverified
integration works. Run pytest and Ruff where applicable.

Finally report changed files, executed checks with actual results,
remaining blockers, integration contract changes, and precise manual
verification steps. STOP and wait for my approval before the next phase.
```

## Phase completion checklist
- [ ] Only approved phase implemented.
- [ ] No unrelated changes.
- [ ] No API keys or real personal content committed.
- [ ] Tool gateway enforced even for malicious model outputs.
- [ ] Error paths and denial paths tested.
- [ ] All test failures/skips and deployment assumptions reported.
- [ ] Team integration requirements listed.
- [ ] Commit SHA recorded after review.

## When Codex must pause for confirmation
Shared file conflicts; required schema changes; any real email sending; introducing new libraries or external services; unexpected repo structure; switching models/providers; altering security boundaries; significant untested implementation assumptions.

## Reporting template
```
Phase:
Files added/modified:
What works:
Tests/checks (commands and outputs):
What remains mocked:
Security checks:
A/C integration dependencies:
Unresolved questions:
Suggested commit:
```
