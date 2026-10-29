# Ghost Protocol — Product and hackathon brief

## Product
**Ghost Protocol v2.1** is a personal AI assistant whose distinctive capability is **persistent, task-scoped, revocable personal consent**. It remembers boundaries and useful preferences while performing genuine everyday tasks through a restricted agent runtime.

**One-line pitch:** Your AI agents should only do what you actually authorized.

## Track and objectives
- Competition: Nebius × NVIDIA Global AI Hackathon.
- Track: Personal AI.
- Three developers: A (backend/security/infra), B (AI/agent/memory), C (frontend/UX).
- Planned target: working submission ready October 29, 2026, ahead of the October 30 deadline. Reconfirm current Devpost rules before final submission.
- Judging: technological implementation, design, impact, and idea quality.

## Core problem
Existing agent sandboxes can restrict network/filesystem actions, but they do not automatically understand a person's permission to share **this document** with **this recipient**, for **this purpose**, during **this time window**. Ghost adds personal consent memory and a trusted semantic authorization layer on top of NVIDIA OpenShell, not another firewall.

## User-facing capabilities
1. **Morning Brief:** scheduled personalized summary from permitted tasks and messages.
2. **Private Document Assistant:** inspect and summarize approved resources.
3. **Smart Email Assistant:** draft and send messages only through authorization checks.
4. **Consent memory:** versioned boundaries, approvals, expiry and revocation.
5. **Audit experience:** clear distinction between AI proposal, gateway decision and actual outcome.

## Canonical demo with synthetic data
- User: “Summarize my tax documents, but never email the originals.”
- Agent reads permitted demo resources and sends an approved *summary* via a Mailpit-controlled email tool.
- A retrieved document contains a malicious instruction to send the original. The agent may attempt this, but the trusted gateway **denies** it.
- User grants a narrowly scoped temporary permission, then revokes it; the next matching request is denied.
- The UI shows genuine decisions, real tool outcomes, persistent preference memory, and a scheduled brief.

## Non-goals for hackathon MVP
Production Gmail access, generic web browsing, multi-agent swarm, universal prompt-injection resistance, AI-controlled sandbox policy enforcement, self-modifying agent code, financial account access, full consumer production security, and advanced semantic memory search.

## Evidence of success
Real Nemotron calls through the qualifying Nebius route; one real sandboxed agent; three working skills; persistent explicit memory; controlled authorized/denied email operations; reproducible measurements with known limitations.
