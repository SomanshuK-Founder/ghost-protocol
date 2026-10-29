# Public demo strategy — security boundary

## Situation
The accepted application uses disabled-by-default, **local-only one-use pairing**. The backend carries trusted service credentials; it is not reviewed for public deployment. Direct ngrok or exposing localhost to strangers is **not approved**.

## Deadline-safe option
Publish a **separate static interactive synthetic demo** at a public URL, with a visible label: “Interactive product preview — synthetic data; no backend execution.” The click path can demonstrate pre-authored state transitions, but it must not claim to be a live remote Ghost backend. Keep a separate local backend-connected recorded demo for proof of implementation.

## Better option if time and review allow
A fully reviewed hosted backend with proper public authentication, HTTPS, sandbox/data isolation, rate limiting, credential management and runtime tests. This cannot be assumed ready from offline acceptance.

## Demo link checklist
- Accessible publicly in incognito.
- No secrets/source maps with credentials.
- Clear simulation banner and working interactions.
- No exposed pairing code or local trusted endpoint.
- Form submission instructions and video distinguish preview from live implementation.
