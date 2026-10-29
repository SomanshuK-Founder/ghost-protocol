"""Explicit provisioning helpers for disposable MySQL 8.4.11 targets.

Externally managed targets require independent human approval, verification of
the exact disposable instance, and independent verification of the runner's
egress IP. The supplied audit reference is only an audit reference; it does not
prove authorization. Boolean confirmations and target fields are caller
assertions, not independent verification.

The project owner has separately authorized a narrowly scoped local testing
mode for Compose project ``ghost-protocol-validation-89254b39`` only. That
project policy does not represent independent organizational approval and
does not apply to shared, staging, production, or externally managed targets.
The local target type pins the project name, endpoint alias, database, server
UUID, port, and expected MySQL-observed runner address. The caller must still
verify the Compose project label before using this path.

The helper redirects Python's ``sys.stdout`` and ``sys.stderr`` while it runs.
That does not guarantee suppression of direct file-descriptor writes, custom
logging handlers, or output from external processes. No credentials are placed
in SQL, logged, or included in reprs. Generated credentials remain in memory.

MySQL 8.4.11 documents ``CREATE USER ... IDENTIFIED BY RANDOM PASSWORD`` as
returning one row with columns ``user``, ``host``, ``generated password``, and
``auth_factor``. This helper checks that shape at runtime. Fake-connection
tests exercise parsing and safeguards but do not validate a live MySQL server.
"""

from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
import io
import ipaddress
from typing import Iterator


INTEGRATION_USER = "ghost_protocol_integration"
INTEGRATION_DATABASE = "nvidia_app_test"
REQUESTED_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "CREATE", "INDEX", "REFERENCES")
_GENERATED_PASSWORD_COLUMNS = ("user", "host", "generated password", "auth_factor")

LOCAL_COMPOSE_PROJECT = "ghost-protocol-validation-89254b39"
LOCAL_MYSQL_HOST = "db"
LOCAL_MYSQL_PORT = 3306
LOCAL_MYSQL_SERVER_UUID = "7e2c2d0b-cc8a-11f1-a91a-12c8c7cffc25"
LOCAL_RUNNER_SOURCE_IP = "172.19.0.10"


class ProvisioningError(RuntimeError):
    """Sanitized provisioning failure safe to display to a caller."""


@dataclass(frozen=True)
class AuthorizedTarget:
    """Caller-supplied target facts and attestations; not authorization proof."""

    host: str
    port: int
    database: str
    server_uuid: str
    audit_reference: str
    runner_egress_ip: str
    human_approval_confirmed: bool
    target_and_egress_independently_verified: bool


@dataclass(frozen=True)
class OwnerAuthorizedLocalTarget:
    """Pinned target declaration for owner-authorized local disposable tests.

    This is a project-owner policy path, not independent approval evidence.
    The provisioning call still verifies the connected MySQL identity and
    observed source IP before it creates the integration account.
    """

    compose_project: str
    host: str
    port: int
    database: str
    server_uuid: str
    runner_source_ip: str


def owner_authorized_local_target() -> OwnerAuthorizedLocalTarget:
    """Return the fixed target allowed by the local testing policy."""
    return OwnerAuthorizedLocalTarget(
        compose_project=LOCAL_COMPOSE_PROJECT,
        host=LOCAL_MYSQL_HOST,
        port=LOCAL_MYSQL_PORT,
        database=INTEGRATION_DATABASE,
        server_uuid=LOCAL_MYSQL_SERVER_UUID,
        runner_source_ip=LOCAL_RUNNER_SOURCE_IP,
    )


@dataclass(frozen=True, repr=False)
class ProvisionedCredentials:
    """In-memory credentials; repr intentionally never includes field values."""

    username: str = field(repr=False)
    password: str = field(repr=False)
    host: str = field(repr=False)
    port: int = field(repr=False)
    database: str = field(repr=False)
    server_uuid: str = field(repr=False)

    def __repr__(self) -> str:
        return "<ProvisionedCredentials redacted>"


