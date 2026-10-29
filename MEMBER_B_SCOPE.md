# Member B — ownership and boundaries

You are the **AI/ML + Agents + Personal Memory** developer. Start independently using mocks; do not wait for Member A or C to finish.

## Owned deliverables
- Nebius Token Factory model adapter for NVIDIA Nemotron 3 Super, with optional Nano after live validation.
- Configurable endpoint, model IDs, timeouts, structured output validation, token/latency telemetry.
- LangGraph personal agent: planning, tool selection, tool response handling, approval pause/resume, error handling.
- Intent-to-*proposed-consent* extraction (never final authorization).
- Explicit, user-correctable, task-relevant personal memory and repository abstraction.
- Three named skill definitions and implementations.
- Strict mock gateway for development with the same contracts as Member A's trusted gateway.
- Synthetic adversarial fixtures, evaluations and reproducible reports.

## Member A owns — do not duplicate
FastAPI public endpoints, deterministic policy decisions, trusted tool gateway and execution, PostgreSQL schema and Alembic migrations, real email adapter/Mailpit, durable scheduled-job runner, OpenShell host/runtime/provider setup, actual credential brokering, deployment, authentication, authoritative audit log/SSE.

## Member C owns
Next.js dashboard, React Flow visualization, chat/task pages, consent and memory interfaces, SSE rendering, UX and demo visuals. Provide typed events and sample payloads, not frontend code.

## Suggested directories (adapt to existing repo)
```
backend/app/agent/            LangGraph agent, state, prompts and tool adapters
backend/app/llm/              Nebius client, typed outputs, telemetry
backend/app/memory/           Memory interface and service
backend/app/skills/           Skill registry and three skills
backend/tests/agent/          Agent and memory tests
backend/tests/evaluations/    Adversarial fixtures and runner
```
Avoid `backend/app/models/` if Member A uses it for SQLAlchemy ORM.

## Definition of done
The agent uses Nemotron to complete legitimate tasks, preserves explicit preferences across sessions, responds correctly to denial/approval/expiry, never bypasses the trusted gateway, and records honest tool/model outcomes.
