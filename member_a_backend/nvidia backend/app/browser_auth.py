"""Single-process local-demo sessions; no database, bearer or tool authority."""

import hashlib
import hmac
import ipaddress
import os
import re
import secrets
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import Request
from pydantic import AwareDatetime, ConfigDict, Field, SecretStr, field_validator

from app.agent_schemas import IdentityModel, OwnerContext

TOKEN = re.compile(r"[A-Za-z0-9_-]{43}", re.ASCII)
PREFIX = "/api/app/v1"
STATUS = {
    "AUTH_NOT_CONFIGURED": 503,
    "AUTH_RATE_LIMITED": 429,
    "LOGIN_FAILED": 401,
    "SESSION_REQUIRED": 401,
    "SESSION_EXPIRED": 401,
    "CSRF_INVALID": 403,
    "ORIGIN_FORBIDDEN": 403,
    "CREDENTIAL_HEADER_FORBIDDEN": 403,
    "INVALID_REQUEST": 422,
    "MALFORMED_JSON": 400,
    "DUPLICATE_JSON_FIELD": 400,
    "PAYLOAD_TOO_LARGE": 413,
    "UNSUPPORTED_MEDIA_TYPE": 415,
    "UNEXPECTED_IDEMPOTENCY_KEY": 400,
    "NOT_FOUND": 404,
}
AuthCode = Literal[
    "AUTH_NOT_CONFIGURED",
    "AUTH_RATE_LIMITED",
    "LOGIN_FAILED",
    "SESSION_REQUIRED",
    "SESSION_EXPIRED",
    "CSRF_INVALID",
    "ORIGIN_FORBIDDEN",
    "CREDENTIAL_HEADER_FORBIDDEN",
    "INVALID_REQUEST",
    "MALFORMED_JSON",
    "DUPLICATE_JSON_FIELD",
    "PAYLOAD_TOO_LARGE",
    "UNSUPPORTED_MEDIA_TYPE",
    "UNEXPECTED_IDEMPOTENCY_KEY",
    "NOT_FOUND",
]
TokenText = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{43}$", repr=False)]


class BrowserAuthError(Exception):
    def __init__(self, code: AuthCode):
        self.code, self.status_code = code, STATUS[code]
        super().__init__(code)


class LoginRequest(IdentityModel):
    pairing_code: SecretStr = Field(
        min_length=43,
        max_length=43,
        repr=False,
        json_schema_extra={"pattern": r"^[A-Za-z0-9_-]{43}$"},
    )

    @field_validator("pairing_code")
    @classmethod
    def token_shape(cls, value):
        if not TOKEN.fullmatch(value.get_secret_value()):
            raise ValueError("Invalid pairing code")
        return value


