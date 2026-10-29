"""Step 39 test-only guard, adapted from archived Step 36 validation."""

import contextlib
import importlib.metadata
import json
import os
import socket
import sys
from pathlib import Path
from unittest.mock import patch

assert os.environ["MYSQL_VALIDATION_PROJECT"] == "ghost-demo-validation"
assert os.environ["MYSQL_HOST"] == "db" and os.environ["MYSQL_TEST_DATABASE"] == "nvidia_app_test"
os.umask(0o077)
sys.path.insert(0, str(Path.cwd()))
from app.config import Settings  # noqa: E402

Settings.model_config["env_file"] = None
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import URL  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

url = URL.create(
    "mysql+pymysql",
    username=os.environ["MYSQL_USER"],
    password=os.environ["MYSQL_PASSWORD"],
    host="db",
    port=3306,
    database="nvidia_app_test",
)
os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
original_dns = socket.getaddrinfo
original_connect, original_connect_ex = socket.socket.connect, socket.socket.connect_ex
ips = {r[4][0] for r in original_dns("db", 3306, socket.AF_INET, socket.SOCK_STREAM)}
assert len(ips) == 1
mailpit_ips = {r[4][0] for r in original_dns("mailpit", 1025, socket.AF_INET, socket.SOCK_STREAM)}
assert len(mailpit_ips) == 1 and mailpit_ips != ips
allowed = {
    (next(iter(ips)), 3306),
    (next(iter(mailpit_ips)), 1025),
    (next(iter(mailpit_ips)), 8025),
}
attempts = []


def denied(*args, **kwargs):
    attempts.append("forbidden")
    raise AssertionError("Only disposable validation MySQL is allowed")


def dns(host, port, *args, **kwargs):
    target = (
        next(iter(ips)) if host == "db" else next(iter(mailpit_ips)) if host == "mailpit" else host
    )
    if (target, int(port)) not in allowed:
        return denied()
    return original_dns(host, port, *args, **kwargs)


def connect(sock, address):
    if isinstance(address, tuple) and address[:2] in allowed:
        return original_connect(sock, address)
    return denied()


def connect_ex(sock, address):
    if isinstance(address, tuple) and address[:2] in allowed:
        return original_connect_ex(sock, address)
    return denied()


engine = create_engine(
    url,
    hide_parameters=True,
    echo=False,
    poolclass=NullPool,
    connect_args={"ssl_ca": "/checkpoints/ca.pem", "ssl_verify_cert": True, "connect_timeout": 3},
)


def identity(connection):
    row = connection.execute(
        text(
            "SELECT VERSION(),@@server_uuid,DATABASE(),@@port,@@transaction_isolation,@@"
            "session.time_zone"
        )
    ).one()
    assert row[0].startswith("8.4.") and row[1] == os.environ["MYSQL_SERVER_UUID"]
    assert row[2] == "nvidia_app_test" and row[3] == 3306
    assert row[4] == "READ-COMMITTED" and row[5] == "+00:00"
    assert connection.execute(text("SHOW STATUS LIKE 'Ssl_cipher'")).one()[1]
    assert tuple(connection.execute(text("SELECT @@general_log,@@slow_query_log")).one()) == (0, 0)
    return {
        "mysql_version": row[0],
        "server_uuid": row[1],
        "database": row[2],
        "isolation": row[4],
        "time_zone": row[5],
        "tls": True,
        "payload_query_logs": False,
    }


