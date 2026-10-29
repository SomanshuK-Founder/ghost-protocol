"""Explicit v1.3 capability after SAFE_STOPPED; never invoked by a restarted graph node."""

import asyncio
import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from app.agent.controlled_contracts import ControlledExecutionResult
from app.agent.gateway_protocol import ContractModel, OpaqueReference
from app.agent.http_gateway import (
    ERROR_CODES,
    MAX_BYTES,
    AuthenticatedHttpToolGateway,
    GatewayErrorCode,
    GatewayTransportError,
    _json,
)
from app.agent.workflow_contracts import WorkflowSnapshot


class OperationObservation(ContractModel):
    operation_ref: OpaqueReference
    request_id: OpaqueReference
    task_ref: OpaqueReference
    operation_state: Literal[
        "ADMITTED",
        "PENDING_APPROVAL",
        "READY",
        "DENIED",
        "DISPATCHING",
        "SUCCEEDED",
        "FAILED",
        "UNKNOWN",
    ]
    decision: Literal["ALLOW", "DENY", "APPROVAL_REQUIRED"]
    execution_status: Literal["NOT_EXECUTED", "SUCCEEDED", "FAILED", "UNKNOWN"]
    reason_code: OpaqueReference
    approval_ref: OpaqueReference | None
    approval_state: Literal["PENDING", "APPROVED", "REJECTED", "EXPIRED", "REVOKED"] | None
    resume_ref: OpaqueReference | None
    audit_event_ref: OpaqueReference
    revision: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def consistent(self):
        expected = (
            "UNKNOWN"
            if self.operation_state in ("DISPATCHING", "UNKNOWN")
            else self.operation_state
            if self.operation_state in ("SUCCEEDED", "FAILED")
            else "NOT_EXECUTED"
        )
        if self.execution_status != expected or (
            self.resume_ref is not None and self.approval_state != "APPROVED"
        ):
            raise ValueError("Contradictory operation observation")
        return self


