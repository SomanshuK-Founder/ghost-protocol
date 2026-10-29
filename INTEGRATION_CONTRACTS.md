# Proposed integration contracts — sign-off required

**Status: PROVISIONAL.** The contracts below are for independent work and mock-driven development. They are not claims that these endpoints exist. Member A owns final authoritative schemas and transport; Member C owns public consumption.

## ToolGateway abstraction
The agent submits structured requests to Member A's authenticated gateway. It must not decide its own identity or privileges.

Suggested operations:
- `files.list_authorized`
- `files.read` with a server-known `resource_id`
- `email.draft`
- `email.send` with a typed recipient/body and optional approved `attachment_resource_ids`
- `tasks.list` (scope-limited for Morning Brief)

**Never permit** generic `shell.exec`, arbitrary URL fetch, raw path reads, direct SMTP, or unknown tool names.

## Example request (illustrative)
```json
{
  "request_id": "req-demo-001",
  "task_ref": "opaque-task-ref",
  "action": "email.send",
  "purpose": "share_document_summary",
  "arguments": {
    "recipient": "teammate@example.test",
    "subject": "Summary",
    "body": "Approved summary",
    "attachment_resource_ids": []
  },
  "idempotency_key": "opaque-dedupe-ref"
}
```
`task_ref` is a correlation ID, **not authorization**; A authenticates the caller and resolves the user and policy scope on the trusted side.

## Example response
```json
{
  "request_id": "req-demo-001",
  "decision": "APPROVAL_REQUIRED",
  "execution_status": "NOT_EXECUTED",
  "reason_code": "NO_MATCHING_CONSENT",
  "approval_ref": "approval-demo-001",
  "result": null,
  "audit_event_ref": "event-demo-001"
}
```

Decision enum: `ALLOW`, `DENY`, `APPROVAL_REQUIRED`.
Execution enum: `NOT_EXECUTED`, `SUCCEEDED`, `FAILED`, `UNKNOWN`.

## Approval and resume
1. B proposes a tool request.
2. A checks existing permissions; returns a decision.
3. On `APPROVAL_REQUIRED`, B pauses graph with approval reference.
4. A/C obtain authenticated user approval, persist it with purpose/resource/recipient/task/expiry.
5. A signals resumable task; B continues; **A rechecks policy immediately before execution**.
6. Revocation or expiry invalidates any permission on subsequent attempts.

## MemoryRepository (B-defined protocol, A-approved persistence)
- `list_active(task_context)` returns authorized relevant memories.
- `propose_update(source_ref, kind, value)` makes a candidate.
- `correct(memory_ref, new_value)` updates authoritative active state through trusted persistence.
- `get_for_task(task_ref)` respects task-scoped retrieval.

B can implement in-memory/mock adapters and contract tests; **A** approves actual database schema and migrations.

## SSE event example for C
```json
{
  "event_id": "ev-demo-001",
  "task_ref": "task-demo-001",
  "type": "tool.decision",
  "timestamp": "2026-10-12T12:00:00Z",
  "payload": {
    "action": "email.send",
    "decision": "DENY",
    "reason_code": "RECIPIENT_NOT_AUTHORIZED"
  }
}
```
Do not send document contents, credentials or full model prompts over UI events.

## Must agree with A before real integration
- Transport + sandbox-to-gateway caller authentication.
- Trusted task identity binding.
- Action names, schemas, failure codes, idempotency semantics.
- Approval TTL, race conditions, retries, UNKNOWN outcomes.
- Memory persistence ownership and deletion/correction.
- Task state and event shapes with C.