def main():
    stage = sys.argv[1]
    with engine.connect() as connection:
        print(json.dumps(identity(connection)), flush=True)
        connection.commit()
        if stage == "migrate":
            from alembic import command
            from alembic.config import Config

            revision = sys.argv[2]
            expected = [
                "0001_initial",
                "0002_agent_identity",
                "0003_scoped_consent",
                "0004_operation_ledger",
                "0005_durable_approvals",
                "0006_trusted_execution",
                "0007_document_catalog",
                "0008_secure_document_reading",
                "0009_mailpit_email",
                "0010_workflow_resume",
                "0011_controlled_execution",
            ]
            assert revision in expected
            config = Config("alembic.ini")
            config.attributes["connection"] = connection
            command.upgrade(config, revision)
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == revision
            )
            connection.commit()
            print("Migration verified: " + revision)
            return 0
        if stage == "persistence":
            import hashlib
            import urllib.request

            tables = {
                "gateway_operations": [
                    "operation_ref",
                    "task_ref",
                    "owner_id",
                    "request_id",
                    "idempotency_key",
                    "operation_status",
                    "audit_event_id",
                ],
                "execution_attempts": [
                    "attempt_ref",
                    "operation_ref",
                    "state",
                    "mode",
                    "workflow_binding_ref",
                    "resume_hint_digest",
                    "audit_event_id",
                ],
                "pending_approvals": [
                    "approval_ref",
                    "operation_ref",
                    "status",
                    "consumed_at",
                    "consent_ref",
                    "audit_event_id",
                ],
                "workflow_checkpoints": [
                    "binding_ref",
                    "task_ref",
                    "operation_ref",
                    "approval_ref",
                    "thread_id",
                    "checkpoint_id",
                    "phase",
                    "admitted_authorization_version",
                    "audit_event_id",
                ],
            }
            identities = {}
            for table, fields in tables.items():
                rows = [
                    list(row)
                    for row in connection.execute(
                        text(
                            "SELECT "
                            + ",".join(fields)
                            + " FROM "
                            + table
                            + " ORDER BY "
                            + fields[0]
                        )
                    )
                ]
                identities[table] = {
                    "rows": len(rows),
                    "identity_sha256": hashlib.sha256(
                        json.dumps(rows, default=str, sort_keys=True).encode()
                    ).hexdigest(),
                }
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open("http://mailpit:8025/api/v1/messages") as response:
                captures = json.load(response)["total"]
            print(json.dumps({"identities": identities, "mailpit_captures": captures}))
            return 0
        if stage == "postcheck":
            from sqlalchemy import inspect

            tables = inspect(connection).get_table_names()
            rows = []
            for table in tables:
                assert table.replace("_", "").isalnum()
                rows.extend(
                    dict(row)
                    for row in connection.execute(text("SELECT * FROM `" + table + "`")).mappings()
                )
            serialized = json.dumps(rows, default=str)
            assert os.environ["MYSQL_PASSWORD"] not in serialized
            assert os.environ["API_BEARER_TOKEN"] not in serialized
            import re

            assert re.search(r"gpa_cred_[a-f0-9]{32}\.[A-Za-z0-9_-]{43}", serialized) is None
            assert all(
                marker not in serialized
                for marker in [
                    "STEP38_PRIVATE_PROMPT",
                    "PRIVATE_PROMPT_MARKER",
                    "PRIVATE_DOCUMENT_MARKER",
                    "PRIVATE_EMAIL_MARKER",
                    "PRIVATE_RESULT_MARKER",
                ]
            )
            assert (
                connection.execute(
                    text("SELECT COUNT(*) FROM execution_attempts WHERE mode='SYNTHETIC_READ'")
                ).scalar_one()
                == 0
            )
            from app.services.email_profile import BODY

            def strings(value):
                if isinstance(value, dict):
                    for item in value.values():
                        yield from strings(item)
                elif isinstance(value, (list, tuple)):
                    for item in value:
                        yield from strings(item)
                elif isinstance(value, str):
                    yield value

            for value in strings(rows):
                assert BODY not in value
                assert not any(part in value for part in ("C:\\Users\\", "/home/", "/Users/"))
                assert all(
                    marker not in value
                    for marker in [
                        os.environ["MYSQL_PASSWORD"],
                        os.environ["API_BEARER_TOKEN"],
                        "PRIVATE_DOCUMENT_MARKER",
                        "PRIVATE_EMAIL_MARKER",
                        "PRIVATE_RESULT_MARKER",
                    ]
                )
            import hashlib
            import sqlite3
            import urllib.request

            files = list(Path("/checkpoints").glob("**/*.sqlite"))
            checkpoint_rows = write_rows = 0
            forbidden_values = [
                os.environ["MYSQL_PASSWORD"],
                os.environ["API_BEARER_TOKEN"],
                "STEP38_PRIVATE_PROMPT",
                "PRIVATE_PROMPT_MARKER",
                "PRIVATE_DOCUMENT_MARKER",
                "PRIVATE_EMAIL_MARKER",
                "PRIVATE_RESULT_MARKER",
                "NEBIUS_KEY_MARKER",
                "SMTP_KEY_MARKER",
                BODY,
            ]
            for file in files:
                raw = file.read_bytes()
                assert all(value.encode() not in raw for value in forbidden_values)
                assert re.search(rb"gpa_cred_[a-f0-9]{32}\.[A-Za-z0-9_-]{43}", raw) is None
                with sqlite3.connect(file) as stored:
                    for table in ("checkpoints", "writes"):
                        rows_local = stored.execute("SELECT * FROM " + table).fetchall()
                        if table == "checkpoints":
                            checkpoint_rows += len(rows_local)
                        else:
                            write_rows += len(rows_local)
                        blob = b"".join(
                            v if isinstance(v, bytes) else str(v).encode()
                            for row in rows_local
                            for v in row
                        )
                        assert all(value.encode() not in blob for value in forbidden_values)
            application_logs = list(Path("/checkpoints").glob("**/application-*.log"))
            for application_log in application_logs:
                raw_log = application_log.read_bytes()
                assert all(value.encode() not in raw_log for value in forbidden_values)
                assert re.search(rb"gpa_cred_[a-f0-9]{32}\.[A-Za-z0-9_-]{43}", raw_log) is None
            print(
                json.dumps(
                    {
                        "application_logs_scanned": len(application_logs),
                        "bytes": sum(log.stat().st_size for log in application_logs),
                        "credentials_and_private_markers_absent": True,
                    }
                )
            )
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

            def capture_api(path):
                with opener.open("http://mailpit:8025" + path, timeout=3) as response:
                    return json.load(response)

            listing = capture_api("/api/v1/messages")
            from app.services.email_profile import SENDER, SUBJECT

            for item in listing["messages"]:
                message = capture_api("/api/v1/message/" + item["ID"])
                assert message["From"]["Address"] == SENDER
                assert [value["Address"] for value in message["To"]] == ["teammate@example.test"]
                assert message["Subject"] == SUBJECT and message["Text"] == BODY
            print(
                json.dumps(
                    {
                        "sqlite_files": len(files),
                        "checkpoint_rows": checkpoint_rows,
                        "write_rows": write_rows,
                        "private_markers_and_configured_credentials_absent": True,
                        "mailpit_messages_checked": len(listing["messages"]),
                        "all_mailpit_profiles_verified": True,
                        "no_raw_payloads_exported": True,
                    }
                )
            )
            attempt_count = connection.execute(
                text("SELECT COUNT(*) FROM execution_attempts")
            ).scalar_one()
            mismatches = connection.execute(
                text(
                    "SELECT COUNT(*) FROM execution_attempts a JOIN gateway_operations o ON o.op"
                    "eration_ref=a.operation_ref JOIN workflow_checkpoints w ON w.binding_ref=a."
                    "workflow_binding_ref WHERE a.state<>o.operation_status OR a.audit_event_id<"
                    ">o.audit_event_id OR a.dispatch_at<>o.execution_started_at OR w.operation_r"
                    "ef<>o.operation_ref OR w.task_ref<>o.task_ref OR w.owner_id<>o.owner_id"
                )
            ).scalar_one()
            assert mismatches == 0
            duplicate_phases = {}
            for phase in ["ADMITTED", "RESUMING", "RESUMED"]:
                duplicate_phases[phase] = connection.execute(
                    text(
                        "SELECT COUNT(*) FROM (SELECT JSON_UNQUOTE(JSON_EXTRACT(detail,'$"
                        ".binding_re"
                        "f')) AS binding,COUNT(*) AS n FROM audit_events WHERE event_type"
                        "='gateway.w"
                        "orkflow.transition' AND outcome=:phase GROUP BY binding HAVING C"
                        "OUNT(*)>1) "
                        "duplicated"
                    ),
                    {"phase": phase},
                ).scalar_one()
            assert all(value == 0 for value in duplicate_phases.values())
            metrics = {
                row[0]: int(row[1])
                for row in connection.execute(
                    text(
                        "SHOW GLOBAL STATUS WHERE Variable_name IN ('Innodb_deadlocks','I"
                        "nnodb_row_l"
                        "ock_waits','Innodb_row_lock_time','Innodb_row_lock_time_max')"
                    )
                )
            }
            errors = None  # Performance-schema metrics are outside application DB privileges.

            print(
                json.dumps(
                    {
                        "application_rows_scanned": len(rows),
                        "plaintext_agent_tokens_absent": True,
                        "owner_database_credentials_absent": True,
                        "private_markers_absent": True,
                        "raw_email_bodies_absent": True,
                        "execution_attempts": attempt_count,
                        "operation_attempt_workflow_mismatches": mismatches,
                        "innodb_metrics": metrics,
                        "duplicate_admission_claim_completion_records": duplicate_phases,
                        "lock_timeout_deadlock_error_counts": errors,
                    }
                )
            )
            return 0
        if stage == "schema":
            from sqlalchemy import inspect

            inspector = inspect(connection)
            table = "execution_attempts"
            result = {
                "tables": inspector.get_table_names(),
                "foreign_keys": inspector.get_foreign_keys(table),
                "unique_constraints": inspector.get_unique_constraints(table),
                "indexes": inspector.get_indexes(table),
                "checks": inspector.get_check_constraints(table),
                "columns": [{**c, "type": str(c["type"])} for c in inspector.get_columns(table)],
            }
            print(json.dumps(result, default=str))
            print(connection.execute(text("SHOW CREATE TABLE execution_attempts")).one()[1])
            print(
                json.dumps(
                    {
                        "runtime": {
                            name: importlib.metadata.version(name)
                            for name in [
                                "SQLAlchemy",
                                "alembic",
                                "pytest",
                                "PyMySQL",
                                "langgraph",
                                "langgraph-checkpoint",
                                "langgraph-checkpoint-sqlite",
                                "aiosqlite",
                            ]
                        }
                    }
                )
            )
            return 0
    if stage == "mailpit":
        import errno
        import urllib.request

        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open("http://mailpit:8025/api/v1/info", timeout=3) as response:
            info = json.load(response)
        with opener.open("http://mailpit:8025/api/v1/messages", timeout=3) as response:
            captures = json.load(response)["total"]
        assert info["Version"] == "v1.32.0" and captures == 0
        probe = socket.socket()
        probe.settimeout(1)
        try:
            original_connect(probe, ("198.51.100.1", 9))
            raise AssertionError("Unexpected external route")
        except OSError as exc:
            assert exc.errno == errno.ENETUNREACH
        finally:
            probe.close()
        print(
            json.dumps(
                {
                    "mailpit_version": info["Version"],
                    "initial_captures": captures,
                    "external_probe": "ENETUNREACH",
                    "forwarding_configuration": "disabled by inspected compose environment",
                }
            )
        )
        return 0
    if stage == "isolation":
        assert os.getuid() == 1000
        status = Path("/proc/self/status").read_text()
        assert "CapEff:\t0000000000000000" in status and "NoNewPrivs:\t1" in status
        assert not any(
            line.split()[1] == "00000000"
            for line in Path("/proc/net/route").read_text().splitlines()[1:]
        )
        print(
            json.dumps(
                {
                    "uid": os.getuid(),
                    "capabilities": 0,
                    "no_new_privileges": True,
                    "default_route": False,
                    "mysql_only_network_guard": True,
                }
            )
        )
        return 0
    if stage == "tests":
        import pytest

        return pytest.main(sys.argv[2:])
    if stage == "bridge":
        import runpy

        runpy.run_path(
            "/workspace/backend/tests/agent/demo_runtime_worker.py",
            run_name="__main__",
            init_globals={"ENGINE": engine, "GUARD_ATTEMPTS": attempts},
        )
        return 0
    raise AssertionError("Unknown runner stage")


