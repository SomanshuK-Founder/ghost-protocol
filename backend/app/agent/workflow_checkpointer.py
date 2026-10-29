"""Restricted official SQLite saver for the reference-only continuation graph."""

import json
import re
from datetime import datetime
from uuid import UUID

from langgraph.checkpoint.base import get_checkpoint_metadata
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Interrupt

from app.agent.workflow_contracts import WorkflowError, WorkflowSnapshot


def state_only(value):
    if not isinstance(value, dict) or set(value) != {"binding", "phase"}:
        raise ValueError("Only workflow reference state may persist")
    WorkflowSnapshot.model_validate_json(json.dumps(value["binding"]), strict=True)
    if value["phase"] not in ("PAUSED", "SAFE_STOPPED"):
        raise ValueError("Invalid workflow phase")


def channel_only(channel, value):
    if channel == "__start__":
        state_only(value)
    elif channel == "binding":
        WorkflowSnapshot.model_validate_json(json.dumps(value), strict=True)
    elif channel == "phase":
        if value not in ("PAUSED", "SAFE_STOPPED"):
            raise ValueError("Invalid workflow phase")
    elif channel == "__interrupt__":
        for item in value:
            if (
                not isinstance(item, Interrupt)
                or item.response_schema is not None
                or set(item.value) != {"binding_ref", "thread_id"}
            ):
                raise ValueError("Unsafe interrupt value")
            from app.agent.http_gateway import REFERENCE

            for ref in item.value.values():
                REFERENCE.validate_python(ref, strict=True)
    elif channel == "__resume__":
        if isinstance(value, dict) and "binding_ref" in value:
            WorkflowSnapshot.model_validate_json(json.dumps(value), strict=True)
        else:
            if isinstance(value, dict) and any(
                re.fullmatch(r"[0-9a-f]{32}", key) is None for key in value
            ):
                raise ValueError("Invalid interrupt identity")
            for item in value.values() if isinstance(value, dict) else value:
                WorkflowSnapshot.model_validate_json(json.dumps(item), strict=True)
    elif channel != "branch:to:await_approval" or value is not None:
        raise ValueError("Unknown workflow channel")


def checkpoint_only(checkpoint):
    if set(checkpoint) - {
        "v",
        "id",
        "ts",
        "channel_values",
        "channel_versions",
        "versions_seen",
        "pending_sends",
        "updated_channels",
    }:
        raise ValueError("Unexpected checkpoint fields")
    if checkpoint["v"] != 4 or str(UUID(checkpoint["id"])) != checkpoint["id"]:
        raise ValueError("Invalid checkpoint identity")
    if datetime.fromisoformat(checkpoint["ts"]).tzinfo is None or checkpoint.get("pending_sends"):
        raise ValueError("Unsupported checkpoint structure")
    channels = {"__start__", "binding", "phase", "branch:to:await_approval"}
    if set(checkpoint["channel_versions"]) - channels:
        raise ValueError("Unknown versioned channel")
    for value in checkpoint["channel_versions"].values():
        if type(value) not in (int, str) or re.fullmatch(r"[0-9.]{1,100}", str(value)) is None:
            raise ValueError("Invalid channel version")
    for node, versions in checkpoint["versions_seen"].items():
        if (
            node not in ("__input__", "__start__", "await_approval", "__interrupt__")
            or set(versions) - channels
        ):
            raise ValueError("Unknown checkpoint node")
    if set(checkpoint.get("updated_channels") or ()) - channels:
        raise ValueError("Unknown updated channel")
    for channel, value in checkpoint["channel_values"].items():
        channel_only(channel, value)


class WorkflowSqliteSaver(AsyncSqliteSaver):
    """No pickle, custom classes or arbitrary channels/config metadata are persisted."""

    def __init__(self, conn):
        super().__init__(
            conn, serde=JsonPlusSerializer(pickle_fallback=False, allowed_msgpack_modules=None)
        )

    async def aput(self, config, checkpoint, metadata, new_versions):
        try:
            checkpoint_only(checkpoint)
            meta = get_checkpoint_metadata(config, metadata)
            if set(meta) - {"source", "step", "parents"}:
                raise ValueError("Unexpected checkpoint metadata")
            if meta.get("source") not in ("input", "loop", "update", "fork"):
                raise ValueError("Invalid checkpoint source")
            if (
                type(meta.get("step")) is not int
                or meta.get("parents") != {}
                or re.fullmatch(r"wfthread_[0-9a-f]{32}", config["configurable"]["thread_id"])
                is None
            ):
                raise ValueError("Invalid checkpoint metadata")
            clean_config = {
                "configurable": {
                    key: value
                    for key, value in config["configurable"].items()
                    if key in ("thread_id", "checkpoint_ns", "checkpoint_id")
                }
            }
        except Exception:
            raise WorkflowError("CHECKPOINT_REJECTED") from None
        return await super().aput(clean_config, checkpoint, meta, new_versions)

    async def aput_writes(self, config, writes, task_id, task_path=""):
        try:
            for channel, value in writes:
                channel_only(channel, value)
        except Exception:
            raise WorkflowError("CHECKPOINT_REJECTED") from None
        return await super().aput_writes(config, writes, task_id, task_path)

    async def aget_tuple(self, config):
        result = await super().aget_tuple(config)
        if result is not None:
            try:
                checkpoint_only(result.checkpoint)
                for _, channel, value in result.pending_writes or ():
                    channel_only(channel, value)
            except Exception:
                raise WorkflowError("CHECKPOINT_REJECTED") from None
        return result
