"""Run from Member A's directory; no network or MySQL connections are permitted."""

import socket
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    attempts = []

    def blocked(*args, **kwargs):
        attempts.append("blocked")
        raise AssertionError("Networking and MySQL are forbidden in offline tests")

    async def blocked_async(*args, **kwargs):
        return blocked()

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return original_connect(sock, address)
        return blocked()

    def local_connect_ex(sock, address):
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return original_connect_ex(sock, address)
        return blocked()

    with ExitStack() as guards:
        guards.enter_context(patch.object(socket, "getaddrinfo", blocked))
        guards.enter_context(patch.object(socket, "create_connection", blocked))
        guards.enter_context(patch.object(socket.socket, "connect", local_connect))
        guards.enter_context(patch.object(socket.socket, "connect_ex", local_connect_ex))

        import httpx
        import pymysql
        import pytest
        from app.config import Settings

        # Never load a private .env while collecting tests.
        Settings.model_config["env_file"] = None
        guards.enter_context(patch.object(pymysql.connections.Connection, "connect", blocked))
        guards.enter_context(patch.object(httpx.HTTPTransport, "handle_request", blocked))
        guards.enter_context(
            patch.object(httpx.AsyncHTTPTransport, "handle_async_request", blocked_async)
        )
        args = sys.argv[1:] or ["tests", "-m", "not integration", "-ra"]
        result = pytest.main(args)
    print(f"Network/MySQL attempts: {len(attempts)}")
    return int(result) or int(bool(attempts))


if __name__ == "__main__":
    raise SystemExit(main())
