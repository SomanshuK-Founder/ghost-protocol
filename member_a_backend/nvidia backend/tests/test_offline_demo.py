"""Disposable CLI and actual-app bootstrap tests, without overriding get_db."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from app.offline_demo import OfflineDemoError, load_demo

BACKEND = Path(__file__).resolve().parents[1]
WORKER = Path(__file__).with_name("offline_demo_worker.py")


def run(tmp_path, *arguments, worker=False):
    environment = {
        name: os.environ[name]
        for name in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE")
        if name in os.environ
    }
    environment.update(
        PYTHONPATH=str(BACKEND),
        PYTHONDONTWRITEBYTECODE="1",
        API_BEARER_TOKEN="private-env-canary",
        MYSQL_PASSWORD="private-env-canary",
        DATABASE_URL="mysql+pymysql://unused:unused@never-connect.example.test/unused",
    )
    command = (
        [sys.executable, "-B", str(WORKER)]
        if worker
        else [sys.executable, "-B", "-m", "app.offline_demo"]
    )
    return subprocess.run(
        [*command, *map(str, arguments)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=100,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def initialize(tmp_path):
    directory = tmp_path / "ghost-offline-test"
    result = run(tmp_path, "init", "--offline", "--directory", directory)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["pairing_enabled"] is False
    return directory


def test_fresh_process_cannot_rebind_production(tmp_path):
    from app.database import SessionLocal, engine

    before = dict(os.environ)
    with pytest.raises(OfflineDemoError, match="fresh process"):
        load_demo(tmp_path / "ghost-offline-unreachable", initialize=True)
    assert dict(os.environ) == before
    assert SessionLocal.kw["bind"] is engine and SessionLocal.kw["autoflush"] is False
    assert not (tmp_path / "ghost-offline-unreachable").exists()


def test_bootstrap_requires_explicit_opt_in(tmp_path):
    result = run(tmp_path, "init", "--directory", tmp_path / "ghost-offline-disabled")
    assert result.returncode == 2 and not (tmp_path / "ghost-offline-disabled").exists()


def test_initialize_verify_and_never_overwrite(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "API_BEARER_TOKEN=dotenv-canary\nDATABASE_URL=mysql+pymysql://unused@never-connect.example.test/unused\n"
    )
    directory = initialize(tmp_path)
    original = (directory / "demo.sqlite3").read_bytes()
    duplicate = run(tmp_path, "init", "--offline", "--directory", directory)
    assert duplicate.returncode == 2 and (directory / "demo.sqlite3").read_bytes() == original
    verified = run(tmp_path, "verify", "--offline", "--directory", directory)
    assert verified.returncode == 0, verified.stderr
    assert "canary" not in verified.stdout + verified.stderr
    with sqlite3.connect(directory / "demo.sqlite3") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 13
        assert (
            db.execute("SELECT name FROM sqlite_master WHERE name='alembic_version'").fetchone()
            is None
        )


@pytest.mark.parametrize("tamper", ["version", "application-id", "schema", "manifest", "orphan"])
def test_schema_version_and_integrity_drift_fail_closed(tmp_path, tamper):
    directory = initialize(tmp_path)
    if tamper == "manifest":
        (directory / "offline-profile.json").write_text('{"profile":"production"}')
    else:
        with sqlite3.connect(directory / "demo.sqlite3") as db:
            if tamper == "version":
                db.execute("PRAGMA user_version=12")
            elif tamper == "application-id":
                db.execute("PRAGMA application_id=0")
            elif tamper == "schema":
                db.execute("CREATE TABLE unexpected(value TEXT)")
            else:
                db.execute(
                    "INSERT INTO agent_credentials "
                    "(credential_ref,token_digest,task_ref,owner_id,credential_epoch,"
                    "issued_at,expires_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    ("cred_fake", "0" * 64, "missing", "local-user", 1, "2026-01-01", "2027-01-01"),
                )
    refused = run(tmp_path, "verify", "--offline", "--directory", directory)
    assert refused.returncode == 2


@pytest.mark.parametrize("directory", ["relative", r"\\remote\share\ghost-offline-test"])
def test_remote_or_relative_state_rejected(tmp_path, directory):
    result = run(tmp_path, "init", "--offline", "--directory", directory)
    assert result.returncode == 2


@pytest.mark.parametrize("mode", ["launcher", "paired-launcher"])
def test_explicit_launcher_preserves_origin_and_pairing_boundary(tmp_path, mode):
    directory = initialize(tmp_path)
    result = run(tmp_path, mode, directory, worker=True)
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["host"] == "127.0.0.1" and observed["port"] == 8000
    assert observed["workers"] == 1 and not observed["proxy_headers"] and not observed["access_log"]
    assert observed["pairing_enabled"] == (mode == "paired-launcher")
    assert observed["pairing_code_prints"] == int(mode == "paired-launcher")


def test_noninteractive_pairing_never_starts(tmp_path):
    directory = initialize(tmp_path)
    result = run(
        tmp_path,
        "serve",
        "--offline",
        "--directory",
        directory,
        "--origin",
        "http://127.0.0.1:8000",
        "--pair",
    )
    assert result.returncode == 2 and "One-use" not in result.stdout


def test_actual_bootstrap_end_to_end_and_process_restart(tmp_path):
    result = run(tmp_path, "flow", tmp_path / "ghost-offline-flow", worker=True)
    assert result.returncode == 0, result.stdout + result.stderr
    observed = json.loads(result.stdout)
    assert observed["actual_session_autoflush"] is False and observed["dependency_overrides"] == 0
    assert observed["approve_http_status"] == 200 and observed["workflow_phase"] == "RESUMED"
    assert observed["unknown_reconciliation"] and observed["restart"]["durable_replay"]
    assert observed["unauthorized_attempts"] == observed["network_mysql_smtp_attempts"] == 0


def test_existing_file_is_never_overwritten(tmp_path):
    target = tmp_path / "ghost-offline-existing"
    target.write_bytes(b"existing-database-sentinel")
    result = run(tmp_path, "init", "--offline", "--directory", target)
    assert result.returncode == 2 and target.read_bytes() == b"existing-database-sentinel"


@pytest.mark.parametrize(
    "origin", ["http://0.0.0.0:8000", "http://localhost:8000", "https://127.0.0.1:8000"]
)
def test_unqualified_origins_never_launch(tmp_path, origin):
    directory = initialize(tmp_path)
    result = run(tmp_path, "serve", "--offline", "--directory", directory, "--origin", origin)
    assert result.returncode == 2
