# Acceptance and QA checklist

## Functional
- [ ] TypeScript strict build passes.
- [ ] All 19 browser operations mapped by actual OpenAPI operation ID.
- [ ] No unknown response fields invented in code.
- [ ] Pairing enabled only by local operator; 401/expiry/logout work.
- [ ] Session/CSRF/Origin protections remain active in full browser run.
- [ ] Task created and persists after local restart.
- [ ] Planning presents mock provenance and bounded state.
- [ ] Approval, reject, revoke and continuation respect authority and safe stop.
- [ ] UNKNOWN prevents blind retry.
- [ ] Audit timeline uses stored events; no fake timestamps.
- [ ] Six-field catalog allowlist obeyed.
- [ ] No trusted token/secret in bundle, logs or network response.

## Visual
- [ ] 1366×768 screenshot deliberate and readable.
- [ ] 1920×1080 and 390×844 checked; no horizontal overflow.
- [ ] Focus visible, tab order correct, dialogs accessible.
- [ ] Contrast meets WCAG AA where applicable.
- [ ] Reduced-motion honored.
- [ ] Loading/empty/error states polished, no silent failures.
- [ ] Demo capture legible at YouTube resolution.

## Backend limitations
- [ ] Real MySQL migrations 0012/0013 explicitly unverified.
- [ ] Native OpenShell sandbox enforcement explicitly unverified.
- [ ] Live Nemotron through new application flow not claimed unless reverified.
- [ ] Mailpit not described as public email.

## Required evidence
Tests, screenshots, browser recordings, console/network cleanliness, exact app start commands, versioned OpenAPI, security scan, provenance label review, full demo rehearsal.
