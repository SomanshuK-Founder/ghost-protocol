"""Real-application OpenAPI completion and the allowlisted browser schema audience."""

from copy import deepcopy
from http import HTTPStatus

from fastapi import Request
from fastapi.openapi.models import OpenAPI
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute, iter_route_contexts

from app.application_contracts import AppFailure
from app.browser_auth import PREFIX, BrowserAuthError, request_context
from app.gateway_contracts import ARGUMENT_TYPES
from app.openapi_contracts import DetailError, GatewayError, LegacyToolResult

SCHEMA_PATH = PREFIX + "/openapi.json"
APP_RULES = (
    "LOCAL_DEMO is disabled by default and supports one owner/process on literal loopback only. "
    "Owner identity is server-derived. No browser bearer, owner, role or proxy headers. "
    "All reads validate Host/Origin/peer; POST requires the exact configured Origin and "
    "X-Ghost-CSRF bound to the HttpOnly SameSite=Strict preauth/session cookie. "
    "HTTPS uses __Host-ghost_session with Secure; explicit HTTP loopback uses "
    "ghost_demo_session without Secure. Cookies have Path=/ and no Domain. "
    "Expired/revoked sessions cannot access private results. Responses are no-store. "
    "Approval and metadata continuation never dispatch; UNKNOWN requires reconciliation, "
    "never an automatic resend. Catalog metadata does not authorize protected content."
)


def normalize_defaults(value):
    if isinstance(value, dict):
        # FastAPI omits null defaults while serializing generated schema models.
        return {
            key: normalize_defaults(child)
            for key, child in value.items()
            if key != "default" or child is not None
        }
    if isinstance(value, list):
        return [normalize_defaults(child) for child in value]
    return value


def register(schemas, name, schema):
    schema = normalize_defaults(schema)
    for child, definition in schema.pop("$defs", {}).items():
        register(schemas, child, definition)
    if name in schemas and schemas[name] != schema:
        raise ValueError(f"Conflicting OpenAPI component: {name}")
    schemas[name] = schema
    return {"$ref": "#/components/schemas/" + name}


def model_ref(schemas, model):
    return register(
        schemas,
        model.__name__,
        model.model_json_schema(mode="serialization", ref_template="#/components/schemas/{model}"),
    )


def error_response(schema, status):
    return {
        "description": HTTPStatus(status).phrase,
        "content": {"application/json": {"schema": schema}},
    }


def references(value):
    if isinstance(value, dict):
        if "$ref" in value:
            yield value["$ref"]
        for child in value.values():
            yield from references(child)
    elif isinstance(value, list):
        for child in value:
            yield from references(child)


def application_schema(combined):
    """Prune transitively; merely deleting internal paths would leave private components."""
    schema = deepcopy(combined)
    schema["info"] = {
        "title": "Ghost browser application API",
        "version": "ghost-app-v1",
        "description": APP_RULES,
    }
    schema["paths"] = {
        path: item
        for path, item in schema["paths"].items()
        if path.startswith(PREFIX + "/") or path == "/health"
    }
    required, pending = set(), list(references(schema["paths"]))
    available = schema["components"]["schemas"]
    while pending:
        reference = pending.pop()
        if not reference.startswith("#/components/schemas/"):
            raise ValueError("Only local schema references may enter the browser artifact")
        name = reference.rsplit("/", 1)[1]
        if name not in required:
            required.add(name)
            pending.extend(references(available[name]))
    schema["components"] = {
        "schemas": {name: available[name] for name in sorted(required)},
        "securitySchemes": {
            name: schema["components"]["securitySchemes"][name]
            for name in ("AppSession", "CsrfHeader")
        },
    }
    # No private servers, global tags or security inherited from the trusted audience.
    for name in ("servers", "tags", "security", "externalDocs", "webhooks"):
        schema.pop(name, None)
    return schema


def trusted_errors(path, method, detail, gateway, validation):
    if path.startswith("/api/gateway/"):
        statuses = {401, 404, 422, 503}
        if method == "post":
            statuses |= {400, 403, 409, 410, 413, 415, 429}
            if path.endswith("/execute"):
                statuses.remove(404)
        return {status: gateway for status in statuses}
    if path.startswith("/api/control/"):
        result = {401: detail, 404: gateway, 503: {"anyOf": [detail, gateway]}}
        result[422] = {"anyOf": [gateway, validation]}
        if method == "post":
            result.update({status: gateway for status in (400, 413, 415)})
        if method == "post" and (
            "/workflow-checkpoints" in path
            or path.endswith("/resolve")
            or path.endswith("/revoke")
            and "/approvals/" in path
        ):
            result[409] = gateway
        if path.endswith("/consents") and method == "post":
            result[403] = gateway
        return result
    result = {401: detail, 503: detail, 422: validation}
    if path == "/api/tool-permissions":
        result[400] = detail
    if path == "/api/tools/execute":
        result.update({403: detail, 404: detail, 504: detail})
        result[422] = {"anyOf": [detail, validation]}
    if path != "/api/audit-events":
        result[500] = detail
    return result


