"""Authorization/owner review plus a separate, explicitly injected v1.3 capability."""

import json
import math
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import SecretStr, TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.agent_auth import get_authenticated_owner_context
from app.agent_schemas import IdentityModel, OwnerContext
from app.controlled_contracts import ControlledExecutionResult, ResumeExecution
from app.database import get_db
from app.gateway_contracts import (
    ApprovalResolution,
    ApprovalReview,
    ConsentCreate,
    OpaqueReference,
    OperationStatus,
    ToolRequest,
    ToolResponse,
)
from app.openapi_contracts import (
    ApprovalResolutionResult,
    ApprovalRevokeResult,
    ConsentGrantResult,
    ConsentRevokeResult,
    PendingApprovalList,
    request_body,
)
from app.services.agent_identity import AgentIdentityError, authenticated_task
from app.services.approvals import list_pending, owner_approval
from app.services.controlled_execution import ControlledExecution, get_controlled_execution
from app.services.operation_ledger import admit_operation, get_operation_status
from app.services.resource_catalog import ResourceCatalog, get_resource_catalog
from app.services.scoped_consent import (
    create_scoped_consent,
    revoke_scoped_consent,
)

router = APIRouter(tags=["authorization-only"])
execution_router = APIRouter(tags=["controlled-execution"])


def owner_response(value, status=200):
    # Preserve historical datetime encoding while adding typed response documentation.
    return JSONResponse(jsonable_encoder(value), status_code=status)


class GatewayProtocolError(Exception):
    def __init__(self, status_code, code, request_id=None):
        self.status_code, self.code, self.request_id = status_code, code, request_id


def error_response(status_code, code, request_id=None, *, execution_uncertain=False):
    return JSONResponse(
        status_code=status_code,
        headers={"WWW-Authenticate": "Bearer"} if status_code == 401 else None,
        content={
            "error_code": code,
            "message": "Request cannot be processed",
            "correlation_ref": f"http_{uuid4().hex}",
            "request_id": request_id,
            "audit_event_ref": None,
            "execution_uncertain": execution_uncertain,
        },
    )


async def protocol_error_handler(request: Request, exc: GatewayProtocolError):
    return error_response(exc.status_code, exc.code, exc.request_id)