class ControlledExecutionClient:
    def __init__(self, *, enabled=False, **configuration):
        if enabled is not True:
            raise ValueError("Explicit trusted execution enablement required")
        self._auth = AuthenticatedHttpToolGateway(**configuration)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()

    async def aclose(self):
        await self._auth.aclose()

    def _binding(self, binding):
        value = WorkflowSnapshot.model_validate_json(binding.model_dump_json(), strict=True)
        if value.task_ref != self._auth.task_ref:
            raise ValueError("Wrong trusted task")
        return value

    async def _exchange(self, method, path, payload=None):
        try:
            async with asyncio.timeout(self._auth.deadline_seconds):
                token = await self._auth._credential()
                async with self._auth._client.stream(
                    method,
                    path,
                    json=payload,
                    headers={
                        "Authorization": "Bearer " + token.get_secret_value(),
                        "Accept-Encoding": "identity",
                    },
                ) as response:
                    if 300 <= response.status_code < 400:
                        raise ValueError("Redirect forbidden")
                    if (
                        response.headers.get("content-type", "").split(";")[0].strip().lower()
                        != "application/json"
                        or response.headers.get("content-encoding", "identity") != "identity"
                    ):
                        raise ValueError("Invalid response media")
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        if len(body) + len(chunk) > MAX_BYTES:
                            raise ValueError("Response size exceeded")
                        body.extend(chunk)
                    data = _json(bytes(body))
                    if response.status_code != 200:
                        codes = set(ERROR_CODES.get(response.status_code, ()))
                        if response.status_code == 403:
                            codes.add("ACTION_DISABLED")
                        if (
                            set(data)
                            != {
                                "error_code",
                                "message",
                                "correlation_ref",
                                "request_id",
                                "audit_event_ref",
                                "execution_uncertain",
                            }
                            or data.get("error_code") not in codes
                            or type(data.get("execution_uncertain")) is not bool
                        ):
                            raise ValueError("Unknown execution error")
                        from app.agent.http_gateway import REFERENCE

                        REFERENCE.validate_python(data["correlation_ref"], strict=True)
                        for key in ("request_id", "audit_event_ref"):
                            if data[key] is not None:
                                REFERENCE.validate_python(data[key], strict=True)
                        if not isinstance(data["message"], str) or len(data["message"]) > 512:
                            raise ValueError("Invalid execution error")
                        raise GatewayTransportError(
                            GatewayErrorCode.HTTP_ERROR,
                            http_status=response.status_code,
                            server_error_code=data["error_code"],
                            execution_uncertain=data.get("execution_uncertain") is True,
                        )
                    return bytes(body)
        except GatewayTransportError:
            raise
        except Exception:
            pass
        raise GatewayTransportError(GatewayErrorCode.INVALID_RESPONSE, execution_uncertain=True)

    async def status(self, binding):
        try:
            binding = self._binding(binding)
            raw = await self._exchange("GET", "/api/gateway/v1/operations/" + binding.request_id)
            result = OperationObservation.model_validate_json(raw, strict=True)
            if (result.task_ref, result.request_id, result.operation_ref, result.approval_ref) != (
                binding.task_ref,
                binding.request_id,
                binding.operation_ref,
                binding.approval_ref,
            ):
                raise ValueError("Wrong operation observation")
            return result
        except GatewayTransportError:
            raise
        except Exception:
            pass
        raise GatewayTransportError(GatewayErrorCode.INVALID_RESPONSE, execution_uncertain=True)

    async def execute_completed(self, binding, request, *, resume_ref, expected_version=None):
        try:
            from app.agent.http_gateway import REFERENCE

            binding = self._binding(binding)
            request, _ = self._auth._request(request)
            REFERENCE.validate_python(resume_ref, strict=True)
            if binding.phase != "RESUMED" or (
                request.task_ref,
                request.request_id,
                request.idempotency_key,
            ) != (binding.task_ref, binding.request_id, binding.idempotency_key):
                raise ValueError("Completed workflow required")
            arguments = request.arguments.model_dump(mode="json")
            if "recipient" in arguments:
                local, domain = arguments["recipient"].rsplit("@", 1)
                arguments["recipient"] = local + "@" + domain.lower()
            wire = dict(
                version="gw-wire-v1",
                owner_id=binding.owner_ref,
                task_ref=request.task_ref,
                action=request.action.value,
                purpose=request.purpose,
                arguments=arguments,
            )
            digest = hashlib.sha256(
                json.dumps(
                    wire, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
                ).encode()
            ).hexdigest()
            if digest != binding.canonical_request_digest:
                raise ValueError("Original proposal identity required")
            mode = {
                "files.read": "SIMULATED",
                "email.draft": "EMAIL_DRAFT",
                "email.send": "MAILPIT_SEND",
            }.get(request.action.value)
            if mode is None:
                raise ValueError("Unsupported execution action")
            if mode == "SIMULATED":
                REFERENCE.validate_python(expected_version, strict=True)
            raw = await self._exchange(
                "POST",
                "/api/gateway/v1/operations/" + binding.request_id + "/resume",
                {"resume_ref": resume_ref},
            )
            result = ControlledExecutionResult.model_validate_json(raw, strict=True)
            if (
                result.task_ref,
                result.operation_ref,
                result.workflow_ref,
                result.request_id,
                result.idempotency_key,
                result.mode,
            ) != (
                binding.task_ref,
                binding.operation_ref,
                binding.binding_ref,
                binding.request_id,
                binding.idempotency_key,
                mode,
            ):
                raise ValueError("Wrong execution identity")
            if result.result is not None:
                if mode == "SIMULATED" and (
                    result.result.resource_id,
                    result.result.version_ref,
                ) != (request.arguments.resource_id, expected_version):
                    raise ValueError("Wrong synthetic resource")
                if (
                    mode == "EMAIL_DRAFT"
                    and result.result.payload_digest != binding.canonical_request_digest
                ):
                    raise ValueError("Wrong draft digest")
            return result
        except GatewayTransportError:
            raise
        except Exception:
            pass
        raise GatewayTransportError(GatewayErrorCode.INVALID_RESPONSE, execution_uncertain=True)
