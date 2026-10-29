# Architecture decisions and unresolved questions

## Agreed v2.1 choices
- Python 3.12 + FastAPI + Pydantic v2.
- LangGraph personal agent.
- NVIDIA Nemotron 3 Super via Nebius Token Factory; Nano optional after confirmation.
- NVIDIA OpenShell sandbox with pinned compatible version on suitable Ubuntu VM.
- Trusted, deterministic Member A consent gateway.
- PostgreSQL + SQLAlchemy + Alembic.
- Minimal Postgres durable job runner, separate from LangGraph checkpoints.
- Mailpit test email, SSE to frontend, Caddy TLS.
- React/Next.js frontend built by Member C.
- Policy Advisor integration optional, not a blocker.
- Use provider profile bound to Nebius endpoint or trusted proxy fallback; **not yet verified**.

## Unknowns — explicit sign-off required
| ID | Question | Owner | Deadline |
|---|---|---|---|
| Q1 | Exact Nemotron model IDs/base URL and structured-output support | B | B1 |
| Q2 | Is Nano available in team account? | B | B1 |
| Q3 | Pinned OpenShell version, kernel/Docker checks, blocked network/file tests | A | Oct 14 |
| Q4 | Secure credential routing: custom provider or Ghost proxy | A+B | Oct 14 |
| Q5 | Authenticated gateway transport and identity binding | A+B | B2 |
| Q6 | Final tool payloads, approval and execution enums | A+B | B2 |
| Q7 | Memory and skill persistence tables/APIs | A+B | B3 |
| Q8 | Morning Brief scheduler triggering + deduplication behavior | A+B | B4 |
| Q9 | Frontend event/task payload contract | A+B+C | B2 |
| Q10 | Policy Advisor proposal approval and live reload behavior | A | Stretch |

## Main risks and mitigations
**Sandbox integration delay:** enforce Oct 14 go/no-go; do not silently extend. **Overlap with OpenShell:** focus on personal semantic consent, not reimplementing generic firewall. **Wrong hackathon track fit:** show three useful assistant skills and memory. **Contract mismatch:** agree JSON fixtures and run contract tests. **Unsafe demo:** use synthetic docs and Mailpit. **Unstable inference:** bounded retries, model output validation and explicit error states. **Time:** ship one core vertical slice before polishing UI.

## Decisions log (update as evidence arrives)
| Date | Decision | Evidence | Owner |
|---|---|---|---|
| Oct 12, 2026 | v2.1 architecture chosen; runtime not yet proven | Team planning | All |
