# Screens and user flows

## 0. Local access / Pairing
- When pairing disabled show explicit “Local pairing is off — enable it through the operator setup.” No imaginary login credentials.
- Pairing code entry (single-use, short lifetime), accessible errors, expired/replayed flows. Never display full secret after consumption.
- Session status, local-only banner, logout.

## 1. Overview
- Recent tasks, pending approvals, recent audit events, connection/security status.
- Counts must come from accessible APIs; omit rather than invent unsupported aggregates.
- Primary CTA: Create task. Secondary: Review approvals.

## 2. Tasks and new task
- Task list with status, created time, safe summary and pagination.
- Empty state invites creating first task.
- New-task form maps exactly to actual create schema. Show constraint and schema errors inline.

## 3. Task details / Planning
- Summary header, task metadata, action Plan or current planning state, actual plan output summary.
- Decision Rail uses real workflow history and audit items only.
- While planning, show cancellable UI only if cancellation endpoint actually exists. Otherwise indicate bounded wait without promising cancellation.
- Real `ALLOW` is NOT execution. `SAFE_STOPPED` is prominent.

## 4. Approval center
- Pending approvals list with urgency/expiry. Only show fields supplied by backend.
- Detail view: operation, task, purpose, scope, expiry, provenance; separate Approve and Reject.
- Decision dialog summarizing consequences. Only update after backend confirms and refetches.
- Revocation interface only where authorized and present in contract.

## 5. Workflow / Operations
- Workflow status, continuation requests if supported, status/error/UNKNOWN.
- No direct dispatch button, no “retry execution” for UNKNOWN.
- Operation history shows IDs, status, timestamps and source references.

## 6. Audit activity
- Paginated chronological event stream with filter controls only for API-supported filters; a detail drawer with redacted metadata, status and audit refs.
- No fabricated traces or expanded raw logs containing sensitive payloads.

## 7. Document catalog
- Six-field allowlisted metadata, owner-scoped. Never expose raw document contents, disk paths, storage aliases, digests.
- Disabled/hidden read or share actions unless explicitly supported by protected workflow and consent.

## 8. Settings & Help
- Local connection mode, session info, provenance legend, security limitations, logout, README link.
- OpenShell status must be marked runtime-unverified; show Nemotron live-verification historical evidence separately from current mock UI.

## Universal screen states
Loading skeleton, empty, 401/session expired, 403/not authorized, 404, 409 conflict, 422 validation, rate limited (if implemented), 5xx, disconnected, UNKNOWN/reconciliation. Every action must have focus/keyboard handling and a truthful recovery message.
