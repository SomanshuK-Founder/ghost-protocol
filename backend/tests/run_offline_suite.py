"""From project root: python backend/tests/run_offline_suite.py.

Runs the ordinary complete pytest suite with live opt-in disabled and networking
blocked. Local loopback socket plumbing is allowed for Windows asyncio only;
all real HTTP transports, DNS, and connection helper calls remain blocked.
"""

import os
import socket
from contextlib import ExitStack
from unittest.mock import patch


def main() -> int:
    os.environ["GHOST_RUN_NEBIUS_LIVE"] = "0"
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    attempts: list[str] = []

    def blocked(*args, **kwargs):
        attempts.append("blocked-network-operation")  # Never record endpoint/headers/data.
        raise AssertionError("External networking forbidden during offline acceptance")

    async def blocked_async(*args, **kwargs):
        return blocked()

    original_connect, original_connect_ex = socket.socket.connect, socket.socket.connect_ex

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
        # Import dependencies only after the socket guards are active.
        import httpx
        import httpx2
        import pytest
        import requests

        for library in (httpx, httpx2):
            guards.enter_context(patch.object(library.HTTPTransport, "handle_request", blocked))
            guards.enter_context(
                patch.object(library.AsyncHTTPTransport, "handle_async_request", blocked_async)
            )
        guards.enter_context(patch.object(requests.Session, "request", blocked))
        result = pytest.main(["-q", "-rs"])
        print(f"External network attempts: {len(attempts)}")
        return result or int(bool(attempts))


if __name__ == "__main__":
    raise SystemExit(main())
