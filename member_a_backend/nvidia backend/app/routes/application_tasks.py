"""The five owner-session task/planning interfaces of ghost-app-v1."""

import asyncio
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session, sessionmaker

from app.agent_schemas import Reference
from app.application_contracts import (
    AppErrorDetail,
    AppFailure,
    ApplicationError,
    AppSuccess,
    PlanningStart,
    PlanningView,
    TaskCreate,
    TaskDetail,
    TaskPage,
)
from app.browser_auth import PREFIX, BrowserAuthError, request_context
from app.database import get_db
from app.routes.session import body
from app.services import application_tasks as service
from app.services.agent_identity import AgentIdentityError, issue_agent_credential
from app.services.application_host import ApplicationRuntime, host_callback

PLANNING_BUDGET_SECONDS = 18


class OwnerRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bound(request):
            try:
                return await handler(request)
            except AgentIdentityError as exc:
                code = (
                    exc.code
                    if exc.code in ("NOT_FOUND", "TASK_NOT_ACTIVE")
                    else "BACKEND_UNAVAILABLE"
                )
                raise ApplicationError(exc.status_code, code) from None
            except (ValueError, TypeError):
                raise ApplicationError(503, "BACKEND_UNAVAILABLE") from None
            except RequestValidationError:
                raise BrowserAuthError("INVALID_REQUEST") from None

        return bound


router = APIRouter(
    prefix=PREFIX,
    route_class=OwnerRoute,
    tags=["application-tasks"],
    responses={
        code: {"model": AppFailure}
        for code in (400, 401, 403, 404, 409, 413, 415, 422, 429, 503, 504)
    },
)


def authenticated(request, *, allow_query=False):
    store, token, csrf = request_context(
        request,
        allow_query=allow_query
        or request.method == "GET"
        and request.url.path == PREFIX + "/tasks",
        allow_idempotency=request.method == "POST",
    )
    owner, lease = store.authorize(token)
    if request.method == "POST":
        store.validate_csrf(token, csrf)
    elif request.headers.get("content-length", "0") != "0" or request.headers.get(
        "transfer-encoding"
    ):
        raise BrowserAuthError("INVALID_REQUEST")
    request.scope["browser_lease"] = store, lease
    return owner


def fresh(request):
    store, lease = request.scope["browser_lease"]
    store.check_lease(lease)


def response(data, *, replayed=False, status=200):
    return JSONResponse(
        AppSuccess(data=data, replayed=replayed).model_dump(mode="json"), status_code=status
    )


def typed_body(model):
    return {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": model.model_json_schema()}},
        }
    }


@router.post(
    "/tasks",
    status_code=201,
    response_model=AppSuccess[TaskDetail],
    openapi_extra=typed_body(TaskCreate),
)
async def create(request: Request, db: Annotated[Session, Depends(get_db)]):
    owner = authenticated(request)
    payload = await body(request, TaskCreate)
    identity = service.command_identity(request, payload, owner)
    fresh(request)
    result, replay = service.create_task(
        db, owner, payload, identity, request.app.state.application_runtime
    )
    return response(result, replayed=replay, status=200 if replay else 201)


@router.get("/tasks", response_model=AppSuccess[TaskPage])
def listing(request: Request, db: Annotated[Session, Depends(get_db)]):
    owner = authenticated(request)
    params = request.query_params
    if any(key not in ("limit", "cursor") or len(params.getlist(key)) != 1 for key in params):
        raise BrowserAuthError("INVALID_REQUEST")
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
    return response(
        service.task_page(
            db, owner, request.app.state.application_runtime, limit=int(raw), cursor=cursor
        )
    )


@router.get("/tasks/{task_ref}", response_model=AppSuccess[TaskDetail])
def detail(task_ref: Reference, request: Request, db: Annotated[Session, Depends(get_db)]):
    return response(
        service.get_task(
            db, authenticated(request), task_ref, request.app.state.application_runtime
        )
    )


@router.get("/tasks/{task_ref}/planning", response_model=AppSuccess[PlanningView])
def planning_status(task_ref: Reference, request: Request, db: Annotated[Session, Depends(get_db)]):
    return response(
        service.get_planning(
            db, authenticated(request), task_ref, request.app.state.application_runtime
        )
    )


