"""Explicit trusted-host registration; no tool dispatch or migration application."""

import argparse
import json
import os
import sys
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Register selected synthetic fixture metadata")
    parser.add_argument("--register", action="store_true", required=True)
    parser.add_argument("--fixture", action="append", required=True)
    parser.add_argument("--owner-token-env", default="GHOST_OWNER_TOKEN")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.agent_schemas import OwnerContext
    from app.database import SessionLocal
    from app.security import require_bearer
    from app.services.agent_identity import AgentIdentityError
    from app.services.document_catalog import FixtureRegistration, register_synthetic_resources
    from fastapi import HTTPException
    from pydantic import ValidationError

    try:
        token = os.environ.get(args.owner_token_env, "")
        owner = OwnerContext(owner_id=require_bearer("Bearer " + token))
        selection = FixtureRegistration(fixtures=tuple(args.fixture))
        with SessionLocal() as db:
            resources = register_synthetic_resources(db, owner=owner, selection=selection)
        print(json.dumps({"registered": [r.model_dump(mode="json") for r in resources]}))
        return 0
    except (HTTPException, AgentIdentityError, ValidationError):
        print("Synthetic fixture registration denied", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
