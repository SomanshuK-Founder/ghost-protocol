# Recommended Codex UI/UX skills

Use a small, complementary set; don't install many overlapping design instructions. **Review each repository and its SKILL.md/scripts first.** Pin the revision when possible; avoid shell scripts from unknown forks.

## Recommended

1. **`frontend-design` by Anthropic** — deliberate art direction, typography and avoidance of generic AI SaaS templates. GitHub: https://github.com/anthropics/skills/tree/main/skills/frontend-design
2. **`ui-ux-pro-max`** — design intelligence and UX rules. Codex-focused fork: https://github.com/Rpeng666/ui-ux-pro-max-skill-codex (includes install script; review it before running). Alternative two-skill pack: https://github.com/hitbullets/codex-skills
3. **`web-design-guidelines` by Vercel Labs** — final accessibility/interaction critique: https://github.com/vercel-labs/agent-skills/tree/main/skills/web-design-guidelines

## Installation option: skills CLI (after reviewing repository)
From repo root in PowerShell, with compatible Node installed:
```powershell
npx skills add https://github.com/anthropics/skills --skill frontend-design
npx skills add https://github.com/vercel-labs/agent-skills --skill web-design-guidelines
```
Select Codex and project-local install when prompted. For UI/UX Pro Max, use repo installation instructions after checking its install script (the fork writes to `.codex/skills`; Codex versions can use different skill directories). Ensure `SKILL.md` is in the path recognized by *your* Codex configuration, then restart the session and list installed skills. Do not run an arbitrary install script merely because GitHub says so.

## Recommended use sequence
1. Ask `frontend-design` to propose two creative directions grounded in `design.md`, then select the Control Room direction.
2. Ask `ui-ux-pro-max` to audit token hierarchy, accessibility, forms, responsive structure, nav.
3. Build functional screens and take real browser screenshots.
4. Ask Vercel `web-design-guidelines` to review concrete source files and report file/line-level defects.
5. Iterate screenshots at desktop and mobile until legible and distinctive.

## Guardrail
Skills provide suggestions, not authority to change API/auth/security; they must obey `design.md`, the generated OpenAPI, and project AGENTS.md.
