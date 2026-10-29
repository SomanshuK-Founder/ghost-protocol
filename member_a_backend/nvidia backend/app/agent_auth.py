"""Agent-only dependency for future routes with a task_ref path parameter."""

from typing import Annotated

from fastapi import Depends, Header, HTTPException
from pydantic import SecretStr
from sqlalchemy.orm import Session

from app.agent_schemas import AuthenticatedAgentContext, OwnerContext
from app.database import get_db
from app.security import require_bearer
from app.services.agent_identity import AgentIdentityError, validate_agent_credential


def get_authenticated_owner_context(
    owner_id: Annotated[str, Depends(require_bearer)],
) -> OwnerContext:
    return OwnerContext(owner_id=owner_id)


def get_authenticated_agent_context(
    task_ref: str,
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> AuthenticatedAgentContext:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="AUTH_REQUIRED",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return validate_agent_credential(
            db,
            token=SecretStr(authorization[7:]),
            task_ref=task_ref,
        )
    except AgentIdentityError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.code,
            headers={"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None,
        ) from None