def complete_schema(schema):
    schemas = schema.setdefault("components", {}).setdefault("schemas", {})
    detail, gateway, app_error = (
        model_ref(schemas, model) for model in (DetailError, GatewayError, AppFailure)
    )
    validation = {"$ref": "#/components/schemas/HTTPValidationError"}
    schemes = schema["components"]["securitySchemes"]
    schemes.update(
        OwnerBearer={
            "type": "http",
            "scheme": "bearer",
            "description": "Trusted owner/control host only; never browser credentials.",
        },
        TaskAgentBearer={
            "type": "http",
            "scheme": "bearer",
            "description": "Trusted injected agent credential; exact task/owner/expiry binding.",
        },
    )
    schemes["CsrfHeader"]["description"] = (
        "Required together with the cookie on every POST, including login/logout. "
        "Exact Origin/Host checks also apply; cookie security alone is insufficient."
    )
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            body = operation.get("requestBody", {}).get("content", {}).get("application/json")
            if body and "title" in body["schema"]:
                body["schema"] = register(schemas, body["schema"]["title"], body["schema"])
            if path == "/health":
                operation["security"] = []
                operation["description"] = (
                    "Liveness only; no database/model/sandbox readiness claim."
                )
                continue
            if path.startswith(PREFIX + "/"):
                operation["description"] = APP_RULES + " " + operation.get("description", "")
                if method == "post":
                    operation.setdefault("parameters", []).append(
                        {
                            "name": "Origin",
                            "in": "header",
                            "required": True,
                            "schema": {"type": "string"},
                            "description": "Exact configured origin; no forwarded-header trust.",
                        }
                    )
                # Auth middleware and application services share this exact outer error shape.
                for status in (*map(int, operation["responses"].keys()), 404, 500):
                    if status >= 400:
                        operation["responses"][str(status)] = error_response(app_error, status)
                if path == PREFIX + "/tasks" and method == "post":
                    operation["responses"]["200"] = deepcopy(operation["responses"]["201"])
                    operation["responses"]["200"]["description"] = "Idempotent replay; current task"
                if path.startswith(PREFIX + "/session"):
                    success = "204" if path.endswith("/logout") else "200"
                    operation["responses"][success]["headers"] = {
                        "Set-Cookie": {
                            "description": "HttpOnly; SameSite=Strict; Path=/; HTTPS Secure",
                            "schema": {"type": "string"},
                        }
                    }
                if "429" in operation["responses"]:
                    operation["responses"]["429"]["headers"] = {
                        "Retry-After": {
                            "schema": {"type": "string"},
                            "description": "Delay in seconds",
                        }
                    }
                continue
            scheme = "TaskAgentBearer" if path.startswith("/api/gateway/") else "OwnerBearer"
            operation["security"] = [{scheme: []}]
            operation["parameters"] = [
                parameter
                for parameter in operation.get("parameters", [])
                if not (
                    parameter["in"] == "header" and parameter["name"].lower() == "authorization"
                )
            ]
            operation["description"] = (
                "Private trusted backend operation. Cookie sessions are not bearer credentials. "
                + operation.get("description", "")
            )
            for status, error in trusted_errors(path, method, detail, gateway, validation).items():
                operation["responses"][str(status)] = error_response(error, status)
            if scheme == "TaskAgentBearer":
                operation["responses"]["401"]["headers"] = {
                    "WWW-Authenticate": {"schema": {"type": "string", "const": "Bearer"}}
                }
            operation["responses"].setdefault(
                "500",
                {
                    "description": "Unhandled server failure; effect may require reconciliation",
                    "content": {"text/plain": {"schema": {"type": "string"}}},
                },
            )
            if path == "/api/tools/execute":
                operation["responses"]["200"]["content"]["application/json"]["schema"] = model_ref(
                    schemas, LegacyToolResult
                )
    # Mirror existing model validators in documentation, without replacing runtime parsers.
    schemas["ToolRequest"]["allOf"] = [
        {
            "if": {"properties": {"action": {"const": action}}},
            "then": {
                "properties": {"arguments": {"$ref": "#/components/schemas/" + model.__name__}}
            },
        }
        for action, model in ARGUMENT_TYPES.items()
    ]
    schemas["TaskCreate"]["allOf"] = [
        {
            "if": {"properties": {"profile_id": {"const": "document_simulation_v1"}}},
            "then": {"properties": {"resource_id": {"type": "string"}}},
            "else": {"properties": {"resource_id": {"type": "null"}}},
        }
    ]
    schemas["ConsentCreate"]["properties"]["resource_ids"]["uniqueItems"] = True
    schemas["ConsentCreate"]["allOf"] = [
        {
            "if": {"properties": {"action": {"const": action}}},
            "then": {"properties": {"resource_ids": {"minItems": count, "maxItems": count}}},
        }
        for action, count in (("files.read", 1), ("tasks.list", 0))
    ]
    for name in ("WorkflowPause", "WorkflowIdentity"):
        schemas[name]["properties"]["checkpoint_id"]["pattern"] = (
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        )
    return schema


def inventory(app):
    return [
        {
            "path": context.path,
            "methods": sorted(context.methods or ()),
            "name": context.name,
            "include_in_schema": isinstance(context.original_route, APIRoute)
            and context.original_route.include_in_schema,
        }
        for context in iter_route_contexts(app.routes)
    ]


def install_openapi(app):
    original = app.openapi

    def openapi():
        result = complete_schema(deepcopy(original()))
        OpenAPI.model_validate(result)
        return result

    app.openapi = openapi

    @app.get(SCHEMA_PATH, include_in_schema=False)
    def browser_openapi(request: Request):
        request_context(request)
        if request.headers.get("content-length", "0") != "0" or request.headers.get(
            "transfer-encoding"
        ):
            raise BrowserAuthError("INVALID_REQUEST")
        return JSONResponse(application_schema(app.openapi()))

    app.state.application_paths += (SCHEMA_PATH,)