_active_credentials: ContextVar[ProvisionedCredentials | None] = ContextVar(
    "ghost_protocol_provisioned_credentials", default=None
)


def current_provisioned_credentials() -> ProvisionedCredentials | None:
    return _active_credentials.get()


@contextmanager
def use_provisioned_credentials(
    credentials: ProvisionedCredentials,
) -> Iterator[None]:
    """Install credentials for this invocation and reset only its own token."""
    token: Token[ProvisionedCredentials | None] = _active_credentials.set(credentials)
    try:
        yield
    except BaseException:
        try:
            _active_credentials.reset(token)
        except BaseException:
            # Preserve the invocation's primary exception if token cleanup fails.
            pass
        raise
    else:
        try:
            _active_credentials.reset(token)
        except BaseException:
            raise ProvisioningError(
                "Provisioned credential context cleanup failed."
            ) from None


@contextmanager
def suppress_python_output() -> Iterator[None]:
    """Discard Python-level stdout/stderr only, not fd, logging, or child output."""
    sink = io.StringIO()
    with redirect_stdout(sink), redirect_stderr(sink):
        yield


def _validate_target(target: AuthorizedTarget | OwnerAuthorizedLocalTarget) -> str:
    if isinstance(target, OwnerAuthorizedLocalTarget):
        expected = (
            LOCAL_COMPOSE_PROJECT,
            LOCAL_MYSQL_HOST,
            LOCAL_MYSQL_PORT,
            INTEGRATION_DATABASE,
            LOCAL_MYSQL_SERVER_UUID,
            LOCAL_RUNNER_SOURCE_IP,
        )
        supplied = (
            target.compose_project,
            target.host,
            target.port,
            target.database,
            target.server_uuid,
            target.runner_source_ip,
        )
        if supplied != expected:
            raise ProvisioningError("Owner-authorized local target does not match the fixed disposable target.")
        return LOCAL_RUNNER_SOURCE_IP

    if not isinstance(target, AuthorizedTarget):
        raise ProvisioningError("A supported integration target authorization mode is required.")
    if target.human_approval_confirmed is not True:
        raise ProvisioningError("Independent human approval is required before provisioning.")
    if target.target_and_egress_independently_verified is not True:
        raise ProvisioningError(
            "Independent verification of the disposable target and runner egress IP is required."
        )
    if target.database != INTEGRATION_DATABASE:
        raise ProvisioningError("Authorized target database must be nvidia_app_test.")
    if not target.host or target.host.strip() != target.host or target.host in {"%", "_"}:
        raise ProvisioningError("Authorized target host is invalid.")
    if not isinstance(target.port, int) or isinstance(target.port, bool) or not 1 <= target.port <= 65535:
        raise ProvisioningError("Authorized target port is invalid.")
    if not target.server_uuid or not target.audit_reference:
        raise ProvisioningError("Authorized target server UUID and audit reference are required.")
    try:
        runner_ip = str(ipaddress.ip_address(target.runner_egress_ip))
    except ValueError:
        raise ProvisioningError("Runner egress address must be a verified IP address.") from None
    return runner_ip


def _connection_endpoint(admin_connection) -> tuple[str, int]:
    host = getattr(admin_connection, "host", None)
    port = getattr(admin_connection, "port", None)
    if host is None or port is None:
        raise ProvisioningError("Admin connection endpoint cannot be verified.")
    try:
        return str(host), int(port)
    except (TypeError, ValueError):
        raise ProvisioningError("Admin connection endpoint cannot be verified.") from None


