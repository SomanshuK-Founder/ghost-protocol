"""A09-A19 only: owner review, metadata continuation and safe observation."""

import asyncio
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from app.agent_schemas import IdentityModel, Reference
from app.application_contracts import (
    AppFailure,
    ApplicationError,
    AppPage,
    ApprovalDecision,
    ApprovalDetail,
    ApprovalList,
    ApprovalMutation,
    AppSuccess,
    CancelResult,
    DocumentMetadata,
    OperationList,
    OperationView,
    TimelineItem,
    WorkflowView,
)
from app.browser_auth import PREFIX, BrowserAuthError
from app.database import get_db
from app.gateway_contracts import OpaqueReference
from app.routes.application_tasks import (
    OwnerRoute,
    authenticated,
    body,
    fresh,
    response,
    typed_body,
)
from app.services import application_interfaces as service
from app.services.application_host import continuation_callback
from app.services.application_tasks import command_identity

router = APIRouter(
    prefix=PREFIX,
    route_class=OwnerRoute,
    tags=["application-interfaces"],
    responses={
        code: {"model": AppFailure}
        for code in (400, 401, 403, 404, 409, 413, 415, 422, 429, 503, 504)
    },
)
Database = Annotated[Session, Depends(get_db)]


def query(request, *, task=False, page=False):
    params = request.query_params
    keys = ({"task_ref"} if task else set()) | ({"limit", "cursor"} if page else set())
    if any(k not in keys or len(params.getlist(k)) != 1 for k in params):
        raise BrowserAuthError("INVALID_REQUEST")
    if task:
        from pydantic import TypeAdapter

        try:
            return TypeAdapter(Reference).validate_python(params["task_ref"], strict=True)
        except (KeyError, ValueError):
            raise BrowserAuthError("INVALID_REQUEST") from None
    raw = params.get("limit", "20")
    if (
        len(raw) > 2
        or not raw.isascii()
        or not raw.isdecimal()
        or str(int(raw)) != raw
        or not 1 <= int(raw) <= 50
    ):
        raise BrowserAuthError("INVALID_REQUEST")
    cursor = params.get("cursor")
    if cursor is not None and (not cursor or len(cursor) > 2048):
        raise ApplicationError(400, "INVALID_CURSOR")
    return int(raw), cursor


PAGE_PARAMETERS = {
    "parameters": [
        {
            "name": "limit",
            "in": "query",
            "schema": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
        },
        {
            "name": "cursor",
            "in": "query",
            "schema": {"type": "string", "minLength": 1, "maxLength": 2048},
        },
    ]
}


@router.get(
    "/approvals",
    response_model=AppSuccess[ApprovalList],
    openapi_extra={
        "parameters": [
            {
                "name": "task_ref",
                "in": "query",
                "required": True,
                "schema": {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},
            }
        ]
    },
)
def approvals(request: Request, db: Database):
    owner = authenticated(request, allow_query=True)
    return response(service.approvals(db, owner, query(request, task=True)))


@router.get("/approvals/{approval_ref}", response_model=AppSuccess[ApprovalDetail])
def approval_detail(approval_ref: OpaqueReference, request: Request, db: Database):
    return response(
        service.approval_detail(
            db, authenticated(request), approval_ref, request.app.state.application_runtime
        )
    )


async def mutation(request, db, kind, target, model):
    owner = authenticated(request)
    payload = await body(request, model)
    identity = command_identity(request, payload, owner)
    fresh(request)
    result, replay = service.mutate(
        db, owner, kind, target, payload, identity, request.app.state.application_runtime
    )
    return response(result, replayed=replay)


@router.post(
    "/approvals/{approval_ref}/decision",
    response_model=AppSuccess[ApprovalMutation],
    openapi_extra=typed_body(ApprovalDecision),
)
async def decision(approval_ref: OpaqueReference, request: Request, db: Database):
    return await mutation(request, db, "APPROVAL_DECISION", approval_ref, ApprovalDecision)


@router.post(
    "/approvals/{approval_ref}/revoke",
    response_model=AppSuccess[ApprovalMutation],
    openapi_extra=typed_body(IdentityModel),
)
async def revoke(approval_ref: OpaqueReference, request: Request, db: Database):
    return await mutation(request, db, "APPROVAL_REVOKE", approval_ref, IdentityModel)


@router.post(
    "/tasks/{task_ref}/cancel",
    response_model=AppSuccess[CancelResult],
    openapi_extra=typed_body(IdentityModel),
)
async def cancel(task_ref: Reference, request: Request, db: Database):
    return await mutation(request, db, "CANCEL", task_ref, IdentityModel)


