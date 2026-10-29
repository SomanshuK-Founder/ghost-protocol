import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace

import pytest
from sqlalchemy.exc import OperationalError
from tests.integration.conftest import (
    EXPECTED_TABLES,
    IntegrationSetupError,
    _install_provisioned_identity_guard,
    _is_mysql_unavailable,
    _setup_failure,
    _skip_reason,
    _validate_test_database,
)
from tests.integration.provisioning import (
    INTEGRATION_USER,
    LOCAL_COMPOSE_PROJECT,
    LOCAL_MYSQL_SERVER_UUID,
    LOCAL_RUNNER_SOURCE_IP,
    AuthorizedTarget,
    ProvisionedCredentials,
    ProvisioningError,
    owner_authorized_local_target,
    provision_integration_account,
    suppress_python_output,
    use_provisioned_credentials,
)


def test_test_database_must_be_isolated(monkeypatch):
    monkeypatch.setattr("tests.integration.conftest.MYSQL_HOST", "db")
    monkeypatch.setattr("tests.integration.conftest.MYSQL_USER", "test-user")
    monkeypatch.setattr("tests.integration.conftest.MYSQL_PASSWORD", "test-password")
    monkeypatch.setattr("tests.integration.conftest.TEST_DATABASE", "nvidia_app")
    monkeypatch.setattr("tests.integration.conftest.APPLICATION_DATABASE", "nvidia_app")
    assert _skip_reason() == "MYSQL_TEST_DATABASE must differ from MYSQL_DATABASE"


def test_test_database_must_end_in_test(monkeypatch):
    monkeypatch.setattr("tests.integration.conftest.MYSQL_HOST", "db")
    monkeypatch.setattr("tests.integration.conftest.MYSQL_USER", "test-user")
    monkeypatch.setattr("tests.integration.conftest.MYSQL_PASSWORD", "test-password")
    monkeypatch.setattr("tests.integration.conftest.TEST_DATABASE", "nvidia_app_staging")
    monkeypatch.setattr("tests.integration.conftest.APPLICATION_DATABASE", "nvidia_app")
    assert _skip_reason() == "MYSQL_TEST_DATABASE must end in _test"


def test_connection_refused_is_the_only_skippable_class():
    unavailable = OperationalError("connect", {}, Exception(2003, "connection refused"))
    denied = OperationalError("connect", {}, Exception(1044, "access denied"))
    assert _is_mysql_unavailable(unavailable) is True
    assert _is_mysql_unavailable(denied) is False


def test_authentication_denied_is_not_skippable():
    denied = OperationalError("connect", {}, Exception(1045, "access denied"))
    assert _is_mysql_unavailable(denied) is False
    failure = _setup_failure(denied)
    assert isinstance(failure, IntegrationSetupError)
    assert "1045" in str(failure)
    assert "access denied" not in str(failure)


def test_unexpected_exception_fails_with_sanitized_diagnostic():
    failure = _setup_failure(RuntimeError("secret-password-value"))
    assert isinstance(failure, IntegrationSetupError)
    assert "RuntimeError" in str(failure)
    assert "secret-password-value" not in str(failure)


def test_database_identity_mismatch_fails_closed():
    class FakeResult:
        def scalar_one(self):
            return "nvidia_app"

    class FakeConnection:
        def execute(self, statement):
            return FakeResult()

    with pytest.raises(IntegrationSetupError, match="does not match"):
        _validate_test_database(FakeConnection())


def test_missing_schema_fails_closed(monkeypatch):
    class FakeResult:
        def scalar_one(self):
            return "nvidia_app_test"

    class FakeConnection:
        def execute(self, statement):
            return FakeResult()

    monkeypatch.setattr(
        "tests.integration.conftest.inspect",
        lambda connection: type("Inspector", (), {"get_table_names": lambda self: {"users"}})(),
    )

    with pytest.raises(IntegrationSetupError, match="missing expected tables"):
        _validate_test_database(FakeConnection())


