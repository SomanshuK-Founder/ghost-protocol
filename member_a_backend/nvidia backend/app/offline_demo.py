"""Explicit Windows loopback demo, using a disposable ORM snapshot, never MySQL migrations."""

import argparse
import ctypes
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Literal

from pydantic import Field

from app.agent_schemas import IdentityModel

DATABASE = "demo.sqlite3"
MANIFEST = "offline-profile.json"
APPLICATION_ID = 0x4750444D
SNAPSHOT_VERSION = 13


class OfflineDemoError(RuntimeError):
    pass


class OfflineProfile(IdentityModel):
    profile: Literal["ghost-local-offline-v1"] = "ghost-local-offline-v1"
    schema_snapshot: Literal["orm-snapshot-0013_application_interfaces"] = (
        "orm-snapshot-0013_application_interfaces"
    )
    ddl_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def local_directory(value):
    directory = Path(value)
    if (
        os.name != "nt"
        or not directory.is_absolute()
        or directory.drive.startswith("\\\\")
        or ".." in directory.parts
        or not directory.name.startswith("ghost-offline-")
    ):
        raise OfflineDemoError("Use an absolute local Windows ghost-offline-* directory")
    drive_type = ctypes.WinDLL("kernel32", use_last_error=True).GetDriveTypeW
    drive_type.argtypes, drive_type.restype = [ctypes.c_wchar_p], ctypes.c_uint
    if drive_type(directory.anchor) != 3:
        raise OfflineDemoError("The demo requires a local fixed drive, never a network share")
    for path in (directory, *directory.parents):
        if path.exists() or path.is_symlink() or path.is_junction():
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise OfflineDemoError("Links and reparse points are not demo state directories")
    return directory.resolve()


def regular_file(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise OfflineDemoError("Offline state must use regular files without links")


def ddl_digest(engine):
    from sqlalchemy import text

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT type,name,tbl_name,sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
            )
        ).all()
    return hashlib.sha256(json.dumps([list(row) for row in rows]).encode()).hexdigest()


def verify_schema(engine, directory, metadata):
    from sqlalchemy import create_engine, text

    regular_file(directory / DATABASE)
    regular_file(directory / MANIFEST)
    if (directory / MANIFEST).stat().st_size > 4096:
        raise OfflineDemoError("Invalid offline profile")
    profile = OfflineProfile.model_validate_json((directory / MANIFEST).read_bytes())
    reference = create_engine("sqlite://")
    try:
        metadata.create_all(reference)
        expected = ddl_digest(reference)
    finally:
        reference.dispose()
    if profile.ddl_sha256 != expected or ddl_digest(engine) != expected:
        raise OfflineDemoError("Offline ORM snapshot differs; create fresh demo state")
    with engine.connect() as connection:
        if (
            connection.scalar(text("PRAGMA application_id")) != APPLICATION_ID
            or connection.scalar(text("PRAGMA user_version")) != SNAPSHOT_VERSION
            or connection.scalar(text("PRAGMA foreign_keys")) != 1
            or connection.execute(text("PRAGMA foreign_key_check")).first() is not None
            or connection.scalars(text("PRAGMA quick_check")).all() != ["ok"]
        ):
            raise OfflineDemoError("Offline schema/version/integrity checks failed")
    return profile


