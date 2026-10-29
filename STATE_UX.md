# State management, errors and feedback

## State categories
1. Session: server-owned; React only holds safe session view and CSRF token as permitted.
2. Server data: tasks, planning, approvals, audit, catalog. Derive from typed API responses.
3. Transient UI state: dialog open, active filters, draft text, expanded rows.
4. Demo provenance: display from actual response fields. In separate synthetic demo mode, all content visibly labeled synthetic.

## Status handling
Build status enumerations from OpenAPI, not guessed Python enums. Treat unknown status as `Unknown state` and show an inspection/reload path. `UNKNOWN` outcomes mean manual reconciliation, never auto retry. A workflow at `SAFE_STOPPED` must not appear as successful protected dispatch.

## API error handling
- 401: clear session view and return to pairing flow.
- 403: explain lack of permission without exposing hidden resource details.
- 404: display not found.
- 409: show conflict/stale state; refetch before user decides again.
- 422: inline form errors based on backend detail.
- 5xx/timeout: preserve draft; explain request may have uncertain outcome if mutation was submitted. No blind replay.

## Performance
Avoid massive dashboard queries, cap list pages, only poll active workflows with bounded intervals, obey reduced motion, provide low-bandwidth behavior. Use semantic live regions selectively for approval/state updates.