def test_migration_version_mismatch_fails_closed(monkeypatch):
    class FakeResult:
        def __init__(self, value):
            self.value = value

        def scalar_one(self):
            return self.value

        def scalar_one_or_none(self):
            return self.value

    class FakeConnection:
        def execute(self, statement):
            if "DATABASE" in str(statement):
                return FakeResult("nvidia_app_test")
            return FakeResult("0000_wrong")

    monkeypatch.setattr(
        "tests.integration.conftest.inspect",
        lambda connection: type(
            "Inspector", (), {"get_table_names": lambda self: EXPECTED_TABLES}
        )(),
    )

    with pytest.raises(IntegrationSetupError, match="migration version"):
        _validate_test_database(FakeConnection())


def _authorized_target(**overrides):
    values = {
        "host": "mysql-disposable.example",
        "port": 3306,
        "database": "nvidia_app_test",
        "server_uuid": "server-uuid-84",
        "audit_reference": "change-1234",
        "runner_egress_ip": "192.0.2.40",
        "human_approval_confirmed": True,
        "target_and_egress_independently_verified": True,
    }
    values.update(overrides)
    return AuthorizedTarget(**values)


class _ProvisioningCursor:
    def __init__(
        self,
        *,
        malformed_password=False,
        grant_error=None,
        returned_host="192.0.2.40",
        returned_username=INTEGRATION_USER,
        identity=("8.4.11", "server-uuid-84", 3306, "nvidia_app_test", "admin@192.0.2.40"),
    ):
        self.executed = []
        self.description = None
        self._row = None
        self.malformed_password = malformed_password
        self.grant_error = grant_error
        self.returned_host = returned_host
        self.returned_username = returned_username
        self.identity = identity

    def execute(self, statement):
        self.executed.append(statement)
        if statement.startswith("SELECT VERSION()"):
            self._row = self.identity
        elif statement.startswith("CREATE USER"):
            if self.malformed_password:
                self.description = [(name,) for name in ("user", "host", "password")]
                self._row = (INTEGRATION_USER, "192.0.2.40", "sentinel-password")
            else:
                self.description = [
                    (name,)
                    for name in (
                        "user",
                        "host",
                        "generated password",
                        "auth_factor",
                    )
                ]
                self._row = (
                    self.returned_username,
                    self.returned_host,
                    "sentinel-password",
                    1,
                )
        elif statement.startswith("GRANT") and self.grant_error is not None:
            raise self.grant_error

    def fetchone(self):
        return self._row


class _ProvisioningConnection:
    def __init__(self, cursor, host="mysql-disposable.example", port=3306):
        self._cursor = cursor
        self.host = host
        self.port = port

    def cursor(self):
        return self._cursor

    def escape(self, value):
        return "'" + value.replace("'", "\\'") + "'"


def _owner_local_target(**overrides):
    target = owner_authorized_local_target()
    return replace(target, **overrides)


def _local_cursor(**identity_overrides):
    identity = {
        "version": "8.4.11",
        "server_uuid": LOCAL_MYSQL_SERVER_UUID,
        "port": 3306,
        "database": "nvidia_app_test",
        "user_host": f"admin@{LOCAL_RUNNER_SOURCE_IP}",
    }
    identity.update(identity_overrides)
    return _ProvisioningCursor(
        returned_host=LOCAL_RUNNER_SOURCE_IP,
        identity=(
            identity["version"],
            identity["server_uuid"],
            identity["port"],
            identity["database"],
            identity["user_host"],
        ),
    )


def test_provisioning_target_mismatch_fails_before_account_creation():
    cursor = _ProvisioningCursor()
    connection = _ProvisioningConnection(cursor)
    target = _authorized_target(server_uuid="different-server")

    with pytest.raises(ProvisioningError, match="does not match"):
        provision_integration_account(connection, target)

    assert not any(statement.startswith("CREATE USER") for statement in cursor.executed)


