import os
from collections.abc import Generator
from types import SimpleNamespace
from urllib.parse import quote_plus

import pytest
from app.config import get_settings
from app.database import get_db
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool
from tests.integration.provisioning import current_provisioned_credentials

TEST_DATABASE = os.getenv("MYSQL_TEST_DATABASE", "nvidia_app_test")
APPLICATION_DATABASE = os.getenv("MYSQL_DATABASE", "nvidia_app")
MYSQL_HOST = os.getenv("MYSQL_HOST", "")
MYSQL_USER = os.getenv("MYSQL_USER", "")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
MYSQL_SERVER_UUID = os.getenv("MYSQL_SERVER_UUID", "")
EXPECTED_MIGRATION = "0013_application_interfaces"
EXPECTED_TABLES = {
    "alembic_version",
    "users",
    "consent_records",
    "tool_permissions",
    "audit_events",
    "gateway_tasks",
    "agent_credentials",
    "scoped_consents",
    "gateway_operations",
    "pending_approvals",
    "execution_attempts",
    "document_resources",
    "email_artifacts",
    "workflow_checkpoints",
    "application_commands",
}


class IntegrationSetupError(RuntimeError):
    """Raised when MySQL is reachable but integration setup is invalid."""


def _skip_reason() -> str | None:
    provisioned = current_provisioned_credentials()
    if provisioned is not None:
        try:
            configured_port = int(MYSQL_PORT)
        except (TypeError, ValueError):
            return "MYSQL_PORT does not match the authorized provisioned target"
        expected = (
            ("MYSQL_HOST", MYSQL_HOST, provisioned.host),
            ("MYSQL_PORT", configured_port, provisioned.port),
            ("MYSQL_TEST_DATABASE", TEST_DATABASE, provisioned.database),
            ("MYSQL_SERVER_UUID", MYSQL_SERVER_UUID, provisioned.server_uuid),
        )
        for name, configured, authorized in expected:
            if configured != authorized:
                return f"{name} does not match the authorized provisioned target"
        if TEST_DATABASE == APPLICATION_DATABASE:
            return "MYSQL_TEST_DATABASE must differ from MYSQL_DATABASE"
        if not TEST_DATABASE.endswith("_test"):
            return "MYSQL_TEST_DATABASE must end in _test"
        return None

    missing = [
        name
        for name, value in {
            "MYSQL_HOST": MYSQL_HOST,
            "MYSQL_USER": MYSQL_USER,
            "MYSQL_PASSWORD": MYSQL_PASSWORD,
        }.items()
        if not value
    ]
    if missing:
        return f"MySQL integration configuration is missing: {', '.join(missing)}"
    if TEST_DATABASE == APPLICATION_DATABASE:
        return "MYSQL_TEST_DATABASE must differ from MYSQL_DATABASE"
    if not TEST_DATABASE.endswith("_test"):
        return "MYSQL_TEST_DATABASE must end in _test"
    return None


def _mysql_error_code(exc: BaseException) -> int | None:
    original = getattr(exc, "orig", None)
    arguments = getattr(original, "args", ())
    if arguments and isinstance(arguments[0], int):
        return arguments[0]
    return None


def _is_mysql_unavailable(exc: BaseException) -> bool:
    """Return true only for known transport/server-unreachable MySQL errors."""
    return isinstance(exc, OperationalError) and _mysql_error_code(exc) in {
        2002,  # Can't connect to local server
        2003,  # Can't connect to MySQL server
        2005,  # Unknown MySQL server host
        2013,  # Lost connection during connection/query
        2055,  # Lost connection to MySQL server at '%s', system error
    }


def _setup_failure(exc: BaseException) -> IntegrationSetupError:
    code = _mysql_error_code(exc)
    if code is None:
        return IntegrationSetupError(
            f"MySQL integration setup failed with {type(exc).__name__}; "
            "the failure was not classified as server-unavailable"
        )
    return IntegrationSetupError(
        f"MySQL integration setup failed with MySQL error {code}; "
        "credentials, permissions, database selection, or schema may be invalid"
    )


def _validate_test_database(connection) -> None:
    selected_database = connection.execute(text("SELECT DATABASE()")).scalar_one()
    if selected_database != TEST_DATABASE:
        raise IntegrationSetupError(
            f"Connected database {selected_database!r} does not match MYSQL_TEST_DATABASE"
        )

    available_tables = set(inspect(connection).get_table_names())
    missing_tables = EXPECTED_TABLES - available_tables
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise IntegrationSetupError(
            f"Integration database is missing expected tables: {missing}; "
            "run the approved Alembic prerequisite against the isolated test database"
        )

    migration = connection.execute(
        text("SELECT version_num FROM alembic_version")
    ).scalar_one_or_none()
    if migration != EXPECTED_MIGRATION:
        raise IntegrationSetupError(
            f"Integration database migration version {migration!r} does not match "
            f"expected {EXPECTED_MIGRATION!r}"
        )