def agent_token(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> SecretStr:
    if not authorization or not authorization.startswith("Bearer "):
        raise GatewayProtocolError(401, "AUTH_REQUIRED")
    if len(request.headers.getlist("authorization")) != 1:
        raise GatewayProtocolError(401, "AUTH_INVALID")
    return SecretStr(authorization[7:])


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise GatewayProtocolError(400, "DUPLICATE_JSON_FIELD")
        result[key] = value
    return result


def invalid_number(value):
    raise GatewayProtocolError(400, "MALFORMED_JSON")


def finite_number(value):
    result = float(value)
    if not math.isfinite(result):
        raise GatewayProtocolError(400, "MALFORMED_JSON")
    return result


def check_depth(value, depth=0):
    if depth > 8:
        raise GatewayProtocolError(422, "INVALID_REQUEST")
    if isinstance(value, dict):
        for item in value.values():
            check_depth(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            check_depth(item, depth + 1)


async def parse_body(request: Request, model):
    if request.headers.get("content-encoding"):
        raise GatewayProtocolError(415, "UNSUPPORTED_MEDIA_TYPE")
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise GatewayProtocolError(415, "UNSUPPORTED_MEDIA_TYPE")
    if sum(len(k) + len(v) + 4 for k, v in request.scope["headers"]) > 8192:
        raise GatewayProtocolError(413, "PAYLOAD_TOO_LARGE")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 256 * 1024:
            raise GatewayProtocolError(413, "PAYLOAD_TOO_LARGE")
        body.extend(chunk)
    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=invalid_number,
            parse_float=finite_number,
        )
        check_depth(value)
        return model.model_validate_json(json.dumps(value, allow_nan=False))
    except (UnicodeError, json.JSONDecodeError):
        raise GatewayProtocolError(400, "MALFORMED_JSON") from None
    except (ValueError, TypeError, RecursionError, ValidationError):
        raise GatewayProtocolError(422, "INVALID_REQUEST") from None


async def tool_body(request: Request) -> ToolRequest:
    return await parse_body(request, ToolRequest)


async def consent_body(request: Request) -> ConsentCreate:
    return await parse_body(request, ConsentCreate)


async def resolution_body(request: Request) -> ApprovalResolution:
    return await parse_body(request, ApprovalResolution)


async def empty_body(request: Request) -> IdentityModel:
    return await parse_body(request, IdentityModel)


@router.post(
    "/api/gateway/v1/execute",
    response_model=ToolResponse,
    openapi_extra=request_body(ToolRequest),
    summary="Authorize only; never executes a tool",
    description=(
        "Operation admission and optional durable owner review only. No execution or resume. "
        "Exact replays retain operation identity."
    ),
)
def authorize(
    token: Annotated[SecretStr, Depends(agent_token)],
    payload: Annotated[ToolRequest, Depends(tool_body)],
    db: Annotated[Session, Depends(get_db)],
    catalog: Annotated[ResourceCatalog, Depends(get_resource_catalog)],
):
    try:
        return admit_operation(db, token=token, request=payload, catalog=catalog)
    except AgentIdentityError as exc:
        return error_response(
            exc.status_code,
            exc.code,
            payload.request_id,
            execution_uncertain=exc.status_code == 503
            or getattr(exc, "execution_uncertain", False),
        )


@router.get("/api/gateway/v1/operations/{request_id}", response_model=OperationStatus)
def operation_status(
    request_id: str,
    token: Annotated[SecretStr, Depends(agent_token)],
    db: Annotated[Session, Depends(get_db)],
    catalog: Annotated[ResourceCatalog, Depends(get_resource_catalog)],
):
    try:
        TypeAdapter(OpaqueReference).validate_python(request_id, strict=True)
    except ValidationError:
        return error_response(422, "INVALID_REQUEST")
    try:
        return get_operation_status(db, token=token, request_id=request_id, catalog=catalog)
    except AgentIdentityError as exc:
        return error_response(
            exc.status_code,
            exc.code,
            request_id,
            execution_uncertain=exc.status_code == 503
            or getattr(exc, "execution_uncertain", False),
        )


@router.post(
    "/api/control/v1/tasks/{task_ref}/consents",
    status_code=201,
    response_model=ConsentGrantResult,
    openapi_extra=request_body(ConsentCreate),
)
def grant_consent(
    task_ref: str,
    owner: Annotated[OwnerContext, Depends(get_authenticated_owner_context)],
    payload: Annotated[ConsentCreate, Depends(consent_body)],
    db: Annotated[Session, Depends(get_db)],
    catalog: Annotated[ResourceCatalog, Depends(get_resource_catalog)],
):
    try:
        consent = create_scoped_consent(
            db, owner=owner, task_ref=task_ref, payload=payload, catalog=catalog
        )
        return owner_response(
            {
                "consent_ref": consent.consent_ref,
                "state": "ACTIVE",
                "expires_at": consent.expires_at,
            },
            201,
        )
    except AgentIdentityError as exc:
        return error_response(exc.status_code, exc.code)


@router.post(
    "/api/control/v1/tasks/{task_ref}/consents/{consent_ref}/revoke",
    response_model=ConsentRevokeResult,
    openapi_extra=request_body(IdentityModel),
)
def revoke_consent(
    task_ref: str,
    consent_ref: str,
    owner: Annotated[OwnerContext, Depends(get_authenticated_owner_context)],
    payload: Annotated[IdentityModel, Depends(empty_body)],
    db: Annotated[Session, Depends(get_db)],
):
    try:
        in_flight = revoke_scoped_consent(
            db, owner=owner, task_ref=task_ref, consent_ref=consent_ref
        )
        return owner_response({"state": "REVOKED", "in_flight": in_flight})
    except AgentIdentityError as exc:
        return error_response(exc.status_code, exc.code)


@router.get("/api/control/v1/approvals", response_model=PendingApprovalList)
def pending_approvals(
    task_ref: str,
    owner: Annotated[OwnerContext, Depends(get_authenticated_owner_context)],
    db: Annotated[Session, Depends(get_db)],
    catalog: Annotated[ResourceCatalog, Depends(get_resource_catalog)],
):
    try:
        return owner_response(list_pending(db, owner=owner, task_ref=task_ref, catalog=catalog))
    except AgentIdentityError as exc:
        return error_response(exc.status_code, exc.code)


@router.get("/api/control/v1/approvals/{approval_ref}", response_model=ApprovalReview)
def review_approval(
    approval_ref: str,
    owner: Annotated[OwnerContext, Depends(get_authenticated_owner_context)],
    db: Annotated[Session, Depends(get_db)],
    catalog: Annotated[ResourceCatalog, Depends(get_resource_catalog)],
):
    try:
        result = owner_approval(db, owner=owner, approval_ref=approval_ref, catalog=catalog)
        return JSONResponse(result.model_dump(mode="json"), headers={"Cache-Control": "no-store"})
    except AgentIdentityError as exc:
        return error_response(exc.status_code, exc.code)


@router.post(
    "/api/control/v1/approvals/{approval_ref}/resolve",
    response_model=ApprovalResolutionResult,
    openapi_extra=request_body(ApprovalResolution),
)
def resolve_approval(
    approval_ref: str,
    owner: Annotated[OwnerContext, Depends(get_authenticated_owner_context)],
    payload: Annotated[ApprovalResolution, Depends(resolution_body)],
    db: Annotated[Session, Depends(get_db)],
    catalog: Annotated[ResourceCatalog, Depends(get_resource_catalog)],
):
    try:
        return owner_response(
            owner_approval(
                db,
                owner=owner,
                approval_ref=approval_ref,
                resolution=payload.resolution,
                catalog=catalog,
            )
        )
    except AgentIdentityError as exc:
        return error_response(exc.status_code, exc.code)


@router.post(
    "/api/control/v1/approvals/{approval_ref}/revoke",
    response_model=ApprovalRevokeResult,
    openapi_extra=request_body(IdentityModel),
)
def revoke_approval(
    approval_ref: str,
    owner: Annotated[OwnerContext, Depends(get_authenticated_owner_context)],
    payload: Annotated[IdentityModel, Depends(empty_body)],
    db: Annotated[Session, Depends(get_db)],
    catalog: Annotated[ResourceCatalog, Depends(get_resource_catalog)],
):
    try:
        return owner_response(
            owner_approval(db, owner=owner, approval_ref=approval_ref, revoke=True, catalog=catalog)
        )
    except AgentIdentityError as exc:
        return error_response(exc.status_code, exc.code)


async def execution_body(request: Request):
    return await parse_body(request, ResumeExecution)


@execution_router.post(
    "/api/gateway/v1/operations/{request_id}/resume",
    response_model=ControlledExecutionResult,
    openapi_extra=request_body(ResumeExecution),
)
def resume_execution(
    request_id: str,
    token: Annotated[SecretStr, Depends(agent_token)],
    payload: Annotated[ResumeExecution, Depends(execution_body)],
    db: Annotated[Session, Depends(get_db)],
    catalog: Annotated[ResourceCatalog, Depends(get_resource_catalog)],
    capability: Annotated[ControlledExecution | None, Depends(get_controlled_execution)],
):
    try:
        TypeAdapter(OpaqueReference).validate_python(request_id, strict=True)
    except ValidationError:
        return error_response(422, "INVALID_REQUEST", request_id)
    try:
        if capability is None:
            with authenticated_task(db, token=token, task_ref=None):
                pass
            return error_response(403, "ACTION_DISABLED", request_id)
        result = capability.resume(
            db, token=token, request_id=request_id, hint=payload.resume_ref, catalog=catalog
        )
        return JSONResponse(result.model_dump(mode="json"), headers={"Cache-Control": "no-store"})
    except ValidationError:
        return error_response(503, "GATEWAY_UNAVAILABLE", request_id, execution_uncertain=True)
    except AgentIdentityError as exc:
        return error_response(
            exc.status_code,
            exc.code,
            request_id,
            execution_uncertain=exc.status_code == 503
            or getattr(exc, "execution_uncertain", False),
        )
