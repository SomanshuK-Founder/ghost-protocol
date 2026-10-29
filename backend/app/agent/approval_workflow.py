"""Durable metadata-only interrupt/continuation around the unchanged planner/gateway."""

import json
from contextlib import asynccontextmanager
from contextvars import Context
from dataclasses import dataclass
from typing import TypedDict

import aiosqlite
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from app.agent.execution_contracts import AuthorizationAgentResult
from app.agent.graph import configure_planning_environment
from app.agent.workflow_checkpointer import WorkflowSqliteSaver
from app.agent.workflow_contracts import WorkflowError, WorkflowSnapshot, resume_identity


class _State(TypedDict):
    binding: dict
    phase: str


@dataclass(frozen=True)
class _Context:
    claim: dict | None = None


class DurableApprovalWorkflow:
    def __init__(self, control, saver):
        self._control, self._saver = control, saver
        builder = StateGraph(_State, context_schema=_Context)

        def await_approval(state: _State, runtime: Runtime[_Context]):
            # Node restart begins here: no gateway/model/approval work precedes interrupt.
            value = interrupt({key: state["binding"][key] for key in ("binding_ref", "thread_id")})
            if runtime.context is None or runtime.context.claim != value:
                raise WorkflowError("RESUME_AUTHORITY_REQUIRED")
            claim = WorkflowSnapshot.model_validate_json(json.dumps(value), strict=True)
            original = WorkflowSnapshot.model_validate_json(
                json.dumps(state["binding"]), strict=True
            )
            if claim.phase != "RESUMING" or any(
                getattr(claim, key) != getattr(original, key)
                for key in (
                    "binding_ref",
                    "owner_ref",
                    "task_ref",
                    "operation_ref",
                    "approval_ref",
                    "request_id",
                    "idempotency_key",
                    "canonical_request_digest",
                    "thread_id",
                    "workflow_version",
                )
            ):
                raise WorkflowError("RESUME_IDENTITY_MISMATCH")
            return {"binding": value, "phase": "SAFE_STOPPED"}

        builder.add_node("await_approval", await_approval)
        builder.add_edge(START, "await_approval")
        builder.add_edge("await_approval", END)
        self._graph = builder.compile(checkpointer=saver)

    @staticmethod
    def _config(snapshot, *, exact=False):
        config = {
            "configurable": {"thread_id": snapshot.thread_id},
            "callbacks": [],
            "recursion_limit": 4,
        }
        if exact:
            config["configurable"]["checkpoint_id"] = snapshot.checkpoint_id
        return config

    async def _invoke(self, value, config, context):
        import asyncio

        configure_planning_environment()

        async def run():
            from langchain_core.globals import get_debug, get_verbose
            from langchain_core.tracers.context import _tracing_v2_is_enabled

            if get_debug() or get_verbose() or _tracing_v2_is_enabled():
                raise WorkflowError("UNSAFE_TRACING")
            return await self._graph.ainvoke(value, config, context=context, durability="sync")

        task = asyncio.create_task(run(), context=Context())
        return await task

    async def pause(self, result):
        if (
            not isinstance(result, AuthorizationAgentResult)
            or result.execution_outcome != "APPROVAL_REQUIRED"
            or not result.action_results
        ):
            raise WorkflowError("APPROVAL_REQUIRED")
        row = result.action_results[-1]
        binding = await self._control.call(
            "prepare",
            {
                "task_ref": result.task_ref,
                "approval_ref": row.approval_ref,
                "request_id": row.request_ref,
                "idempotency_key": row.idempotency_key,
                "workflow_version": "approval-workflow-v1",
            },
        )
        config = self._config(binding)
        existing = await self._graph.aget_state(config)
        if not existing.values:
            await self._invoke(
                {"binding": binding.model_dump(mode="json"), "phase": "PAUSED"}, config, _Context()
            )
            existing = await self._graph.aget_state(config)
        if existing.next != ("await_approval",) or existing.values["phase"] != "PAUSED":
            raise WorkflowError("CHECKPOINT_NOT_PAUSED")
        if existing.values["binding"]["binding_ref"] != binding.binding_ref:
            raise WorkflowError("CHECKPOINT_IDENTITY_MISMATCH")
        return await self._control.call(
            "pause",
            {"checkpoint_id": existing.config["configurable"]["checkpoint_id"]},
            binding.binding_ref,
        )

    async def execute_task(self, orchestrator, task_ref, user_request, bindings):
        result = await orchestrator.execute_task(task_ref, user_request, bindings)
        return (
            await self.pause(result) if result.execution_outcome == "APPROVAL_REQUIRED" else result
        )

    async def resume(self, binding_ref):
        binding = await self._control.call("get", binding_ref=binding_ref)
        if binding.phase not in ("PAUSED", "ADMITTED"):
            raise WorkflowError("RESUME_NOT_ADMISSIBLE")
        local = await self._graph.aget_state(self._config(binding))
        if (
            local.next != ("await_approval",)
            or local.values.get("phase") != "PAUSED"
            or local.config["configurable"]["checkpoint_id"] != binding.checkpoint_id
            or local.values["binding"]["binding_ref"] != binding.binding_ref
        ):
            raise WorkflowError("CHECKPOINT_IDENTITY_MISMATCH")
        identity = resume_identity(binding)
        if binding.phase == "PAUSED":
            binding = await self._control.call("admit", identity, binding_ref)
        claim = await self._control.call("claim", identity, binding_ref)
        if claim.phase != "RESUMING" or resume_identity(claim) != identity:
            raise WorkflowError("RESUME_IDENTITY_MISMATCH")
        await self._invoke(
            Command(resume=claim.model_dump(mode="json")),
            self._config(binding, exact=True),
            _Context(claim.model_dump(mode="json")),
        )
        final = await self._graph.aget_state(self._config(binding))
        if final.next or final.values.get("phase") != "SAFE_STOPPED":
            raise WorkflowError("RESUME_UNCERTAIN")
        return await self._control.call("complete", identity, binding_ref)


@asynccontextmanager
async def approval_workflow(*, checkpoint_path, control):
    """Path/client are trusted host configuration; graph state never receives credentials."""
    async with aiosqlite.connect(str(checkpoint_path)) as connection:
        saver = WorkflowSqliteSaver(connection)
        await saver.setup()
        yield DurableApprovalWorkflow(control, saver)
