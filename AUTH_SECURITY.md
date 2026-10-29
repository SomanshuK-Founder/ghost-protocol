# Authentication and browser security

Step 44B accepted offline: local-only server-managed sessions, HttpOnly SameSite=Strict cookie, HTTPS Secure policy, 900-second idle and 3600-second absolute expiry, single-use operator-issued pairing secret with 120-second lifetime, CSRF bound to session, exact Origin/Host checks, forwarded-header rejection, logout/restart invalidation.

## Rules
- Pairing disabled by default; no hardcoded demo password or browser-issued trusted credentials.
- The server resolves owner; never send a forged owner ID or trust client-side owner selection.
- Browser must never see internal bearer agent credentials, Nebius keys, `.env` values, internal dispatcher tokens or SQLite checkpoints.
- Session cookies are not to be persisted to localStorage; CSRF token delivery must follow actual route implementation.
- No wildcard CORS, no bypassing Host/Origin validation, no tunnel/sharing of local-only pairing.
- Distinguish session timeout from approval expiry; a timed-out browser session cannot make further decisions.
- Clear sensitive client-side draft state on logout or expiry.
- Never render raw document text or email bodies in audit UI.
- Include browser security tests for CSRF failure, cross-origin requests, replay, expiry, logout, wrong-owner access and insufficient scope.

## Deployment guard
A public working demo URL is required by the submission checklist; present local backend through a public tunnel ONLY after separate security review of replacement auth, TLS, exposure, trusted credential access and data isolation. Safer deadline fallback is a **separate synthetic public demo**, clearly labeled simulation, with no access to the private backend. It is not equivalent to a live hosted backend.