@router.get("/tasks/{task_ref}/workflow", response_model=AppSuccess[WorkflowView])
def workflow(task_ref: Reference, request: Request, db: Database):
    return response(
        service.workflow(
            db, authenticated(request), task_ref, request.app.state.application_runtime
        )
    )


@router.post(
    "/tasks/{task_ref}/workflow/continue",
    response_model=AppSuccess[WorkflowView],
    openapi_extra=typed_body(IdentityModel),
)
async def continuation(task_ref: Reference, request: Request, db: Database):
    try:
        async with asyncio.timeout(18):
            return await continue_command(task_ref, request, db)
    except TimeoutError:
        raise ApplicationError(
            504,
            "COMMAND_TIMEOUT",
            command_ref=getattr(request.state, "continuation_command", None),
            uncertain=True,
        ) from None


async def continue_command(task_ref, request, db):
    owner = authenticated(request)
    payload = await body(request, IdentityModel)
    identity = command_identity(request, payload, owner)
    runtime = request.app.state.application_runtime
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)

    async def transact(function, *args, **kwargs):
        def invoke():
            with factory() as session:
                return function(session, *args, **kwargs)

        return await asyncio.to_thread(invoke)

    prior, replay = await transact(service.continuation_claim, owner, task_ref, identity, runtime)
    if replay:
        return response(prior, replayed=True)
    command_ref = f"cmd_{uuid4().hex}"
    fresh(request)
    runtime.reserve(command_ref, task_ref)
    request.state.continuation_command = command_ref
    claimed, uncertain = False, False
    try:
        binding_ref, _ = await transact(
            service.continuation_claim, owner, task_ref, identity, runtime, command_ref
        )
        claimed = True

        async def callback(data):
            fresh(request)
            return await continuation_callback(
                data, owner=owner, task_ref=task_ref, binding_ref=binding_ref, factory=factory
            )

        observation = await runtime.run(
            task_ref=task_ref,
            binding_ref=binding_ref,
            user_request=None,
            action=None,
            purpose=None,
            arguments=None,
            credential=None,
            callback=callback,
        )
        result = await transact(
            service.continuation_finish,
            owner,
            task_ref,
            command_ref,
            runtime,
            observation=observation,
        )
        return response(result)
    except asyncio.CancelledError:
        uncertain = True
        raise
    except Exception as exc:
        if not claimed:
            raise
        failure = (
            exc
            if isinstance(exc, ApplicationError)
            else ApplicationError(503, "HOST_UNAVAILABLE", uncertain=True)
        )
        uncertain = failure.uncertain
        await transact(
            service.continuation_finish, owner, task_ref, command_ref, runtime, failure=failure
        )
        raise ApplicationError(
            failure.status, failure.code, command_ref=command_ref, uncertain=uncertain
        ) from None
    finally:
        runtime.release(uncertain=uncertain)


@router.get("/tasks/{task_ref}/operations", response_model=AppSuccess[OperationList])
def operations(task_ref: Reference, request: Request, db: Database):
    return response(
        service.operations(
            db, authenticated(request), task_ref, request.app.state.application_runtime
        )
    )


@router.get(
    "/tasks/{task_ref}/operations/{operation_ref}", response_model=AppSuccess[OperationView]
)
def operation(task_ref: Reference, operation_ref: OpaqueReference, request: Request, db: Database):
    return response(
        service.operations(
            db,
            authenticated(request),
            task_ref,
            request.app.state.application_runtime,
            operation_ref,
        )
    )


@router.get(
    "/tasks/{task_ref}/timeline",
    response_model=AppSuccess[AppPage[TimelineItem]],
    openapi_extra=PAGE_PARAMETERS,
)
def timeline(task_ref: Reference, request: Request, db: Database):
    owner = authenticated(request, allow_query=True)
    return response(
        service.timeline(
            db, owner, task_ref, request.app.state.application_runtime, *query(request, page=True)
        )
    )


@router.get(
    "/documents",
    response_model=AppSuccess[AppPage[DocumentMetadata]],
    openapi_extra=PAGE_PARAMETERS,
)
def documents(request: Request, db: Database):
    owner = authenticated(request, allow_query=True)
    return response(
        service.documents(
            db, owner, request.app.state.application_runtime, *query(request, page=True)
        )
    )


def install_application_interfaces(app):
    app.include_router(router)
    app.state.application_paths += (
        PREFIX + r"/approvals",
        PREFIX + r"/approvals/[^/]+",
        PREFIX + r"/approvals/[^/]+/(decision|revoke)",
        PREFIX + r"/tasks/[^/]+/(cancel|workflow|operations|timeline)",
        PREFIX + r"/tasks/[^/]+/workflow/continue",
        PREFIX + r"/tasks/[^/]+/operations/[^/]+",
        PREFIX + r"/documents",
    )
