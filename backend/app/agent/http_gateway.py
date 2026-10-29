"""Authenticated, bounded v1.1 authorization transport; no executor or retry path."""

import asyncio
import json
import math
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

import httpx
from pydantic import SecretStr, TypeAdapter, ValidationError

from app.agent.execution_contracts import validate_authorization_observation
from app.agent.gateway_protocol import OpaqueReference, ToolRequest, ToolResponse
from app.tls import tls_verification

MAX_BYTES = 256 * 1024
REFERENCE = TypeAdapter(OpaqueReference)
TOKEN = re.compile(r"gpa_cred_[0-9a-f]{32}\.[A-Za-z0-9_-]{43}", re.ASCII)
ERROR_CODES = {
    400: {"MALFORMED_JSON", "DUPLICATE_JSON_FIELD"},
    401: {"AUTH_REQUIRED", "AUTH_INVALID"},
    403: {"ROLE_FORBIDDEN", "TASK_SCOPE_MISMATCH", "RESULT_ACCESS_DENIED"},
    404: {"NOT_FOUND"},
    409: {
        "REQUEST_ID_CONFLICT",
        "IDEMPOTENCY_CONFLICT",
        "LOGICAL_OPERATION_EXISTS",
        "OPERATION_IN_PROGRESS",
        "RESUME_REQUIRED",
        "NOT_RESUMABLE",
        "APPROVAL_ALREADY_RESOLVED",
    },
    410: {"RESULT_EXPIRED"},
    413: {"PAYLOAD_TOO_LARGE"},
    415: {"UNSUPPORTED_MEDIA_TYPE"},
    422: {"INVALID_REQUEST", "INVALID_TOOL_ARGUMENTS"},
    429: {"CAPACITY_EXCEEDED"},
    500: {"INTERNAL_ERROR"},
    503: {"GATEWAY_UNAVAILABLE"},
    504: {"GATEWAY_TIMEOUT"},
}


class GatewayErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    WRONG_TASK = "WRONG_TASK"
    MISSING_CREDENTIAL = "MISSING_CREDENTIAL"
    INVALID_CREDENTIAL = "INVALID_CREDENTIAL"
    CREDENTIAL_UNAVAILABLE = "CREDENTIAL_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    CONNECTION_FAILURE = "CONNECTION_FAILURE"
    REDIRECT = "REDIRECT"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    HTTP_ERROR = "HTTP_ERROR"
    CLOSED = "CLOSED"


class GatewayTransportError(Exception):
    """Only closed codes and safe correlation metadata; never HTTP objects/bodies."""

    def __init__(
        self,
        code: GatewayErrorCode,
        *,
        request_ref=None,
        http_status=None,
        execution_uncertain=False,
        server_error_code=None,
    ):
        super().__init__("Gateway request could not be completed")
        self.code = code
        self.request_ref = request_ref
        self.http_status = http_status
        self.execution_uncertain = execution_uncertain
        self.server_error_code = server_error_code


class AgentCredentialProvider(Protocol):
    async def get_credential(self, task_ref: str) -> SecretStr | None: ...


@dataclass(frozen=True)
class InMemoryTaskCredential:
    task_ref: str
    token: SecretStr | None = field(repr=False)

    async def get_credential(self, task_ref: str) -> SecretStr | None:
        if task_ref != self.task_ref:
            raise ValueError("Credential task does not match")
        return self.token


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON field")
        value[key] = item
    return value


def _nonfinite(value):
    raise ValueError("Nonfinite JSON number")


def _finite(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Nonfinite JSON number")
    return number


def _json(data):
    invalid = False
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_unique,
            parse_constant=_nonfinite,
            parse_float=_finite,
        )
        stack = [(value, 0)]
        while stack:
            item, depth = stack.pop()
            if depth > 8:
                raise ValueError("JSON depth exceeded")
            if isinstance(item, dict):
                stack.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                stack.extend((child, depth + 1) for child in item)
        if not isinstance(value, dict):
            raise ValueError("JSON object required")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        invalid = True
    if invalid:
        raise GatewayTransportError(GatewayErrorCode.INVALID_RESPONSE, execution_uncertain=True)
    return value


