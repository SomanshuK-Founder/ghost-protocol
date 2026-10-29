# DESIGN.MD — Ghost Protocol visual direction

## Concept: **The Control Room, not another chatbot**
A premium personal-AI operations console where humans stay in command. The memorable centerpiece is a **live-looking, data-backed Decision Rail** — a horizontal/vertical visualization of a task's actual events: Request → Plan → Authorization → Human decision → Safe stop → Recorded outcome. The rail is strictly bound to API state; never animate a fake successful dispatch.

## The visual signature
- **Dark graphite navigation shell**, deep midnight content, calm off-white typography.
- **Electric iris** highlights selections and active planning; **ice cyan** indicates verified/read-only trace; warm amber for action requiring approval; muted red for denied/revoked/uncertain. No rainbow gradients.
- **Hero moment:** task detail opens with a bold task name on the left and a large editorial-style Decision Rail on the right. Each node shows real timestamps, decision source and trace link. This is the central screenshot for the demo video.
- Technical credibility is conveyed through polished alignment, restrained glow and crisp type, NOT Matrix rain, skull motifs, blinking terminals, fake GPU gauges, or generic AI chatbot bubbles.

## Color tokens (starting point; verify WCAG contrast)
| Token | Hex | Role |
|---|---|---|
| `canvas` | `#090C13` | page backdrop |
| `panel` | `#111723` | main surfaces |
| `panel-raised` | `#182131` | elevated surfaces |
| `divider` | `#2A3549` | hairline strokes |
| `text` | `#F2F5FB` | main content |
| `muted` | `#A6B3C7` | secondary labels |
| `iris` | `#A78BFA` | active focus / primary action |
| `cyan` | `#63D8E8` | trace / data provenance |
| `amber` | `#F3BC69` | pending human approval |
| `danger` | `#F38B9B` | rejected / failed / uncertainty |
| `success` | `#72D9B1` | verified completed safe state |

Use color plus icon + label (never color alone). Restrict accent use to meaningful state changes. Ensure body text is comfortably legible.

## Typography
- Display/headline: **Space Grotesk** (or locally available licensed fallback). Use medium weight; strong short headlines, no stretched tracking.
- Body/UI: **Inter** or system sans, 14–16px desktop depending on density.
- Monospace metadata: **IBM Plex Mono** / system monospace for IDs, timestamps and signatures only, not entire layouts.
- Scale: page title 30–40px; section 20–24px; card heading 15–18px; body 14–16px; micro-label >=12px.
- Prefer locally bundled or responsibly hosted fonts; never block app rendering on a Google Fonts request.

## Layout rules
- Desktop ≥1280px: 248px left navigation, top utility bar 64px, 12-column content grid, max content width approx 1480px.
- Tablet: collapsible left rail 72px; main content minimum 0 (avoid overflow).
- Mobile <768px: compact top bar + drawer navigation, single column, minimum 44px touch targets.
- Spacing scale 4/8/12/16/24/32/48/64. Panels 12–16px radius; pills full-round; form controls 10–12px. Avoid identical heavy cards on every surface.
- Design for **1366×768** screen recording first, then test 1920×1080, 768px and 390px.

## Primary screen visual composition
```text
┌─ GHOST / navigation ─┬──────────────────────────────────────────────────────┐
│ Overview            │  Good evening                     LOCAL · SIMULATED │
│ Tasks               │  Your agent, under your control                     │
│ Approvals  [2]      │  [ Create task ]      [ Pending approvals ]        │
│ Activity            │                                                      │
│ Documents           │  FOCUSED TASK                      EVENT TRACE        │
│ Settings            │  "Summarize my day"               Request ●── Plan ● │
│                     │  Planning details                 Review ◉── Stop ● │
│                     │                                                      │
│                     │  Pending approvals / latest operations              │
└─────────────────────┴──────────────────────────────────────────────────────┘
```
Do not hardcode `[2]` or other counts: derived data only.

## Distinctive components
1. **Decision Rail:** owner-visible, immutable-seeming event sequence backed by actual event records; show *NOT VERIFIED* for unavailable stages.
2. **Approval Sheet:** highly readable action, scope, reason, resource, expiry, explicit Approve/Reject, confirmation for consequential choices.
3. **Provenance Chip:** `LOCAL MOCK`, `SIMULATED READ`, `MAILPIT CAPTURE`, `LIVE MODEL (verified evidence only)`, `NOT VERIFIED`, `UNKNOWN`.
4. **Audit Lens:** compact detail panel pairing friendly explanation with copyable operation/audit reference.
5. **Command composer:** high-quality text input with example tasks, constraints, disabled state when local auth is off.

## Motion discipline
- One orchestrated page-enter transition <=350ms; 150–200ms hover/focus feedback; rail updates transition only on *actual* state changes.
- `prefers-reduced-motion` disables decorative motion. Never autoplay fake thinking, fake progress, or fake data.
- No infinite spinners: show a bounded pending state and explanatory recovery option.

## Copy / labels
Use precise language: “Request approval”, “Awaiting decision”, “Continue workflow”, “Safe stopped”, “Recorded outcome”, “Reconciliation required”. Avoid “Autonomously executed”, “100% safe”, “Sandbox secured” until proven. Keep headings sentence case.

## UX quality criteria
- 4.5:1 contrast for standard text, visible keyboard focus, semantic HTML, accessible dialogues, full tab navigation, focus restoration, 44px touch targets, honest empty/loading/error states.
- Responsive evidence: screenshots at desktop and mobile. No text clipping, overflow or inaccessible dialogs.
- Give every primary action one clear visual priority. Never allow animation to delay an urgent approval or error.

## Aesthetic review pass
Before shipping, compare screenshots against these anti-patterns: generic three-metric hero, stock space images, gratuitous blur/glass, dense identical rounded-card grid, random bright neon, placeholder lorem ipsum, and status rendered using color alone. If the result resembles a template, refine its information hierarchy first.
