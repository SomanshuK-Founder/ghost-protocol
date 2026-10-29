"""Browser listener audience; trusted app.main.app remains the private backend."""

from app.browser_auth import PREFIX, BrowserAuthError
from app.routes.session import failure


class PublicApplication:
    def __init__(self, backend):
        self.backend = backend

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 1008})
        if scope["type"] == "http" and not (
            scope["path"] == "/health" or scope["path"].startswith(PREFIX + "/")
        ):
            return await failure(BrowserAuthError("NOT_FOUND"))(scope, receive, send)
        return await self.backend(scope, receive, send)