def test_owner_authorized_local_mode_accepts_only_fixed_disposable_target():
    cursor = _local_cursor()
    target = _owner_local_target()

    credentials = provision_integration_account(_ProvisioningConnection(cursor, host="db"), target)

    assert credentials.server_uuid == LOCAL_MYSQL_SERVER_UUID
    assert next(s for s in cursor.executed if s.startswith("GRANT")).startswith(
        "GRANT SELECT, INSERT, UPDATE, CREATE, INDEX, REFERENCES ON `nvidia_app_test`.* "
    )
    assert LOCAL_COMPOSE_PROJECT == target.compose_project


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("compose_project", "another-project"),
        ("host", "other-db"),
        ("port", 3307),
        ("database", "nvidia_app"),
        ("server_uuid", "another-server"),
        ("runner_source_ip", "172.19.0.11"),
    ],
)
def test_owner_authorized_local_mode_rejects_target_mismatch_before_sql(field, value):
    cursor = _local_cursor()
    target = _owner_local_target(**{field: value})

    with pytest.raises(ProvisioningError, match="fixed disposable target"):
        provision_integration_account(_ProvisioningConnection(cursor, host="db"), target)

    assert cursor.executed == []


@pytest.mark.parametrize(
    "identity",
    [
        ("8.4.11", "wrong-server", 3306, "nvidia_app_test", "admin@172.19.0.10"),
        ("8.4.11", LOCAL_MYSQL_SERVER_UUID, 3306, "nvidia_app", "admin@172.19.0.10"),
        ("8.4.11", LOCAL_MYSQL_SERVER_UUID, 3306, "nvidia_app_test", "admin@172.19.0.11"),
    ],
)
def test_owner_authorized_local_mode_rejects_connected_identity_mismatch(identity):
    cursor = _ProvisioningCursor(identity=identity)

    with pytest.raises(ProvisioningError, match="does not match"):
        provision_integration_account(
            _ProvisioningConnection(cursor, host="db"), _owner_local_target()
        )

    assert not any(statement.startswith("CREATE USER") for statement in cursor.executed)


def test_external_target_still_requires_independent_approval():
    cursor = _ProvisioningCursor()
    target = _authorized_target(human_approval_confirmed=False)

    with pytest.raises(ProvisioningError, match="Independent human approval"):
        provision_integration_account(_ProvisioningConnection(cursor), target)

    assert cursor.executed == []


def test_unknown_authorization_target_type_fails_closed():
    cursor = _ProvisioningCursor()

    with pytest.raises(ProvisioningError, match="supported integration target authorization mode"):
        provision_integration_account(_ProvisioningConnection(cursor), object())

    assert cursor.executed == []


def test_provisioning_grants_exact_database_scoped_privileges():
    cursor = _ProvisioningCursor()
    credentials = provision_integration_account(
        _ProvisioningConnection(cursor), _authorized_target()
    )

    grant = next(statement for statement in cursor.executed if statement.startswith("GRANT"))
    assert grant == (
        "GRANT SELECT, INSERT, UPDATE, CREATE, INDEX, REFERENCES "
        "ON `nvidia_app_test`.* TO 'ghost_protocol_integration'@'192.0.2.40'"
    )
    assert "DELETE" not in grant and "DROP" not in grant and "GRANT OPTION" not in grant
    assert "ALTER" not in grant and " ON *.* " not in grant
    assert all("sentinel-password" not in statement for statement in cursor.executed)
    assert "sentinel-password" not in repr(credentials)


def test_provisioning_rejects_wildcard_runner_host_scope():
    cursor = _ProvisioningCursor()
    with pytest.raises(ProvisioningError, match="IP address"):
        provision_integration_account(
            _ProvisioningConnection(cursor),
            _authorized_target(runner_egress_ip="%"),
        )
    assert cursor.executed == []


@pytest.mark.parametrize(
    ("attestation", "value"),
    [
        ("human_approval_confirmed", False),
        ("human_approval_confirmed", 1),
        ("target_and_egress_independently_verified", False),
        ("target_and_egress_independently_verified", "verified"),
    ],
)
def test_provisioning_requires_literal_true_attestations_before_sql(attestation, value):
    cursor = _ProvisioningCursor()
    with pytest.raises(ProvisioningError):
        provision_integration_account(
            _ProvisioningConnection(cursor),
            _authorized_target(**{attestation: value}),
        )

    assert cursor.executed == []