def _validate_provisioned_dbapi_connection(
    dbapi_connection,
    server_uuid: str,
    port: int,
    database: str,
) -> None:
    cursor = None
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("SELECT @@server_uuid, @@port, DATABASE()")
        row = cursor.fetchone()
        if not isinstance(row, (tuple, list)) or len(row) != 3:
            raise IntegrationSetupError("Connected MySQL server identity result is malformed")
        actual_uuid, actual_port, actual_database = row
        try:
            actual_port = int(actual_port)
        except (TypeError, ValueError):
            raise IntegrationSetupError(
                "Connected MySQL server identity does not match the authorized provisioned target"
            ) from None
        if actual_uuid != server_uuid or actual_port != port or actual_database != database:
            raise IntegrationSetupError(
                "Connected MySQL server identity does not match the authorized provisioned target"
            )
    except IntegrationSetupError:
        raise
    except Exception:
        raise IntegrationSetupError("Could not verify connected MySQL server identity") from None
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass


def _install_provisioned_identity_guard(engine, credentials) -> None:
    expected_uuid = credentials.server_uuid
    expected_port = credentials.port
    expected_database = credentials.database

    def validate_new_connection(dbapi_connection, connection_record) -> None:
        try:
            _validate_provisioned_dbapi_connection(
                dbapi_connection,
                expected_uuid,
                expected_port,
                expected_database,
            )
        except BaseException:
            try:
                connection_record.invalidate()
            except BaseException:
                try:
                    dbapi_connection.close()
                except BaseException:
                    pass
            raise

    event.listen(engine, "connect", validate_new_connection)


@pytest.fixture(scope="session")
def mysql_engine() -> Generator:
    reason = _skip_reason()
    if reason:
        if current_provisioned_credentials() is not None:
            raise IntegrationSetupError(reason)
        pytest.skip(reason)

    provisioned = current_provisioned_credentials()
    if provisioned is None:
        url = (
            f"mysql+pymysql://{quote_plus(MYSQL_USER)}:{quote_plus(MYSQL_PASSWORD)}"
            f"@{MYSQL_HOST}:{MYSQL_PORT}/{TEST_DATABASE}"
        )
    else:
        url = (
            f"mysql+pymysql://{quote_plus(provisioned.username)}:{quote_plus(provisioned.password)}"
            f"@{provisioned.host}:{provisioned.port}/{provisioned.database}"
        )
    engine = create_engine(
        url,
        pool_pre_ping=True,
        poolclass=NullPool,
        echo=False,
        hide_parameters=True,
        connect_args={"ssl_ca": os.environ["MYSQL_SSL_CA"], "ssl_verify_cert": True}
        if os.getenv("MYSQL_SSL_CA")
        else {},
    )
    if provisioned is not None:
        _install_provisioned_identity_guard(engine, provisioned)
    elif os.getenv("MYSQL_VALIDATION_PROJECT"):
        if (
            os.environ["MYSQL_VALIDATION_PROJECT"]
            not in (
                "ghost-mysql-validation",
                "ghost-ledger-validation",
                "ghost-approval-validation",
                "ghost-execution-validation",
                "ghost-catalog-validation",
                "ghost-document-validation",
                "ghost-mailpit-validation",
                "ghost-resume-validation",
            )
            or MYSQL_HOST != "db"
            or MYSQL_PORT != "3306"
            or TEST_DATABASE != "nvidia_app_test"
            or not MYSQL_SERVER_UUID
            or not os.getenv("MYSQL_SSL_CA")
        ):
            engine.dispose()
            raise IntegrationSetupError("Requires the isolated verified Compose target")
        _install_provisioned_identity_guard(
            engine,
            SimpleNamespace(
                server_uuid=MYSQL_SERVER_UUID,
                port=3306,
                database=TEST_DATABASE,
            ),
        )
    try:
        with engine.connect() as connection:
            _validate_test_database(connection)
    except Exception as exc:
        engine.dispose()
        if _is_mysql_unavailable(exc):
            pytest.skip(
                "MySQL service is unavailable at the configured host; "
                f"MySQL error {_mysql_error_code(exc)}"
            )
        if isinstance(exc, IntegrationSetupError):
            raise
        failure = _setup_failure(exc)
        if provisioned is not None:
            raise failure from None
        raise failure from exc

    yield engine
    engine.dispose()


@pytest.fixture
def mysql_session(mysql_engine) -> Generator[Session, None, None]:
    factory = sessionmaker(bind=mysql_engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        yield session


@pytest.fixture
def mysql_client(mysql_engine, monkeypatch) -> Generator[TestClient, None, None]:
    monkeypatch.setenv("API_BEARER_TOKEN", "integration-test-token")
    get_settings.cache_clear()
    factory = sessionmaker(bind=mysql_engine, autoflush=False, expire_on_commit=False)

    def override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


@pytest.fixture
def integration_auth() -> dict[str, str]:
    return {"Authorization": "Bearer integration-test-token"}