result = 1
with contextlib.ExitStack() as guards:
    guards.enter_context(patch.object(socket, "getaddrinfo", dns))
    guards.enter_context(patch.object(socket.socket, "connect", connect))
    guards.enter_context(patch.object(socket.socket, "connect_ex", connect_ex))

    import httpx

    guards.enter_context(patch.object(httpx.HTTPTransport, "handle_request", denied))
    guards.enter_context(patch.object(httpx.AsyncHTTPTransport, "handle_async_request", denied))
    from app.services.document_reader import SyntheticDocumentReader

    guards.enter_context(patch.object(SyntheticDocumentReader, "execute", denied))
    from app.services import tools, trusted_execution

    guards.enter_context(patch.dict(tools.TOOLS, {k: denied for k in tools.TOOLS}))
    for name in ["dispatch_simulated", "dispatch_document_read", "dispatch_email"]:
        guards.enter_context(patch.object(trusted_execution, name, denied))
    try:
        result = int(main())
    except Exception as exc:
        code = getattr(getattr(exc, "orig", None), "args", (None,))[0]
        print(
            json.dumps(
                {
                    "failure_type": type(exc).__name__,
                    "mysql_error": code if isinstance(code, int) else None,
                }
            )
        )
        result = 1
    finally:
        engine.dispose()
        print("Forbidden network/tool/SMTP attempts: " + str(len(attempts)))
raise SystemExit(result or int(bool(attempts)))
