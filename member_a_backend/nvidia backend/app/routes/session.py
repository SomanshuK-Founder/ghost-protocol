"""The three cookie-session operations only; existing bearer routers are untouched."""

import json
import re
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from app.agent_schemas import IdentityModel
from app.browser_auth import (
    PREFIX,
    AuthFailure,
    AuthFailureDetail,
    BrowserAuthError,
    LoginRequest,
    SessionSuccess,
    request_context,
)
from app.routes.gateway import (
    GatewayProtocolError,
    check_depth,
    finite_number,
    invalid_number,
    unique_object,
)


def failure(exc):
    result = AuthFailure(
        error=AuthFailureDetail(code=exc.code, correlation_ref=f"http_{uuid4().hex}")
    )
    return JSONResponse(
        result.model_dump(mode="json"),
        status_code=exc.status_code,
        headers={
            "Cache-Control": "no-store",
            **({"Retry-After": "60"} if exc.status_code == 429 else {}),
        },
    )


class BrowserBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith(PREFIX + "/"):
            return await self.app(scope, receive, send)
        if scope["method"] == "OPTIONS":
            return await failure(BrowserAuthError("ORIGIN_FORBIDDEN"))(scope, receive, send)
        if scope["path"] not in (
            PREFIX + "/session",
            PREFIX + "/session/login",
            PREFIX + "/session/logout",
        ) and not any(
            re.fullmatch(pattern, scope["path"])
            for pattern in getattr(scope["app"].state, "application_paths", ())
        ):
            return await failure(BrowserAuthError("NOT_FOUND"))(scope, receive, send)
        replaced, started = False, False

        async def bounded_send(message):
            nonlocal replaced, started
            if replaced:
                return
            if message["type"] == "http.response.start":
                if message["status"] < 400 and "browser_lease" in scope:
                    store, lease = scope["browser_lease"]
                    try:
                        store.check_lease(lease)
                    except BrowserAuthError as exc:
                        replaced = True
                        return await failure(exc)(scope, receive, send)
                message["headers"] = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if not k.lower().startswith(b"access-control-")
                    and k.lower() != b"cache-control"
                ] + [(b"cache-control", b"no-store")]
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, bounded_send)
        except Exception:
            if started:
                raise
            from app.application_contracts import AppErrorDetail, AppFailure

            response = JSONResponse(
                AppFailure(
                    error=AppErrorDetail(
                        code="INTERNAL_ERROR",
                        correlation_ref=f"http_{uuid4().hex}",
                        command_uncertain=scope["method"] == "POST",
                        reconciliation_required=scope["method"] == "POST",
                    )
                ).model_dump(mode="json"),
                status_code=500,
                headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)


async def body(request, model):
    if request.headers.get("content-encoding") or (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise BrowserAuthError("UNSUPPORTED_MEDIA_TYPE")
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 32768:
            raise BrowserAuthError("PAYLOAD_TOO_LARGE")
        raw.extend(chunk)
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=invalid_number,
            parse_float=finite_number,
        )
        check_depth(value)
        return model.model_validate_json(json.dumps(value, allow_nan=False))
    except GatewayProtocolError as exc:
        raise BrowserAuthError(exc.code) from None
    except (UnicodeError, json.JSONDecodeError):
        raise BrowserAuthError("MALFORMED_JSON") from None
    except (ValidationError, ValueError, TypeError, RecursionError):
        raise BrowserAuthError("INVALID_REQUEST") from None


def session_response(request, store, result, lease, token):
    response = JSONResponse(result.model_dump(mode="json"))
    if token is not None:
        response.set_cookie(
            store.config.cookie_name,
            token,
            max_age=store.check_lease(lease),
            httponly=True,
            secure=store.config.secure,
            samesite="strict",
            path="/",
        )
    request.scope["browser_lease"] = (store, lease)
    return response


ERROR_RESPONSES = {
    status: {"model": AuthFailure} for status in (400, 401, 403, 413, 415, 422, 429, 503)
}
router = APIRouter(prefix=PREFIX, tags=["local-demo-authentication"], responses=ERROR_RESPONSES)


@router.get("/session", response_model=SessionSuccess)
def session_status(request: Request):
    store, token, _ = request_context(request)
    if request.headers.get("content-length", "0") != "0" or request.headers.get(
        "transfer-encoding"
    ):
        raise BrowserAuthError("INVALID_REQUEST")
    return session_response(request, store, *store.inspect(token))


@router.post(
    "/session/login",
    response_model=SessionSuccess,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": LoginRequest.model_json_schema()}},
        }
    },
)
async def login(request: Request):
    store, token, csrf = request_context(request)
    # Check session and CSRF before consuming or even parsing a pairing credential.
    store.validate_csrf(token, csrf)
    payload = await body(request, LoginRequest)
    result = store.pair(token, csrf, payload.pairing_code, request.scope["client"][0])
    return session_response(request, store, *result)


@router.post(
    "/session/logout",
    status_code=204,
    response_class=Response,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": IdentityModel.model_json_schema()}},
        }
    },
)
async def logout(request: Request):
    store, token, csrf = request_context(request)
    store.validate_csrf(token, csrf)
    await body(request, IdentityModel)
    store.logout(token, csrf)
    response = Response(status_code=204)
    response.delete_cookie(
        store.config.cookie_name,
        path="/",
        secure=store.config.secure,
        httponly=True,
        samesite="strict",
    )
    return response


def install_browser_auth(app):
    app.include_router(router)
    app.add_middleware(BrowserBoundary)

    @app.exception_handler(BrowserAuthError)
    async def auth_error(request, exc):
        return failure(exc)

    original_openapi = app.openapi

    def openapi():
        schema = original_openapi()
        store = getattr(app.state, "browser_sessions", None)
        cookie = store.config.cookie_name if store is not None else "ghost_demo_session"
        schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})
        schemes["AppSession"] = {
            "type": "apiKey",
            "in": "cookie",
            "name": cookie,
            "description": "Local-demo opaque preauth/current session; not an owner bearer",
        }
        schemes["CsrfHeader"] = {"type": "apiKey", "in": "header", "name": "X-Ghost-CSRF"}
        for suffix in ("login", "logout"):
            schema["paths"][PREFIX + "/session/" + suffix]["post"]["security"] = [
                {"AppSession": [], "CsrfHeader": []}
            ]
        schema["paths"][PREFIX + "/session"]["get"]["security"] = []
        return schema

    app.openapi = openapi