@router.post(
    "/tasks/{task_ref}/planning",
    response_model=AppSuccess[PlanningView],
    openapi_extra=typed_body(PlanningStart),
)
async def planning(task_ref: Reference, request: Request, db: Annotated[Session, Depends(get_db)]):
    try:
        # Leave two seconds for child termination; DB work has isolated transactions.
        async with asyncio.timeout(PLANNING_BUDGET_SECONDS):
            return await run_planning(task_ref, request, db)
    except TimeoutError:
        raise ApplicationError(
            504,
            "COMMAND_TIMEOUT",
            command_ref=getattr(request.state, "planning_command", None),
            uncertain=True,
        ) from None


async def run_planning(task_ref, request, db):
    owner = authenticated(request)
    payload = await body(request, PlanningStart)
    identity = service.command_identity(request, payload, owner)
    runtime = request.app.state.application_runtime
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)

    async def transact(function, *args, **kwargs):
        def invoke():
            with factory() as session:
                return function(session, *args, **kwargs)

        return await asyncio.to_thread(invoke)

    prior = await transact(service.planning_replay, owner, task_ref, identity, runtime)
    if prior is not None:
        return response(prior, replayed=True)
    command_ref = f"cmd_{uuid4().hex}"
    fresh(request)
    runtime.reserve(command_ref, task_ref)
    request.state.planning_command = command_ref
    claimed, uncertain = False, False
    try:
        action, purpose, arguments = await transact(
            service.claim_planning, owner, task_ref, identity, runtime, command_ref
        )
        claimed = True
        fresh(request)
        credential = (await transact(issue_agent_credential, owner=owner, task_ref=task_ref)).token

        async def callback(data):
            fresh(request)
            return await host_callback(
                data,
                request=request,
                owner=owner,
                task_ref=task_ref,
                credential=credential,
                factory=factory,
                action=action,
                purpose=purpose,
                arguments=arguments,
            )

        observation = await runtime.run(
            task_ref=task_ref,
            user_request=payload.user_request,
            action=action,
            purpose=purpose,
            arguments=arguments,
            credential=credential,
            callback=callback,
        )
        result = await transact(
            service.finish_planning, owner, task_ref, command_ref, observation=observation
        )
        return response(result)
    except asyncio.CancelledError:
        # A late transaction may commit metadata; its durable claim is never retried.
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
        await transact(service.finish_planning, owner, task_ref, command_ref, failure=failure)
        raise ApplicationError(
            failure.status, failure.code, command_ref=command_ref, uncertain=uncertain
        ) from None
    finally:
        runtime.release(uncertain=uncertain)


def install_application_tasks(app):
    app.state.application_runtime = ApplicationRuntime()
    app.state.application_paths = (
        PREFIX + r"/tasks",
        PREFIX + r"/tasks/[^/]+",
        PREFIX + r"/tasks/[^/]+/planning",
    )
    app.include_router(router)

    @app.exception_handler(ApplicationError)
    async def application_error(request, exc):
        result = AppFailure(
            error=AppErrorDetail(
                code=exc.code,
                correlation_ref=f"http_{uuid4().hex}",
                command_ref=exc.command_ref,
                command_uncertain=exc.uncertain,
                execution_uncertain=exc.execution_uncertain,
                reconciliation_required=exc.uncertain
                or exc.execution_uncertain
                or exc.code == "RECONCILIATION_REQUIRED",
            )
        )
        return JSONResponse(
            result.model_dump(mode="json"),
            status_code=exc.status,
            headers={
                "Cache-Control": "no-store",
                **({"Retry-After": "1"} if exc.status == 429 else {}),
            },
        )

    previous = app.openapi

    def openapi():
        schema = previous()
        for path, methods in schema["paths"].items():
            if path.startswith(PREFIX + "/") and not path.startswith(PREFIX + "/session"):
                for method, operation in methods.items():
                    operation["security"] = [
                        {"AppSession": [], **({"CsrfHeader": []} if method == "post" else {})}
                    ]
                    if method == "post" and not any(
                        p.get("name") == "Idempotency-Key" for p in operation.get("parameters", ())
                    ):
                        operation.setdefault("parameters", []).append(
                            {
                                "in": "header",
                                "name": "Idempotency-Key",
                                "required": True,
                                "schema": {"type": "string", "format": "uuid"},
                            }
                        )
                    if (
                        method == "get"
                        and path == PREFIX + "/tasks"
                        and not operation.get("parameters")
                    ):
                        operation["parameters"] = [
                            {
                                "in": "query",
                                "name": "limit",
                                "required": False,
                                "schema": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": 50,
                                    "default": 20,
                                },
                            },
                            {
                                "in": "query",
                                "name": "cursor",
                                "required": False,
                                "schema": {"type": "string", "minLength": 1, "maxLength": 2048},
                            },
                        ]
        return schema

    app.openapi = openapi
