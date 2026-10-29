# Member B architecture and execution boundaries

## Logical layout
```
Frontend (C)
    ↓
Trusted FastAPI control plane (A) ── PostgreSQL, audit, jobs (A)
    ↓
LangGraph personal agent (B) — runs in validated OpenShell sandbox
    ├── Nemotron reasoning → approved credential-isolated inference → Nebius
    └── ToolGateway Protocol → trusted authorization gateway (A)
                                  ├── deterministic ALLOW / DENY / APPROVAL_REQUIRED
                                  └── permitted file and Mailpit tools
```
This is a logical diagram; the precise processes and network routing are **unverified** until A's OpenShell tests pass.

## Agent state (provisional)
- Trusted opaque `task_ref`, current status and skill ID.
- Bounded conversation/task context and relevant memory references.
- Pending gateway request, approval reference, last result, retry count.
- Model telemetry correlation ID and structured error.

Suggested task states: `CREATED`, `PLANNING`, `RUNNING`, `AWAITING_APPROVAL`, `COMPLETED`, `FAILED`, `CANCELLED`.

**Authorization decisions and execution outcomes are separate dimensions.** A tool call may be `ALLOW` but `FAILED`, or `APPROVAL_REQUIRED` and `NOT_EXECUTED`.

## Model selection
- Primary: NVIDIA **Nemotron 3 Super** on **Nebius Token Factory**. Exact model ID and API base URL: **TBD after console verification**.
- Optional fast model: Nemotron 3 Nano if available to the team. Do not hardcode speculative model IDs.
- Validate actual JSON and tool-calling behavior on the configured endpoint; prefer schema validation over assuming a feature works.

## Inference credential isolation
Primary: OpenShell custom provider profile explicitly bound to the Nebius endpoint with credentials outside sandbox. Fallback: authenticated Ghost inference proxy outside sandbox, holding the real key. The sandbox only reaches approved destinations. Member A owns both configurations.

## Memory model
Structured explicit preference records: ID, category, value, source, time, status, superseded version and user correction. Retrieve only data relevant to the current authorized task; do not infer private attributes from unrelated content.

## Skills
Pre-approved, versioned typed workflows. Each declares skill ID, required tool names, input/output schemas and side-effect boundaries. Model cannot invent arbitrary executable tools.

## Scheduling
Member A's durable PostgreSQL job runner schedules Morning Brief. LangGraph checkpointing is for agent progress and is **not** a scheduler; B owns graph-resume behavior and task result handling.
