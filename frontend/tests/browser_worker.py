"""Disposable real backend for browser tests; pairing travels only over private stdin/stdout."""

import argparse
import json
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from serve import StaticApplication  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("directory", type=Path)
parser.add_argument("--initialize", action="store_true")
parser.add_argument("--auth-disabled", action="store_true")
args = parser.parse_args()

from app.offline_demo import load_demo  # noqa: E402

public_app = load_demo(
    args.directory,
    initialize=args.initialize,
    pair=not args.auth_disabled,
    origin="http://127.0.0.1:3000",
)
store = public_app.backend.state.browser_sessions
time_shift = timedelta()
if store is not None:
    from app.browser_auth import BrowserSessions

    store = BrowserSessions(store.config, clock=lambda: datetime.now(UTC) + time_shift)
    public_app.backend.state.browser_sessions = store


def emit_code():
    print(json.dumps({"pairing_code": store.issue_pairing_code().get_secret_value()}), flush=True)


def control():
    global time_shift
    for line in sys.stdin:
        if line.strip() == "pair":
            emit_code()
        elif line.strip() == "expire":
            time_shift += timedelta(seconds=901)
            print(json.dumps({"expired": True}), flush=True)
        elif line.startswith("expire_approval:"):
            from app.agent_schemas import OwnerContext
            from app.database import SessionLocal
            from app.services.approvals import owner_approval

            # Only the disposable test database: exercise the existing expiry transition.
            with SessionLocal() as db:
                result = owner_approval(
                    db,
                    owner=OwnerContext(owner_id="local-user"),
                    approval_ref=line.strip().split(":", 1)[1],
                    now=datetime.now(UTC) + timedelta(seconds=601),
                )
            print(json.dumps({"approval_expired": result.state == "EXPIRED"}), flush=True)


if store is not None:
    emit_code()
    threading.Thread(target=control, daemon=True).start()
else:
    print(json.dumps({"auth_disabled": True}), flush=True)

import uvicorn  # noqa: E402

uvicorn.run(
    StaticApplication(public_app),
    host="127.0.0.1",
    port=3000,
    workers=1,
    proxy_headers=False,
    forwarded_allow_ips="",
    access_log=False,
    log_level="error",
)