def trusted_origin(base_url):
    """Only trusted composition supplies this origin; remote HTTPS, literal local HTTP."""
    if (
        not isinstance(base_url, str)
        or len(base_url) > 2048
        or any(ord(char) < 33 or ord(char) == 127 for char in base_url)
    ):
        raise ValueError("Invalid origin")
    origin = httpx.URL(base_url)
    if (
        not origin.host
        or origin.username
        or origin.password
        or origin.query
        or origin.fragment
        or origin.path not in ("", "/")
        or origin.scheme not in ("http", "https")
        or origin.scheme == "http"
        and origin.host not in ("127.0.0.1", "::1")
    ):
        raise ValueError("Invalid origin")
    return origin


class AuthenticatedHttpToolGateway:
    """Trusted composition pins origin/task/provider; transports are offline test seams."""

    def __init__(
        self,
        *,
        base_url: str,
        task_ref: str,
        credential_provider: AgentCredentialProvider,
        transport: httpx.AsyncBaseTransport | None = None,
        deadline_seconds: float = 4.0,
        openshell: bool = False,
        ca_bundle: str | None = None,
    ):
        invalid = False
        try:
            origin = trusted_origin(base_url)
            self._task_ref = REFERENCE.validate_python(task_ref, strict=True)
            if type(deadline_seconds) not in (int, float) or not 0 < deadline_seconds <= 4:
                raise ValueError("Invalid deadline")
            if isinstance(transport, httpx.AsyncHTTPTransport):
                raise ValueError("Real HTTP transports are owned by this adapter")
            if transport is not None and not isinstance(transport, httpx.AsyncBaseTransport):
                raise ValueError("An isolated async test transport is required")
            if not callable(getattr(credential_provider, "get_credential", None)):
                raise ValueError("An injected credential provider is required")
        except (ValueError, TypeError, httpx.InvalidURL, ValidationError):
            invalid = True
        if invalid:
            raise ValueError("Invalid trusted gateway configuration")
        self._provider = credential_provider
        self._deadline = float(deadline_seconds)
        self._closed = False
        self._client = httpx.AsyncClient(
            base_url=origin,
            transport=transport,
            verify=tls_verification(openshell=openshell, ca_bundle=ca_bundle),
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(self._deadline),
        )

    @property
    def task_ref(self):
        return self._task_ref

    @property
    def deadline_seconds(self):
        return self._deadline

    async def __aenter__(self):
        if self._closed:
            raise GatewayTransportError(GatewayErrorCode.CLOSED)
        return self

    async def __aexit__(self, *args):
        await self.aclose()

    async def aclose(self):
        self._closed = True
        await self._client.aclose()

    async def _credential(self):
        unavailable = False
        try:
            token = await self._provider.get_credential(self._task_ref)
        except Exception:
            unavailable = True
        if unavailable:
            raise GatewayTransportError(GatewayErrorCode.CREDENTIAL_UNAVAILABLE)
        if token is None:
            raise GatewayTransportError(GatewayErrorCode.MISSING_CREDENTIAL)
        if not isinstance(token, SecretStr) or TOKEN.fullmatch(token.get_secret_value()) is None:
            raise GatewayTransportError(GatewayErrorCode.INVALID_CREDENTIAL)
        return token

    def _request(self, request):
        invalid = False
        try:
            if not isinstance(request, ToolRequest):
                raise ValueError("ToolRequest required")
            snapshot = ToolRequest.model_validate_json(
                request.model_dump_json(warnings=False), strict=True
            )
            data = snapshot.model_dump_json().encode("utf-8")
            if len(data) > MAX_BYTES:
                raise ValueError("Request size exceeded")
        except (ValueError, TypeError, AttributeError):
            invalid = True
        if invalid:
            raise GatewayTransportError(GatewayErrorCode.INVALID_REQUEST)
        if snapshot.task_ref != self._task_ref:
            raise GatewayTransportError(
                GatewayErrorCode.WRONG_TASK, request_ref=snapshot.request_id
            )
        return snapshot, data

    async def _response(self, response, request_ref):
        if 300 <= response.status_code < 400:
            raise GatewayTransportError(
                GatewayErrorCode.REDIRECT,
                http_status=response.status_code,
                execution_uncertain=True,
            )
        if (
            response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/json"
            or response.headers.get("content-encoding", "identity").lower() != "identity"
        ):
            raise GatewayTransportError(GatewayErrorCode.INVALID_RESPONSE, execution_uncertain=True)
        body = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=8192):
            if len(body) + len(chunk) > MAX_BYTES:
                raise GatewayTransportError(
                    GatewayErrorCode.INVALID_RESPONSE, execution_uncertain=True
                )
            body.extend(chunk)
        value = _json(bytes(body))
        invalid = False
        try:
            if response.status_code == 200:
                if set(value) != {
                    "request_id",
                    "decision",
                    "execution_status",
                    "reason_code",
                    "approval_ref",
                    "result",
                    "audit_event_ref",
                }:
                    raise ValueError("Exact response fields required")
                result = ToolResponse.model_validate_json(
                    json.dumps(value, allow_nan=False), strict=True
                )
                if result.request_id != request_ref:
                    raise ValueError("Response correlation mismatch")
                validate_authorization_observation(
                    result.decision,
                    result.execution_status,
                    result.reason_code,
                    result.approval_ref,
                    result.result,
                    result.audit_event_ref,
                )
                return result
            if (
                response.status_code not in ERROR_CODES
                or set(value)
                != {
                    "error_code",
                    "message",
                    "correlation_ref",
                    "request_id",
                    "audit_event_ref",
                    "execution_uncertain",
                }
                or value["error_code"] not in ERROR_CODES[response.status_code]
                or value["message"] != "Request cannot be processed"
                or value["request_id"] not in (request_ref, None)
                or type(value["execution_uncertain"]) is not bool
            ):
                raise ValueError("Invalid error envelope")
            REFERENCE.validate_python(value["correlation_ref"], strict=True)
            if value["audit_event_ref"] is not None:
                REFERENCE.validate_python(value["audit_event_ref"], strict=True)
        except (ValueError, TypeError, KeyError):
            invalid = True
        if invalid:
            raise GatewayTransportError(GatewayErrorCode.INVALID_RESPONSE, execution_uncertain=True)
        raise GatewayTransportError(
            GatewayErrorCode.HTTP_ERROR,
            http_status=response.status_code,
            server_error_code=value["error_code"],
            execution_uncertain=value["execution_uncertain"],
        )

    async def execute(self, request: ToolRequest) -> ToolResponse:
        if self._closed:
            raise GatewayTransportError(GatewayErrorCode.CLOSED)
        snapshot, data = self._request(request)
        sent, error, result = False, None, None
        try:
            async with asyncio.timeout(self._deadline):
                token = await self._credential()
                headers = {
                    "Authorization": "Bearer " + token.get_secret_value(),
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                }
                sent = True
                async with self._client.stream(
                    "POST", "/api/gateway/v1/execute", content=data, headers=headers
                ) as response:
                    result = await self._response(response, snapshot.request_id)
        except GatewayTransportError as exc:
            error = GatewayTransportError(
                exc.code,
                request_ref=snapshot.request_id,
                http_status=exc.http_status,
                execution_uncertain=exc.execution_uncertain,
                server_error_code=exc.server_error_code,
            )
        except (TimeoutError, httpx.TimeoutException):
            error = GatewayTransportError(
                GatewayErrorCode.TIMEOUT, request_ref=snapshot.request_id, execution_uncertain=sent
            )
        except httpx.RequestError:
            error = GatewayTransportError(
                GatewayErrorCode.CONNECTION_FAILURE,
                request_ref=snapshot.request_id,
                execution_uncertain=sent,
            )
        except Exception:
            error = GatewayTransportError(
                GatewayErrorCode.INVALID_RESPONSE,
                request_ref=snapshot.request_id,
                execution_uncertain=True,
            )
        if error is not None:
            raise error
        return result
