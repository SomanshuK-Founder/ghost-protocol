"""Single-loopback static UI composition; application requests never pass through a proxy."""

import argparse
import base64
import hashlib
import ipaddress
import sys
from html.parser import HTMLParser
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1]
ROOT = FRONTEND.parent
sys.path.insert(0, str(ROOT / "member_a_backend" / "nvidia backend"))

from starlette.responses import FileResponse, PlainTextResponse  # noqa: E402


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inline = False
        self.values = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.inline = "src" not in dict(attrs)

    def handle_endtag(self, tag):
        if tag == "script":
            self.inline = False

    def handle_data(self, data):
        if self.inline:
            self.values.append(data)


def security_headers(path):
    hashes = []
    if path.suffix == ".html":
        parser = Scripts()
        parser.feed(path.read_text(encoding="utf-8"))
        hashes = [
            "'sha256-" + base64.b64encode(hashlib.sha256(v.encode()).digest()).decode() + "'"
            for v in parser.values
        ]
    return {
        "Content-Security-Policy": (
            "default-src 'none'; script-src 'self' "
            + " ".join(hashes)
            + "; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; "
            "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; "
            "object-src 'none'"
        ),
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "X-Frame-Options": "DENY",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Cache-Control": "no-store",
    }


class StaticApplication:
    def __init__(self, public_app, directory=FRONTEND / "out"):
        self.public_app = public_app
        self.directory = directory.resolve()
        # Next requests flattened segment names, but this export writes nested segment files.
        self.segments = {}
        for file in self.directory.rglob("*.txt"):
            relative = file.relative_to(self.directory).as_posix()
            start = relative.find("__next.")
            if start >= 0:
                alias = "/" + relative[:start] + relative[start:].replace("/", ".")
                self.segments[alias] = file

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.public_app(scope, receive, send)
        path = scope["path"]
        if (
            path == "/health"
            or path.startswith("/api/")
            or path in ("/api", "/docs", "/docs/", "/redoc", "/openapi.json")
        ):
            return await self.public_app(scope, receive, send)
        headers = dict(scope["headers"])
        try:
            valid = (
                ipaddress.ip_address(scope["client"][0]).is_loopback
                and headers.get(b"host") == b"127.0.0.1:3000"
                and scope["server"] == ("127.0.0.1", 3000)
            )
            target = (self.directory / path.lstrip("/")).resolve()
            if not target.is_relative_to(self.directory):
                valid = False
        except (ValueError, KeyError, TypeError):
            valid = False
        if not valid:
            return await PlainTextResponse("Local access only", status_code=403)(
                scope, receive, send
            )
        if scope["method"] not in ("GET", "HEAD"):
            return await PlainTextResponse("Method not allowed", status_code=405)(
                scope, receive, send
            )
        if target.is_dir():
            target /= "index.html"
        if not target.is_file():
            target = self.segments.get(path, target)
        if not target.is_file() or not target.resolve().is_relative_to(self.directory):
            return await PlainTextResponse("Not found", status_code=404)(scope, receive, send)
        return await FileResponse(target, headers=security_headers(target))(scope, receive, send)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--pair", action="store_true")
    args = parser.parse_args()
    if args.pair and (not sys.stdin.isatty() or not sys.stdout.isatty()):
        parser.error("Pairing requires a private interactive operator terminal")
    if not (FRONTEND / "out/index.html").is_file():
        parser.error("Run npm run build in frontend first")
    from app.offline_demo import load_demo

    public_app = load_demo(args.directory, pair=args.pair, origin="http://127.0.0.1:3000")
    store = public_app.backend.state.browser_sessions
    if store is not None:
        code = store.issue_pairing_code()
        print("One-use local pairing code (120 seconds): " + code.get_secret_value(), flush=True)
        del code
    import uvicorn

    try:
        uvicorn.run(
            StaticApplication(public_app),
            host="127.0.0.1",
            port=3000,
            workers=1,
            proxy_headers=False,
            forwarded_allow_ips="",
            access_log=False,
        )
    finally:
        if store is not None:
            store.invalidate_all()
        from app.database import engine

        engine.dispose()


if __name__ == "__main__":
    main()
