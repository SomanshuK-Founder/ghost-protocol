# Product scope and truthful capability matrix

Ghost Protocol is a **Personal AI safety and authorization console**, not a general tool-executing chatbot. User tasks are planned through LangGraph, checked by trusted authorization, presented for review, and traceable through durable records. For the accepted offline demo, planning is deterministic/mock and protected actions are simulated or routed to approved local test transports.

| Capability | Offline demo stance | UI treatment |
|---|---|---|
| Local owner pairing/session | Offline accepted; disabled by default | local operator-controlled pairing |
| Task CRUD-like create/list/detail | Offline accepted | usable screens |
| Bounded LangGraph planning | Deterministic mock in new browser flow | `SIMULATED PLANNING` label |
| Approval decision/revocation | Offline accepted | real local state changes |
| Workflow continuation | Stops at `SAFE_STOPPED` | explicit safe stop |
| Operation history/audit | Owner-scoped projections | real stored records only |
| Catalog metadata | Owner scoped, six-field allowlist | no document contents |
| Email | Fake SMTP / local Mailpit tested earlier | no claim of public send |
| Nemotron via Nebius | Four earlier live Super probes verified, not new UI E2E | cite separately in demo narration |
| OpenShell native sandbox | Deferred / not verified | `NOT VERIFIED` in developer status; no enforcement claims |
| MySQL migration 0012/0013 | Not applied in actual runtime | local SQLite demo only |
| Public authentication | Not implemented or approved | no public exposure |

## Out of scope for deadline
No cloud production deployment of trusted backend, no real public SMTP, no autonomous tool chaining, no unrestricted document reading, no fake generated metrics, no full security-certification claim.

## Demo objective
In <3 minutes, reveal an apparently simple task turning into explainable planning, explicit human control, and an auditable final safe stop. Demonstrate one denied/replayed case. Show Nebius/NVIDIA usage honestly with recorded live-planning proof, distinguish it from local mocked UI.