class BrowserResponse(IdentityModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class OwnerDisplay(BrowserResponse):
    display_name: Literal["Local demo owner"] = "Local demo owner"


class AnonymousSession(BrowserResponse):
    authenticated: Literal[False] = False
    mode: Literal["LOCAL_DEMO"] = "LOCAL_DEMO"
    csrf_token: TokenText
    owner: None = None
    idle_expires_at: None = None
    absolute_expires_at: None = None


class OwnerSession(BrowserResponse):
    authenticated: Literal[True] = True
    mode: Literal["LOCAL_DEMO"] = "LOCAL_DEMO"
    csrf_token: TokenText
    owner: OwnerDisplay
    idle_expires_at: AwareDatetime
    absolute_expires_at: AwareDatetime


class SessionSuccess(BrowserResponse):
    api_version: Literal["ghost-app-v1"] = "ghost-app-v1"
    data: Annotated[AnonymousSession | OwnerSession, Field(discriminator="authenticated")]
    replayed: Literal[False] = False


class AuthFailureDetail(BrowserResponse):
    code: AuthCode
    message: Literal["Request cannot be processed"] = "Request cannot be processed"
    correlation_ref: str
    command_ref: None = None
    command_uncertain: Literal[False] = False
    execution_uncertain: Literal[False] = False
    reconciliation_required: Literal[False] = False
    reason_code: None = None


class AuthFailure(BrowserResponse):
    api_version: Literal["ghost-app-v1"] = "ghost-app-v1"
    error: AuthFailureDetail


@dataclass(frozen=True)
class LocalDemoConfig:
    origin: str
    host: str = field(init=False)
    port: int = field(init=False)
    secure: bool = field(init=False)

    def __post_init__(self):
        try:
            if not isinstance(self.origin, str) or any(ord(c) < 33 for c in self.origin):
                raise ValueError
            url = urlsplit(self.origin)
            if (
                url.scheme not in ("http", "https")
                or url.hostname not in ("127.0.0.1", "::1")
                or url.username is not None
                or url.password is not None
                or url.path
                or url.query
                or url.fragment
            ):
                raise ValueError
            port = url.port or (443 if url.scheme == "https" else 80)
            if not 1 <= port <= 65535:
                raise ValueError
            authority = "[::1]" if url.hostname == "::1" else url.hostname
            if port != (443 if url.scheme == "https" else 80):
                authority += f":{port}"
            if self.origin != f"{url.scheme}://{authority}":
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Only a canonical direct-loopback origin is supported") from None
        object.__setattr__(self, "host", url.hostname)
        object.__setattr__(self, "port", port)
        object.__setattr__(self, "secure", url.scheme == "https")

    @property
    def cookie_name(self):
        return "__Host-ghost_session" if self.secure else "ghost_demo_session"


@dataclass
class _Session:
    owner: OwnerContext | None
    csrf: SecretStr = field(repr=False)
    idle: datetime
    absolute: datetime
    attempts: deque = field(default_factory=deque, repr=False)


@dataclass(frozen=True)
class SessionLease:
    digest: bytes = field(repr=False)
    generation: str = field(repr=False)


def _now():
    return datetime.now(UTC)


def _digest(value: str):
    return hashlib.sha256(value.encode("utf-8")).digest()


class BrowserSessions:
    def __init__(self, config: LocalDemoConfig, *, clock: Callable = _now, workers=1):
        if not isinstance(config, LocalDemoConfig) or type(workers) is not int or workers != 1:
            raise ValueError("Local authentication requires one process")
        self.config, self._clock, self._pid = config, clock, os.getpid()
        self._lock = RLock()
        self._sessions: dict[bytes, _Session] = {}
        self._pairing: tuple[bytes, datetime] | None = None
        self._peers: dict[str, deque] = {}
        self._attempts: deque = deque()
        self._generation = secrets.token_hex(16)

    def _time(self):
        if os.getpid() != self._pid:
            raise BrowserAuthError("AUTH_NOT_CONFIGURED")
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("An aware server clock is required")
        return now.astimezone(UTC)

    def _prune(self, now):
        for digest, record in list(self._sessions.items()):
            if now >= min(record.idle, record.absolute):
                del self._sessions[digest]
        if self._pairing is not None and now >= self._pairing[1]:
            self._pairing = None
        for peer, attempts in list(self._peers.items()):
            self._window(attempts, now)
            if not attempts:
                del self._peers[peer]
        self._window(self._attempts, now)

    @staticmethod
    def _window(attempts, now):
        while attempts and attempts[0] <= now - timedelta(seconds=60):
            attempts.popleft()

    def issue_pairing_code(self) -> SecretStr:
        """Trusted operator only; no HTTP entry point or normal logging."""
        with self._lock:
            now = self._time()
            code = secrets.token_urlsafe(32)
            self._pairing = (_digest(code), now + timedelta(seconds=120))
            return SecretStr(code)

    def invalidate_all(self):
        with self._lock:
            self._sessions.clear()
            self._pairing = None
            self._generation = secrets.token_hex(16)

    def _record(self, token, now):
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            raise BrowserAuthError("SESSION_REQUIRED")
        record = self._sessions.get(_digest(token))
        if record is None:
            raise BrowserAuthError("SESSION_REQUIRED")
        if now >= min(record.idle, record.absolute):
            del self._sessions[_digest(token)]
            raise BrowserAuthError("SESSION_EXPIRED")
        return record

    @staticmethod
    def _csrf(record, csrf):
        if (
            not isinstance(csrf, str)
            or not TOKEN.fullmatch(csrf)
            or not hmac.compare_digest(
                record.csrf.get_secret_value().encode("ascii"), csrf.encode("ascii")
            )
        ):
            raise BrowserAuthError("CSRF_INVALID")

    def _view(self, token, record):
        data = (
            AnonymousSession(csrf_token=record.csrf.get_secret_value())
            if record.owner is None
            else OwnerSession(
                csrf_token=record.csrf.get_secret_value(),
                owner=OwnerDisplay(),
                idle_expires_at=min(record.idle, record.absolute),
                absolute_expires_at=record.absolute,
            )
        )
        return SessionSuccess(data=data), SessionLease(_digest(token), self._generation)

    def inspect(self, token):
        with self._lock:
            now = self._time()
            self._prune(now)
            record = self._sessions.get(_digest(token)) if isinstance(token, str) else None
            replacement = None
            if record is None:
                if sum(item.owner is None for item in self._sessions.values()) >= 64:
                    raise BrowserAuthError("AUTH_RATE_LIMITED")
                replacement = token = secrets.token_urlsafe(32)
                record = _Session(
                    None,
                    SecretStr(secrets.token_urlsafe(32)),
                    now + timedelta(seconds=120),
                    now + timedelta(seconds=120),
                )
                self._sessions[_digest(token)] = record
            elif record.owner is not None:
                record.idle = min(now + timedelta(seconds=900), record.absolute)
                replacement = token  # Refresh cookie lifetime without rotating the identifier.
            view, lease = self._view(token, record)
            return view, lease, replacement

    def pair(self, token, csrf, code: SecretStr, peer):
        with self._lock:
            now = self._time()
            record = self._record(token, now)
            self._csrf(record, csrf)
            self._prune(now)
            self._window(record.attempts, now)
            attempts = self._peers.get(peer, deque())
            if len(record.attempts) >= 5 or len(attempts) >= 5 or len(self._attempts) >= 30:
                raise BrowserAuthError("AUTH_RATE_LIMITED")
            self._peers[peer] = attempts
            for window in (record.attempts, attempts, self._attempts):
                window.append(now)
            candidate = _digest(code.get_secret_value())
            if self._pairing is None or not hmac.compare_digest(candidate, self._pairing[0]):
                raise BrowserAuthError("LOGIN_FAILED")
            self._pairing = None
            for digest, item in list(self._sessions.items()):
                if item.owner is not None or digest == _digest(token):
                    del self._sessions[digest]
            token = secrets.token_urlsafe(32)
            record = _Session(
                OwnerContext(owner_id="local-user"),
                SecretStr(secrets.token_urlsafe(32)),
                now + timedelta(seconds=900),
                now + timedelta(seconds=3600),
            )
            self._sessions[_digest(token)] = record
            view, lease = self._view(token, record)
            return view, lease, token

    def logout(self, token, csrf):
        with self._lock:
            self._csrf(self._record(token, self._time()), csrf)
            del self._sessions[_digest(token)]

    def validate_csrf(self, token, csrf):
        with self._lock:
            self._csrf(self._record(token, self._time()), csrf)

    def owner_context(self, token):
        return self.authorize(token)[0]

    def authorize(self, token):
        with self._lock:
            record = self._record(token, self._time())
            if record.owner is None:
                raise BrowserAuthError("SESSION_REQUIRED")
            return record.owner, self._view(token, record)[1]

    def check_lease(self, lease):
        with self._lock:
            now = self._time()
            record = self._sessions.get(lease.digest)
            if record is None or lease.generation != self._generation:
                raise BrowserAuthError("SESSION_REQUIRED")
            if now >= min(record.idle, record.absolute):
                raise BrowserAuthError("SESSION_EXPIRED")
            return max(0, int((min(record.idle, record.absolute) - now).total_seconds()))


def request_context(request: Request, *, allow_query=False, allow_idempotency=False):
    store = getattr(request.app.state, "browser_sessions", None)
    if not isinstance(store, BrowserSessions):
        raise BrowserAuthError("AUTH_NOT_CONFIGURED")
    config = store.config
    headers = request.headers
    if sum(len(k) + len(v) + 4 for k, v in request.scope["headers"]) > 8192:
        raise BrowserAuthError("PAYLOAD_TOO_LARGE")
    if any(
        name in headers
        for name in (
            "authorization",
            "proxy-authorization",
            "x-api-key",
            "x-user-id",
            "x-owner-id",
            "x-role",
        )
    ):
        raise BrowserAuthError("CREDENTIAL_HEADER_FORBIDDEN")
    if any(
        name == "forwarded" or name.startswith("x-forwarded-") or name == "x-real-ip"
        for name in headers
    ):
        raise BrowserAuthError("ORIGIN_FORBIDDEN")
    try:
        client, server = request.scope.get("client"), request.scope.get("server")
        address = ipaddress.ip_address(client[0]) if client else None
        if (
            address is None
            or not address.is_loopback
            or isinstance(address, ipaddress.IPv6Address)
            and address.ipv4_mapped is not None
            or server is None
            or tuple(server) != (config.host, config.port)
            or request.scope["scheme"] != ("https" if config.secure else "http")
            or headers.getlist("host") != [urlsplit(config.origin).netloc]
        ):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise BrowserAuthError("ORIGIN_FORBIDDEN") from None
    origins, sites = headers.getlist("origin"), headers.getlist("sec-fetch-site")
    if (
        origins
        and origins != [config.origin]
        or sites
        and sites not in (["same-origin"], ["none"])
        or request.method == "GET"
        and not origins
        and not sites
        or request.method != "GET"
        and origins != [config.origin]
    ):
        raise BrowserAuthError("ORIGIN_FORBIDDEN")
    if request.url.query and not allow_query:
        raise BrowserAuthError("INVALID_REQUEST")
    if allow_query and len(request.scope.get("query_string", b"")) > 8192:
        raise BrowserAuthError("INVALID_REQUEST")
    if "idempotency-key" in headers and not allow_idempotency:
        raise BrowserAuthError("UNEXPECTED_IDEMPOTENCY_KEY")
    if len(headers.getlist("cookie")) > 1:
        raise BrowserAuthError("SESSION_REQUIRED")
    cookies = []
    for item in headers.get("cookie", "").split(";"):
        if not item.strip():
            continue
        name, separator, value = item.strip().partition("=")
        if not separator or not name or name.strip() != name:
            raise BrowserAuthError("SESSION_REQUIRED")
        if name in ("ghost_demo_session", "__Host-ghost_session"):
            cookies.append((name, value))
    if len(cookies) > 1 or cookies and cookies[0][0] != config.cookie_name:
        raise BrowserAuthError("SESSION_REQUIRED")
    csrf = headers.getlist("x-ghost-csrf")
    return store, cookies[0][1] if cookies else None, csrf[0] if len(csrf) == 1 else None