def load_demo(directory, *, initialize=False, pair=False, origin="http://127.0.0.1:8000"):
    """Trusted fresh-process composition; no existing engine/settings may be overridden."""
    from app.browser_auth import BrowserSessions, LocalDemoConfig
    from app.config import Settings, get_settings

    if (
        "app.database" in sys.modules
        or "app.main" in sys.modules
        or get_settings.cache_info().currsize
    ):
        raise OfflineDemoError(
            "Run the offline entry in a fresh process; production state is not rebound"
        )
    config = LocalDemoConfig(origin)
    if config.secure:
        raise OfflineDemoError("This qualified offline profile uses literal-loopback HTTP only")
    directory = local_directory(directory)
    if initialize:
        directory.mkdir(mode=0o700, exist_ok=False)
        descriptor = os.open(directory / DATABASE, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(descriptor)
    else:
        regular_file(directory / DATABASE)
        regular_file(directory / MANIFEST)
    # A dedicated process gets synthetic settings; private .env/config/credentials never load.
    environment = {
        key: os.environ[key]
        for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE")
        if key in os.environ
    }
    from sqlalchemy import URL

    environment.update(
        DATABASE_URL=URL.create("sqlite", database=str(directory / DATABASE)).render_as_string(),
        API_BEARER_TOKEN="",
        PYTHONDONTWRITEBYTECODE="1",
        LANGSMITH_TRACING="false",
        LANGCHAIN_TRACING_V2="false",
        GHOST_RUN_NEBIUS_LIVE="0",
    )
    os.environ.clear()
    os.environ.update(environment)
    Settings.model_config["env_file"] = None
    from sqlalchemy import event, text

    from app.database import Base, SessionLocal, engine

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    try:
        from app.main import app, public_app
        from app.services.application_host import ApplicationRuntime

        if engine.dialect.name != "sqlite" or SessionLocal.kw["autoflush"] is not False:
            raise OfflineDemoError("Offline composition must retain the shipped session settings")
        if initialize:
            Base.metadata.create_all(engine)
            with engine.begin() as connection:
                connection.execute(text(f"PRAGMA application_id={APPLICATION_ID}"))
                connection.execute(text(f"PRAGMA user_version={SNAPSHOT_VERSION}"))
            from app.agent_schemas import OwnerContext
            from app.services.document_catalog import (
                FixtureRegistration,
                register_synthetic_resources,
            )

            with SessionLocal() as db:
                register_synthetic_resources(
                    db,
                    owner=OwnerContext(owner_id="local-user"),
                    selection=FixtureRegistration(fixtures=("doc_tax_2026", "doc_project_report")),
                )
            profile = OfflineProfile(ddl_sha256=ddl_digest(engine))
            with (directory / MANIFEST).open("x", encoding="utf-8") as output:
                output.write(profile.model_dump_json(indent=2) + "\n")
        verify_schema(engine, directory, Base.metadata)
        runtime = ApplicationRuntime(workflow_directory=directory / "workflows")
        if not runtime.interpreter.is_file() or not runtime.worker.is_file():
            raise OfflineDemoError("The installed Member B interpreter/worker is required")
        app.state.application_runtime = runtime
        app.state.browser_sessions = BrowserSessions(config) if pair else None
        app.openapi_schema = None
        return public_app
    except Exception:
        engine.dispose()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("init", "verify", "serve"):
        item = commands.add_parser(command)
        item.add_argument("--offline", action="store_true", required=True)
        item.add_argument("--directory", required=True, type=Path)
        if command == "serve":
            item.add_argument("--origin", required=True)
            item.add_argument("--pair", action="store_true")
    args = parser.parse_args(argv)
    if getattr(args, "pair", False) and (not sys.stdin.isatty() or not sys.stdout.isatty()):
        parser.exit(2, "Pairing requires a private interactive operator terminal\n")
    try:
        public_app = load_demo(
            args.directory,
            initialize=args.command == "init",
            pair=getattr(args, "pair", False),
            origin=getattr(args, "origin", "http://127.0.0.1:8000"),
        )
        from app.database import engine

        backend = public_app.backend
        store = backend.state.browser_sessions
        try:
            if args.command != "serve":
                print(
                    json.dumps(
                        {
                            "profile": "ghost-local-offline-v1",
                            "schema": "ORM_SNAPSHOT_0013",
                            "foreign_keys": True,
                            "pairing_enabled": False,
                        }
                    )
                )
                return 0
            if store is not None:
                code = store.issue_pairing_code()
                print(
                    "One-use local pairing code (120 seconds): " + code.get_secret_value(),
                    flush=True,
                )
                del code
            import uvicorn

            from app.browser_auth import LocalDemoConfig

            config = LocalDemoConfig(args.origin)
            uvicorn.run(
                public_app,
                host=config.host,
                port=config.port,
                workers=1,
                reload=False,
                proxy_headers=False,
                forwarded_allow_ips="",
                access_log=False,
            )
        finally:
            if store is not None:
                store.invalidate_all()
            backend.state.browser_sessions = None
            engine.dispose()
    except Exception:
        parser.exit(
            2, "Offline demo refused: fresh process, local state and schema verification required\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
