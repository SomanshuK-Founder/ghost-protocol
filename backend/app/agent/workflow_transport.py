"""Owner-control transport, injected into trusted workflow host, never model/graph state."""

import asyncio

import httpx
from pydantic import SecretStr

from app.agent.http_gateway import MAX_BYTES, _json, trusted_origin
from app.agent.workflow_contracts import WorkflowError, WorkflowSnapshot

ROOT = "/api/control/v1/workflow-checkpoints"
ERRORS = {
    "WORKFLOW_CONFLICT",
    "WORKFLOW_NOT_PAUSED",
    "WORKFLOW_NOT_APPROVED",
    "WORKFLOW_ALREADY_ADMITTED",
    "WORKFLOW_ALREADY_CLAIMED",
    "WORKFLOW_AUTHORIZATION_CHANGED",
    "WORKFLOW_EXPIRED",
    "WORKFLOW_DENIED",
}


class WorkflowControlClient:
    def __init__(self, *, base_url, owner_credential_provider, transport=None):
        if isinstance(transport, httpx.AsyncHTTPTransport):
            raise ValueError("Real HTTP transports must use verified TLS")
        self._provider = owner_credential_provider
        self._client = httpx.AsyncClient(
            base_url=trusted_origin(base_url),
            verify=True,
            trust_env=False,
            follow_redirects=False,
            timeout=4,
            transport=transport,
        )

    async def aclose(self):
        await self._client.aclose()

    async def call(self, command, payload=None, binding_ref=None):
        error, result = None, None
        try:
            from app.agent.http_gateway import REFERENCE

            if binding_ref is not None:
                REFERENCE.validate_python(binding_ref, strict=True)
            if command not in ("prepare", "pause", "get", "admit", "claim", "complete"):
                raise ValueError("Invalid workflow command")
            path = ROOT + ("/" + binding_ref if binding_ref else "")
            if command not in ("prepare", "get"):
                path += "/" + command
            async with asyncio.timeout(4):
                token = await self._provider()
                if (
                    not isinstance(token, SecretStr)
                    or not token.get_secret_value()
                    or token.get_secret_value().startswith("gpa_")
                    or any(ord(c) < 33 or ord(c) > 126 for c in token.get_secret_value())
                ):
                    raise ValueError("Owner credential required")
                async with self._client.stream(
                    "GET" if command == "get" else "POST",
                    path,
                    json=payload if command != "get" else None,
                    headers={
                        "Authorization": "Bearer " + token.get_secret_value(),
                        "Accept-Encoding": "identity",
                    },
                ) as response:
                    if (
                        response.headers.get("content-type", "").split(";")[0] != "application/json"
                        or response.headers.get("content-encoding", "identity") != "identity"
                    ):
                        raise ValueError("Invalid workflow response")
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        if len(body) + len(chunk) > MAX_BYTES:
                            raise ValueError("Oversized workflow response")
                        body.extend(chunk)
                    data = _json(bytes(body))
                    if response.status_code == 200:
                        result = WorkflowSnapshot.model_validate_json(bytes(body), strict=True)
                        if binding_ref is not None and result.binding_ref != binding_ref:
                            raise ValueError("Wrong workflow binding")
                        for key, value in (payload or {}).items():
                            field = (
                                "authorization_version"
                                if key == "expected_authorization_version"
                                else key
                            )
                            if not hasattr(result, field) or getattr(result, field) != value:
                                raise ValueError("Workflow response identity mismatch")
                        if (
                            command in ("pause", "admit", "claim", "complete")
                            and result.phase
                            != {
                                "pause": "PAUSED",
                                "admit": "ADMITTED",
                                "claim": "RESUMING",
                                "complete": "RESUMED",
                            }[command]
                        ):
                            raise ValueError("Workflow response phase mismatch")
                    else:
                        code = data.get("error_code")
                        error = WorkflowError(
                            code
                            if response.status_code == 409 and code in ERRORS
                            else "WORKFLOW_UNAVAILABLE"
                        )
        except Exception:
            error = WorkflowError()
        if error:
            raise error
        return result
