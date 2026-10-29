"""v1.2 owner-only workflow control, never execution."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.agent_auth import get_authenticated_owner_context
from app.agent_schemas import OwnerContext
from app.database import get_db
from app.openapi_contracts import request_body
from app.routes.gateway import error_response, parse_body
from app.services.agent_identity import AgentIdentityError
from app.services.resource_catalog import ResourceCatalog, get_resource_catalog
from app.services.workflow_resume import workflow_checkpoint
from app.workflow_contracts import (
    WorkflowIdentity,
    WorkflowPause,
    WorkflowPrepare,
    WorkflowSnapshot,
)

router = APIRouter(prefix="/api/control/v1/workflow-checkpoints", tags=["workflow-only"])


def _call(db, owner, catalog, command, payload=None, binding_ref=None):
    try:
        return workflow_checkpoint(
            db,
            owner=owner,
            command=command,
            payload=payload,
            binding_ref=binding_ref,
            catalog=catalog,
        )
    except AgentIdentityError as exc:
        return error_response(exc.status_code, exc.code)


async def prepare_body(request: Request):
    return await parse_body(request, WorkflowPrepare)


async def pause_body(request: Request):
    return await parse_body(request, WorkflowPause)


async def identity_body(request: Request):
    return await parse_body(request, WorkflowIdentity)


Owner = Annotated[OwnerContext, Depends(get_authenticated_owner_context)]
Database = Annotated[Session, Depends(get_db)]
Catalog = Annotated[ResourceCatalog, Depends(get_resource_catalog)]


@router.post("", response_model=WorkflowSnapshot, openapi_extra=request_body(WorkflowPrepare))
def prepare(
    owner: Owner,
    db: Database,
    catalog: Catalog,
    payload: Annotated[WorkflowPrepare, Depends(prepare_body)],
):
    return _call(db, owner, catalog, "prepare", payload)


@router.get("/{binding_ref}", response_model=WorkflowSnapshot)
def status(binding_ref: str, owner: Owner, db: Database, catalog: Catalog):
    return _call(db, owner, catalog, "get", binding_ref=binding_ref)


@router.post(
    "/{binding_ref}/pause",
    response_model=WorkflowSnapshot,
    openapi_extra=request_body(WorkflowPause),
)
def pause(
    binding_ref: str,
    owner: Owner,
    db: Database,
    catalog: Catalog,
    payload: Annotated[WorkflowPause, Depends(pause_body)],
):
    return _call(db, owner, catalog, "pause", payload, binding_ref)


@router.post(
    "/{binding_ref}/admit",
    response_model=WorkflowSnapshot,
    openapi_extra=request_body(WorkflowIdentity),
)
def admit(
    binding_ref: str,
    owner: Owner,
    db: Database,
    catalog: Catalog,
    payload: Annotated[WorkflowIdentity, Depends(identity_body)],
):
    return _call(db, owner, catalog, "admit", payload, binding_ref)


@router.post(
    "/{binding_ref}/claim",
    response_model=WorkflowSnapshot,
    openapi_extra=request_body(WorkflowIdentity),
)
def claim(
    binding_ref: str,
    owner: Owner,
    db: Database,
    catalog: Catalog,
    payload: Annotated[WorkflowIdentity, Depends(identity_body)],
):
    return _call(db, owner, catalog, "claim", payload, binding_ref)


@router.post(
    "/{binding_ref}/complete",
    response_model=WorkflowSnapshot,
    openapi_extra=request_body(WorkflowIdentity),
)
def complete(
    binding_ref: str,
    owner: Owner,
    db: Database,
    catalog: Catalog,
    payload: Annotated[WorkflowIdentity, Depends(identity_body)],
):
    return _call(db, owner, catalog, "complete", payload, binding_ref)