def test_generated_password_host_mismatch_fails_before_grant():
    cursor = _ProvisioningCursor(returned_host="192.0.2.41")
    with pytest.raises(ProvisioningError, match="account state may be partial") as error:
        provision_integration_account(_ProvisioningConnection(cursor), _authorized_target())

    assert "192.0.2.41" not in str(error.value)
    assert not any(statement.startswith("GRANT") for statement in cursor.executed)
    assert not any(statement.startswith("DROP USER") for statement in cursor.executed)


def test_generated_password_username_mismatch_fails_before_grant():
    cursor = _ProvisioningCursor(returned_username="unexpected_user")
    with pytest.raises(ProvisioningError, match="account state may be partial") as error:
        provision_integration_account(_ProvisioningConnection(cursor), _authorized_target())

    assert "sentinel-password" not in str(error.value)
    assert not any(statement.startswith("GRANT") for statement in cursor.executed)
    assert not any(statement.startswith("DROP USER") for statement in cursor.executed)


class _IdentityCursor:
    def __init__(self, identity):
        self.identity = identity
        self.closed = False

    def execute(self, statement):
        assert statement == "SELECT @@server_uuid, @@port, DATABASE()"

    def fetchone(self):
        return self.identity

    def close(self):
        self.closed = True


class _IdentityDBAPIConnection:
    def __init__(self, identity):
        self.identity_cursor = _IdentityCursor(identity)
        self.closed = False
        self.close_error = None

    def cursor(self):
        return self.identity_cursor

    def close(self):
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class _FakeConnectionRecord:
    def __init__(self, dbapi_connection, invalidate_error=None):
        self.dbapi_connection = dbapi_connection
        self.invalidate_error = invalidate_error
        self.invalidated = False

    def invalidate(self):
        if self.invalidate_error is not None:
            raise self.invalidate_error
        self.invalidated = True
        self.dbapi_connection.close()


class _FakeEventEngine:
    def __init__(self):
        self.connect_listener = None
        self.handed_to_test = []
        self.connection_records = []
        self.invalidate_error = None

    def connect(self, dbapi_connection):
        record = _FakeConnectionRecord(dbapi_connection, self.invalidate_error)
        self.connection_records.append(record)
        self.connect_listener(dbapi_connection, record)
        self.handed_to_test.append(dbapi_connection)
        return dbapi_connection


@pytest.mark.parametrize(
    "identity",
    [
        ("wrong-server", 3306, "nvidia_app_test"),
        ("server-uuid-84", 3307, "nvidia_app_test"),
        ("server-uuid-84", 3306, "other_database"),
    ],
)
def test_identity_guard_rejects_mismatched_subsequent_physical_connection(monkeypatch, identity):
    credentials = ProvisionedCredentials(
        INTEGRATION_USER,
        "hidden-secret",
        "mysql-disposable.example",
        3306,
        "nvidia_app_test",
        "server-uuid-84",
    )
    engine = _FakeEventEngine()

    def fake_listen(target, event_name, listener):
        assert target is engine
        assert event_name == "connect"
        target.connect_listener = listener

    monkeypatch.setattr("tests.integration.conftest.event.listen", fake_listen)
    _install_provisioned_identity_guard(engine, credentials)

    first = _IdentityDBAPIConnection(("server-uuid-84", 3306, "nvidia_app_test"))
    assert engine.connect(first) is first

    subsequent = _IdentityDBAPIConnection(identity)
    with pytest.raises(IntegrationSetupError, match="does not match"):
        engine.connect(subsequent)

    assert engine.handed_to_test == [first]
    assert subsequent.identity_cursor.closed is True
    assert subsequent.closed is True
    assert engine.connection_records[-1].invalidated is True


