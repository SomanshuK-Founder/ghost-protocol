import hmac

from fastapi import Header, HTTPException

from app.config import get_settings


def require_bearer(authorization: str | None = Header(default=None)) -> str:
    configured = get_settings().api_bearer_token
    if not configured:
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    token = authorization[7:]
    # Reserve the agent namespace even if an operator misconfigures the owner secret.
    if token.startswith("gpa_") or not hmac.compare_digest(token.encode(), configured.encode()):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return "local-user"
