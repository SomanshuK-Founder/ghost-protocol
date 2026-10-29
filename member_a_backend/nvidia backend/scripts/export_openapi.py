"""Reproduce frontend/trusted schema artifacts offline; never load private configuration."""

import hashlib
import json
import os
import socket
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch


def main():
    backend = Path(__file__).resolve().parents[1]
    root = backend.parent.parent
    sys.path.insert(0, str(backend))
    out = root / "docs/integration/step44e_logs"
    generated = root / "docs/frontend-handoff/generated"
    out.mkdir(parents=True, exist_ok=True)
    generated.mkdir(parents=True, exist_ok=True)
    attempts = []

    def denied(*args, **kwargs):
        attempts.append("blocked")
        raise AssertionError("Offline schema export forbids network and database connections")

    # Synthetic import-only configuration; no real engine connection or credential discovery.
    environment = {
        key: os.environ[key]
        for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE")
        if key in os.environ
    }
    environment.update(
        DATABASE_URL="sqlite:///schema-export-unused.sqlite",
        API_BEARER_TOKEN="synthetic-schema-export-only",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONIOENCODING="utf-8",
    )
    with ExitStack() as guards:
        guards.enter_context(patch.dict(os.environ, environment, clear=True))
        for owner, name in (
            (socket, "getaddrinfo"),
            (socket, "create_connection"),
            (socket.socket, "connect"),
            (socket.socket, "connect_ex"),
        ):
            guards.enter_context(patch.object(owner, name, denied))
        import pymysql
        from app.config import Settings

        Settings.model_config["env_file"] = None
        guards.enter_context(patch.object(pymysql.connections.Connection, "connect", denied))
        from app.main import app
        from app.openapi import application_schema, inventory

        combined = app.openapi()
        frontend = application_schema(combined)
        rows = inventory(app)
        pairs = [(method, row["path"]) for row in rows for method in row["methods"]]
        assert len(pairs) == len(set(pairs)), "Duplicate route/method registration"
        for name, value in (
            (out / "trusted-backend.openapi.json", combined),
            (out / "route-inventory.json", rows),
            (generated / "ghost-app-v1.openapi.json", frontend),
        ):
            name.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        assert not attempts
    entry = json.loads((out / "entry-files.json").read_text())
    protected = {
        name: expected
        for name, expected in entry.items()
        if "/migrations/" in name
        or name.startswith("fixtures/")
        or name.startswith("docs/frontend-handoff/0")
        or name.startswith("docs/integration/GHOST_APP_V1_A18")
        or name.startswith("docs/integration/STEP4")
        or name.startswith("docs/integration/step4")
    }
    assert all(
        hashlib.sha256((root / p).read_bytes()).hexdigest() == h for p, h in protected.items()
    )
    (out / "preservation.json").write_text(
        json.dumps(
            {
                "protected_files_unchanged": len(protected),
                "migrations_0012_0013_unchanged": True,
                "fixture_manifest_and_payloads_unchanged": True,
                "historical_contracts_evidence_unchanged": True,
                "registered_entries": len(rows),
                "registered_method_path_pairs": len(pairs),
                "network_mysql_attempts": len(attempts),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        "Exported actual frontend/trusted contracts; protected history unchanged; network/MySQL 0"
    )


if __name__ == "__main__":
    main()