def test_identity_guard_cleanup_failure_preserves_sanitized_error(monkeypatch):
    credentials = ProvisionedCredentials(
        INTEGRATION_USER,
        "hidden-secret",
        "mysql-disposable.example",
        3306,
        "nvidia_app_test",
        "server-uuid-84",
    )
    engine = _FakeEventEngine()
    engine.invalidate_error = RuntimeError("cleanup-secret")

    def fake_listen(target, event_name, listener):
        assert target is engine
        assert event_name == "connect"
        target.connect_listener = listener

    monkeypatch.setattr("tests.integration.conftest.event.listen", fake_listen)
    _install_provisioned_identity_guard(engine, credentials)

    rejected = _IdentityDBAPIConnection(("wrong-server", 3306, "nvidia_app_test"))
    with pytest.raises(IntegrationSetupError, match="does not match") as error:
        engine.connect(rejected)

    assert "cleanup-secret" not in str(error.value)
    assert rejected.closed is True
    assert rejected not in engine.handed_to_test


def test_malformed_generated_password_result_fails_closed():
    cursor = _ProvisioningCursor(malformed_password=True)
    with pytest.raises(ProvisioningError, match="account state may be partial") as error:
        provision_integration_account(_ProvisioningConnection(cursor), _authorized_target())

    assert "sentinel-password" not in str(error.value)
    assert "automatic account cleanup was attempted" in str(error.value)
    assert not any(statement.startswith("DROP USER") for statement in cursor.executed)


def test_grant_failure_is_sanitized_and_does_not_drop_account():
    cursor = _ProvisioningCursor(grant_error=RuntimeError("sentinel-driver-secret"))
    with pytest.raises(ProvisioningError, match="account state may be partial") as error:
        provision_integration_account(_ProvisioningConnection(cursor), _authorized_target())

    message = str(error.value)
    assert "sentinel-driver-secret" not in message
    assert "sentinel-password" not in message
    assert "No automatic account cleanup was attempted" in message
    assert not any(statement.startswith("DROP USER") for statement in cursor.executed)


def test_provisioned_credential_context_ownership_and_primary_error():
    outer = ProvisionedCredentials(
        INTEGRATION_USER,
        "outer-secret",
        "mysql-disposable.example",
        3306,
        "nvidia_app_test",
        "server-uuid-84",
    )
    inner = ProvisionedCredentials(
        INTEGRATION_USER,
        "inner-secret",
        "mysql-disposable.example",
        3306,
        "nvidia_app_test",
        "server-uuid-84",
    )
    from tests.integration.provisioning import current_provisioned_credentials

    with use_provisioned_credentials(outer):
        with pytest.raises(ValueError, match="primary failure"):
            with use_provisioned_credentials(inner):
                assert current_provisioned_credentials() is inner
                raise ValueError("primary failure")
        assert current_provisioned_credentials() is outer
    assert current_provisioned_credentials() is None


def test_provisioned_skip_reason_requires_matching_config(monkeypatch):
    from tests.integration.provisioning import use_provisioned_credentials

    credentials = ProvisionedCredentials(
        INTEGRATION_USER,
        "context-secret",
        "mysql-disposable.example",
        3306,
        "nvidia_app_test",
        "server-uuid-84",
    )
    monkeypatch.setattr("tests.integration.conftest.MYSQL_HOST", credentials.host)
    monkeypatch.setattr("tests.integration.conftest.MYSQL_PORT", "3306")
    monkeypatch.setattr("tests.integration.conftest.TEST_DATABASE", credentials.database)
    monkeypatch.setattr("tests.integration.conftest.APPLICATION_DATABASE", "nvidia_app")
    monkeypatch.setattr("tests.integration.conftest.MYSQL_SERVER_UUID", credentials.server_uuid)

    with use_provisioned_credentials(credentials):
        assert _skip_reason() is None
        monkeypatch.setattr("tests.integration.conftest.MYSQL_SERVER_UUID", "wrong-server")
        assert (
            _skip_reason() == "MYSQL_SERVER_UUID does not match the authorized provisioned target"
        )


def test_python_stream_redirection_only_suppresses_python_streams():
    """Does not cover fd writes, custom logging handlers, or child processes."""
    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    with redirect_stdout(captured_stdout), redirect_stderr(captured_stderr):
        with suppress_python_output():
            print("stdout-secret")
            print("stderr-secret", file=sys.stderr)

    assert captured_stdout.getvalue() == ""
    assert captured_stderr.getvalue() == ""