def _validate_connected_target(admin_connection, cursor, target: AuthorizedTarget, runner_ip: str) -> None:
    if _connection_endpoint(admin_connection) != (target.host, target.port):
        raise ProvisioningError("Connected MySQL endpoint does not match the authorized target.")
    cursor.execute("SELECT VERSION(), @@server_uuid, @@port, DATABASE(), USER()")
    row = cursor.fetchone()
    if not isinstance(row, (tuple, list)) or len(row) != 5:
        raise ProvisioningError("Connected MySQL identity result is malformed.")
    version, server_uuid, port, database, user_host = row
    if version != "8.4.11":
        raise ProvisioningError("Connected server is not the authorized MySQL 8.4.11 target.")
    if server_uuid != target.server_uuid or int(port) != target.port:
        raise ProvisioningError("Connected MySQL server identity does not match the authorized target.")
    if database != target.database:
        raise ProvisioningError("Connected database does not match the authorized target.")
    if not isinstance(user_host, str) or "@" not in user_host:
        raise ProvisioningError("MySQL-observed runner address is unavailable.")
    observed_host = user_host.rsplit("@", 1)[1]
    try:
        observed_ip = str(ipaddress.ip_address(observed_host))
    except ValueError:
        raise ProvisioningError("MySQL-observed runner address is not an IP address.") from None
    if observed_ip != runner_ip:
        raise ProvisioningError("MySQL-observed runner address does not match the verified egress IP.")


def _generated_password(cursor, expected_host: str) -> str:
    description = getattr(cursor, "description", None)
    columns = tuple(column[0].lower() for column in description or () if column)
    row = cursor.fetchone()
    if columns != _GENERATED_PASSWORD_COLUMNS or not isinstance(row, (tuple, list)) or len(row) != 4:
        raise ProvisioningError("MySQL generated-password result has an unsupported shape.")
    username, host, password, auth_factor = row
    if username != INTEGRATION_USER or host != expected_host:
        raise ProvisioningError("MySQL generated-password result has an unsupported identity.")
    if not isinstance(password, str) or not password or auth_factor not in (1, "1"):
        raise ProvisioningError("MySQL generated-password result is malformed.")
    return password


def _provision_integration_account(
    admin_connection,
    target: AuthorizedTarget | OwnerAuthorizedLocalTarget,
) -> ProvisionedCredentials:
    runner_ip = _validate_target(target)
    try:
        cursor = admin_connection.cursor()
    except BaseException:
        raise ProvisioningError("Could not initialize the authorized MySQL connection.") from None

    create_attempted = False
    try:
        _validate_connected_target(admin_connection, cursor, target, runner_ip)
        quoted_user = admin_connection.escape(INTEGRATION_USER)
        quoted_host = admin_connection.escape(runner_ip)
        create_attempted = True
        cursor.execute(
            f"CREATE USER {quoted_user}@{quoted_host} IDENTIFIED BY RANDOM PASSWORD"
        )
        password = _generated_password(cursor, runner_ip)
        privileges = ", ".join(REQUESTED_PRIVILEGES)
        cursor.execute(
            f"GRANT {privileges} ON `{INTEGRATION_DATABASE}`.* "
            f"TO {quoted_user}@{quoted_host}"
        )
        return ProvisionedCredentials(
            username=INTEGRATION_USER,
            password=password,
            host=target.host,
            port=target.port,
            database=INTEGRATION_DATABASE,
            server_uuid=target.server_uuid,
        )
    except ProvisioningError as exc:
        if create_attempted:
            raise ProvisioningError(
                "Provisioning failed after CREATE USER was attempted; account state may be partial. "
                "No automatic account cleanup was attempted."
            ) from None
        raise ProvisioningError(str(exc)) from None
    except BaseException:
        if create_attempted:
            raise ProvisioningError(
                "Provisioning failed after CREATE USER was attempted; account state may be partial. "
                "No automatic account cleanup was attempted."
            ) from None
        raise ProvisioningError("Authorized target verification or provisioning setup failed.") from None


def provision_integration_account(
    admin_connection,
    target: AuthorizedTarget | OwnerAuthorizedLocalTarget,
) -> ProvisionedCredentials:
    """Explicitly create the narrowly scoped integration account.

    This function does not connect to MySQL itself. The target must use either
    the independent-approval path or the project-owner-authorized fixed local
    disposable path. It never drops an account, including when CREATE USER may
    have succeeded but a later step fails.
    """
    with suppress_python_output():
        return _provision_integration_account(admin_connection, target)
