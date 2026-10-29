"""Explicit direct-loopback operator entry; never enabled by app.main or .env."""

import argparse
import sys

from app.browser_auth import BrowserSessions, LocalDemoConfig


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Single-process direct-loopback authentication demo"
    )
    parser.add_argument("--origin", required=True)
    parser.add_argument("--pair", action="store_true", required=True)
    parser.add_argument("--tls-cert")
    parser.add_argument("--tls-key")
    args = parser.parse_args(argv)
    try:
        config = LocalDemoConfig(args.origin)
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise ValueError
        if config.secure != bool(args.tls_cert and args.tls_key):
            raise ValueError
        if not config.secure and (args.tls_cert or args.tls_key):
            raise ValueError
    except ValueError:
        parser.exit(
            2, "Requires a private terminal and direct-loopback origin with matching TLS.\n"
        )

    import uvicorn

    from app.main import app, public_app

    store = BrowserSessions(config)
    app.state.browser_sessions = store
    app.openapi_schema = None
    code = store.issue_pairing_code()
    print("One-use local pairing code (120 seconds): " + code.get_secret_value(), flush=True)
    del code
    try:
        uvicorn.run(
            public_app,
            host=config.host,
            port=config.port,
            workers=1,
            reload=False,
            proxy_headers=False,
            forwarded_allow_ips="",
            access_log=False,
            ssl_certfile=args.tls_cert,
            ssl_keyfile=args.tls_key,
        )
    finally:
        store.invalidate_all()
        app.state.browser_sessions = None


if __name__ == "__main__":
    main()
