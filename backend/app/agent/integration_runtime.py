"""Trusted gateway composition; no settings/env loading, inference client or task minting."""

from contextlib import asynccontextmanager

from app.agent.execution_contracts import ExecutionInputError, ExecutionProvenance
from app.agent.http_gateway import AuthenticatedHttpToolGateway
from app.agent.mock_gateway import MockToolGateway
from app.agent.orchestration import GatewayOrchestrator


@asynccontextmanager
async def gateway_runtime(
    model_provider,
    *,
    mode=ExecutionProvenance.MOCK_SIMULATION,
    mock_gateway=None,
    base_url=None,
    task_ref=None,
    credential_provider=None,
    transport=None,
    deadline_seconds=4.0,
    execution_options=None,
    planning_options=None,
    openshell=False,
    ca_bundle=None,
):
    """Only trusted Python construction selects the mode; no public task/config parser."""
    if not isinstance(mode, ExecutionProvenance):
        raise ExecutionInputError("Explicit provenance enum required")
    if mode == ExecutionProvenance.MOCK_SIMULATION:
        if openshell is not False or any(
            value is not None
            for value in (base_url, task_ref, credential_provider, transport, ca_bundle)
        ):
            raise ExecutionInputError("HTTP configuration requires trusted authorization mode")
        yield GatewayOrchestrator(
            model_provider,
            mock_gateway if mock_gateway is not None else MockToolGateway(),
            execution_options=execution_options,
            planning_options=planning_options,
        )
    else:
        if mock_gateway is not None:
            raise ExecutionInputError("Trusted authorization mode requires the HTTP adapter")
        async with AuthenticatedHttpToolGateway(
            base_url=base_url,
            task_ref=task_ref,
            credential_provider=credential_provider,
            transport=transport,
            deadline_seconds=deadline_seconds,
            openshell=openshell,
            ca_bundle=ca_bundle,
        ) as gateway:
            yield GatewayOrchestrator(
                model_provider,
                gateway,
                provenance=ExecutionProvenance.TRUSTED_AUTHORIZATION_ONLY,
                execution_options=execution_options,
                planning_options=planning_options,
            )
