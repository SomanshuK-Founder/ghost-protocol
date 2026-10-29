"""Owner application projections and atomic decisions; never imports an executor."""

import base64
import hmac
import json
import re
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import func, select

from app.application_contracts import (
    ApplicationError,
    AppPage,
    ApprovalDetail,
    ApprovalList,
    ApprovalMutation,
    ApprovalSummary,
    CancelResult,
    DocumentMetadata,
    OperationList,
    OperationView,
    Provenance,
    TaskSummary,
    TimelineItem,
    WorkflowView,
)
from app.models import (
    ApplicationCommand,
    AuditEvent,
    DocumentResource,
    ExecutionAttempt,
    GatewayOperation,
    PendingApproval,
    WorkflowCheckpoint,
)
from app.services.agent_identity import _active, _revoke_task_locked, _transaction, _utc
from app.services.application_tasks import (
    _command,
    _detail,
    _existing,
    _owned_application,
    _planning,
    digest,
)
from app.services.approvals import _owner_approval_locked, _owner_operation, reconcile
from app.services.fixture_storage import FIXTURES, STORAGE_REFERENCES
from app.services.operation_ledger import _history, _isolation
from app.services.resource_catalog import EMPTY_CATALOG
from app.services.workflow_resume import _current, _snapshot


def uncertain(operation):
    return operation.operation_status in ("DISPATCHING", "UNKNOWN")


def provenance(db, task, runtime, operation=None):
    from app.services.application_tasks import planning_view

    source = planning_view(_planning(db, task, runtime), task.task_ref).provenance
    if operation is None:
        operation = db.scalar(
            select(GatewayOperation)
            .where(
                GatewayOperation.task_ref == task.task_ref,
                GatewayOperation.owner_id == task.owner_id,
                GatewayOperation.operation_status.in_(
                    ("DISPATCHING", "UNKNOWN", "SUCCEEDED", "FAILED")
                ),
            )
            .order_by(GatewayOperation.created_at.desc())
            .limit(1)
        )
    if operation is None:
        return source
    attempt = db.scalar(
        select(ExecutionAttempt).where(ExecutionAttempt.operation_ref == operation.operation_ref)
    )
    if attempt or operation.operation_status in ("DISPATCHING", "UNKNOWN", "SUCCEEDED", "FAILED"):
        return Provenance(
            planning_source=source.planning_source,
            execution_mode=attempt.mode
            if attempt and attempt.mode in ("SIMULATED", "EMAIL_DRAFT", "MAILPIT_SEND")
            else None,
            effect="UNCONFIRMED",
            evidence="UNATTESTED",
        )
    return Provenance(planning_source=source.planning_source, evidence=source.evidence)


def approval_context(db, owner, reference):
    task, operation, approval, request = _owner_operation(db, owner, reference)
    _owned_application(db, owner, task.task_ref)
    reconcile(db, task, operation, approval, request, EMPTY_CATALOG, _utc(None))
    return task, operation, approval, request


def approval_summary(approval):
    return ApprovalSummary(
        approval_ref=approval.approval_ref,
        task_ref=approval.task_ref,
        operation_ref=approval.operation_ref,
        request_id=approval.request_id,
        state=approval.status,
        expires_at=approval.expires_at,
    )


def approvals(db, owner, task_ref):
    from app.services.approvals import list_pending

    with _transaction(db):
        _owned_application(db, owner, task_ref)
    result = list_pending(db, owner=owner, task_ref=task_ref)
    return ApprovalList(
        items=tuple(ApprovalSummary(task_ref=task_ref, **row) for row in result["approvals"])
    )


def approval_detail(db, owner, reference, runtime):
    with _transaction(db):
        task, operation, approved, _ = approval_context(db, owner, reference)
        reviewed, error = _owner_approval_locked(db, owner=owner, approval_ref=reference)
        if error:
            raise error
        return ApprovalDetail(
            **approval_summary(approved).model_dump(),
            action=reviewed.action,
            purpose=reviewed.purpose,
            arguments=reviewed.arguments,
            resource_versions=reviewed.resource_versions,
            binding_digest=reviewed.binding_digest,
            consumed=approved.consumed_at is not None,
            in_flight=uncertain(operation),
            provenance=provenance(db, task, runtime, operation),
        )


def mutation_view(db, owner, kind, target, runtime):
    if kind == "CANCEL":
        task, profile = _owned_application(db, owner, target)
        detail = _detail(db, task, profile, runtime)
        return CancelResult(
            task=TaskSummary.model_validate(
                {k: getattr(detail, k) for k in TaskSummary.model_fields}
            ),
            in_flight=detail.in_flight,
        )
    _, operation, approved, _ = approval_context(db, owner, target)
    return ApprovalMutation(approval=approval_summary(approved), in_flight=uncertain(operation))


def stored_failure(row):
    if row.state in ("CLAIMED", "UNCERTAIN"):
        return ApplicationError(
            409, "COMMAND_UNCERTAIN", command_ref=row.command_ref, uncertain=True
        )
    return ApplicationError(
        row.failure_http_status,
        row.failure_code,
        command_ref=row.command_ref,
        execution_uncertain=row.failure_code == "RECONCILIATION_REQUIRED",
    )


def mutate(db, owner, kind, target, payload, identity, runtime):
    failure = None
    with _transaction(db):
        _isolation(db)
        if kind == "CANCEL":
            task, _ = _owned_application(db, owner, target)
        else:
            task, operation, approved, _ = approval_context(db, owner, target)
        prior = _existing(db, owner, identity)
        if prior:
            if (
                prior.kind != kind
                or prior.task_ref != task.task_ref
                or (kind != "CANCEL" and prior.approval_ref != target)
            ):
                raise ApplicationError(503, "BACKEND_UNAVAILABLE")
            if prior.state != "SUCCEEDED":
                failure = stored_failure(prior)
            replay = True
        else:
            row = _command(owner, identity, kind, _utc(None), task_ref=task.task_ref)
            if kind != "CANCEL":
                row.approval_ref = target
            db.add(row)
            db.flush()
            error = None
            if kind == "CANCEL":
                _revoke_task_locked(db, owner=owner, task_ref=target, timestamp=_utc(None))
            elif kind == "APPROVAL_DECISION" and uncertain(operation):
                failure = ApplicationError(
                    409,
                    "RECONCILIATION_REQUIRED",
                    command_ref=row.command_ref,
                    execution_uncertain=True,
                )
            else:
                _, error = _owner_approval_locked(
                    db,
                    owner=owner,
                    approval_ref=target,
                    resolution=payload.resolution if kind == "APPROVAL_DECISION" else None,
                    revoke=kind == "APPROVAL_REVOKE",
                )
            if error:
                failure = ApplicationError(
                    409, "APPROVAL_STATE_CONFLICT", command_ref=row.command_ref
                )
            row.updated_at = max(_utc(None), row.created_at)
            row.state = "FAILED" if failure else "SUCCEEDED"
            if failure:
                row.failure_code, row.failure_http_status = failure.code, failure.status
            replay = False
        # Project only after the entire atomic command/domain unit is query-visible.
        db.flush()
        result = mutation_view(db, owner, kind, target, runtime)
    if failure:
        raise failure
    return result, replay


def workflow_context(db, owner, task_ref, runtime):
    task, _ = _owned_application(db, owner, task_ref)
    rows = list(
        db.scalars(
            select(WorkflowCheckpoint)
            .where(
                WorkflowCheckpoint.task_ref == task_ref,
                WorkflowCheckpoint.owner_id == owner.owner_id,
            )
            .with_for_update()
        )
    )
    if len(rows) > 1:
        raise ApplicationError(503, "BACKEND_UNAVAILABLE")
    row = rows[0] if rows else None
    planning = _planning(db, task, runtime)
    blocked = planning is not None and planning.state == "UNCERTAIN"
    blocked |= (
        db.scalar(
            select(GatewayOperation.operation_ref)
            .where(
                GatewayOperation.task_ref == task_ref,
                GatewayOperation.owner_id == owner.owner_id,
                GatewayOperation.operation_status.in_(("DISPATCHING", "UNKNOWN")),
            )
            .limit(1)
        )
        is not None
    )
    available = False
    if row:
        _, operation, approved, request = approval_context(db, owner, row.approval_ref)
        if (
            row.operation_ref,
            row.request_id,
            row.idempotency_key,
            row.canonical_request_digest,
        ) != (
            operation.operation_ref,
            request.request_id,
            request.idempotency_key,
            operation.canonical_request_digest,
        ):
            raise ApplicationError(503, "BACKEND_UNAVAILABLE")
        reason, _ = _current(db, task, operation, approved, request, EMPTY_CATALOG, _utc(None))
        command = db.scalar(
            select(ApplicationCommand).where(
                ApplicationCommand.continuation_binding_ref == row.binding_ref
            )
        )
        if (
            command
            and command.state == "CLAIMED"
            and (command.runtime_ref != runtime.identity or not runtime.active(command.command_ref))
        ):
            command.state, command.failure_code, command.failure_http_status = (
                "UNCERTAIN",
                "COMMAND_UNCERTAIN",
                409,
            )
            command.updated_at = max(_utc(None), command.created_at)
        blocked |= (
            bool(command and command.state == "UNCERTAIN")
            or uncertain(operation)
            or row.phase == "RESUMING"
            and not (command and runtime.active(command.command_ref))
        )
        available = (
            not reason
            and not blocked
            and command is None
            and row.checkpoint_id is not None
            and row.phase in ("PAUSED", "ADMITTED")
        )
        if row.phase == "ADMITTED":
            available &= (
                row.admitted_authorization_version == task.authorization_version
                and row.expires_at is not None
                and _utc(None) < row.expires_at
            )
    view = WorkflowView(
        task_ref=task_ref,
        binding_ref=row.binding_ref if row else None,
        operation_ref=row.operation_ref if row else None,
        approval_ref=row.approval_ref if row else None,
        phase=row.phase if row else None,
        authorization_version=task.authorization_version,
        expires_at=row.expires_at if row else None,
        continuation_available=bool(available),
        reconciliation_required=bool(blocked),
        provenance=provenance(db, task, runtime),
    )
    return view, row


def workflow(db, owner, task_ref, runtime):
    with _transaction(db):
        return workflow_context(db, owner, task_ref, runtime)[0]


def continuation_claim(db, owner, task_ref, identity, runtime, command_ref=None):
    with _transaction(db):
        view, binding = workflow_context(db, owner, task_ref, runtime)
        prior = _existing(db, owner, identity)
        if prior:
            if (
                prior.kind != "CONTINUE"
                or prior.task_ref != task_ref
                or not binding
                or prior.continuation_binding_ref != binding.binding_ref
            ):
                raise ApplicationError(503, "BACKEND_UNAVAILABLE")
            if prior.state != "SUCCEEDED":
                if prior.state == "CLAIMED" and runtime.active(prior.command_ref):
                    raise ApplicationError(
                        409, "COMMAND_IN_PROGRESS", command_ref=prior.command_ref
                    )
                raise stored_failure(prior)
            return view, True
        if view.reconciliation_required:
            actual = (
                db.scalar(
                    select(GatewayOperation.operation_ref)
                    .where(
                        GatewayOperation.task_ref == task_ref,
                        GatewayOperation.owner_id == owner.owner_id,
                        GatewayOperation.operation_status.in_(("UNKNOWN", "DISPATCHING")),
                    )
                    .limit(1)
                )
                is not None
            )
            raise ApplicationError(409, "RECONCILIATION_REQUIRED", execution_uncertain=actual)
        if not _active(_owned_application(db, owner, task_ref)[0], _utc(None)):
            raise ApplicationError(409, "TASK_NOT_ACTIVE")
        if not view.continuation_available:
            denied = binding and (
                binding.phase == "DENIED"
                or approval_context(db, owner, binding.approval_ref)[2].status
                in ("REJECTED", "EXPIRED", "REVOKED")
            )
            raise ApplicationError(409, "WORKFLOW_DENIED" if denied else "WORKFLOW_NOT_READY")
        if db.scalar(
            select(ApplicationCommand).where(
                ApplicationCommand.continuation_binding_ref == binding.binding_ref
            )
        ):
            raise ApplicationError(409, "WORKFLOW_NOT_READY")
        if command_ref is None:
            return None, False
        row = _command(
            owner,
            identity,
            "CONTINUE",
            _utc(None),
            task_ref=task_ref,
            runtime_ref=runtime.identity,
            command_ref=command_ref,
        )
        row.continuation_binding_ref = binding.binding_ref
        db.add(row)
        db.flush()
        return binding.binding_ref, False


def continuation_finish(db, owner, task_ref, command_ref, runtime, observation=None, failure=None):
    with _transaction(db):
        view, binding = workflow_context(db, owner, task_ref, runtime)
        row = db.get(ApplicationCommand, command_ref, populate_existing=True)
        if (
            row is None
            or row.owner_id != owner.owner_id
            or row.task_ref != task_ref
            or row.state != "CLAIMED"
            or binding is None
            or binding.binding_ref != row.continuation_binding_ref
        ):
            raise ApplicationError(409, "COMMAND_UNCERTAIN", uncertain=True)
        if not failure:
            current = _snapshot(binding, _owned_application(db, owner, task_ref)[0])
            if (
                observation is None
                or observation.model_dump() != current.model_dump()
                or observation.phase != "RESUMED"
                or (
                    observation.owner_ref,
                    observation.task_ref,
                    observation.binding_ref,
                    observation.operation_ref,
                    observation.approval_ref,
                    observation.checkpoint_id,
                )
                != (
                    owner.owner_id,
                    task_ref,
                    binding.binding_ref,
                    binding.operation_ref,
                    binding.approval_ref,
                    binding.checkpoint_id,
                )
                or binding.phase != "RESUMED"
            ):
                raise ValueError("Uncorrelated continuation")
        row.state = (
            "UNCERTAIN" if failure and failure.uncertain else "FAILED" if failure else "SUCCEEDED"
        )
        if failure:
            row.failure_code, row.failure_http_status = failure.code, failure.status
        row.updated_at = max(_utc(None), row.created_at)
        return view.model_copy(
            update={"reconciliation_required": bool(failure and failure.uncertain)}
        )


def execution_status(state):
    return (
        "UNKNOWN"
        if state in ("UNKNOWN", "DISPATCHING")
        else state
        if state in ("SUCCEEDED", "FAILED")
        else "NOT_EXECUTED"
    )


def operation_view(db, owner, task, operation, runtime):
    if (operation.owner_id, operation.task_ref) != (owner.owner_id, task.task_ref):
        raise ApplicationError(404, "NOT_FOUND")
    _history(db, operation)
    approved = db.scalar(
        select(PendingApproval).where(PendingApproval.operation_ref == operation.operation_ref)
    )
    if approved:
        _, _, approved, _ = approval_context(db, owner, approved.approval_ref)
    _history(db, operation)
    attempt = db.scalar(
        select(ExecutionAttempt).where(ExecutionAttempt.operation_ref == operation.operation_ref)
    )
    return OperationView(
        operation_ref=operation.operation_ref,
        task_ref=task.task_ref,
        request_id=operation.request_id,
        action=operation.action,
        state=operation.operation_status,
        decision=operation.decision,
        execution_status=execution_status(operation.operation_status),
        reason_code=operation.reason_code,
        approval_ref=approved.approval_ref if approved else None,
        approval_state=approved.status if approved else None,
        attempt_ref=attempt.attempt_ref if attempt else None,
        audit_event_ref=operation.audit_event_ref,
        revision=operation.revision,
        created_at=operation.created_at,
        updated_at=operation.updated_at,
        reconciliation_required=uncertain(operation),
        provenance=provenance(db, task, runtime, operation),
    )


def operations(db, owner, task_ref, runtime, reference=None):
    with _transaction(db):
        task, _ = _owned_application(db, owner, task_ref)
        query = select(GatewayOperation).where(
            GatewayOperation.owner_id == owner.owner_id, GatewayOperation.task_ref == task_ref
        )
        if reference:
            row = db.scalar(query.where(GatewayOperation.operation_ref == reference))
            if row is None:
                raise ApplicationError(404, "NOT_FOUND")
            return operation_view(db, owner, task, row, runtime)
        rows = list(
            db.scalars(
                query.order_by(GatewayOperation.created_at, GatewayOperation.operation_ref).limit(
                    21
                )
            )
        )
        return OperationList(
            items=tuple(operation_view(db, owner, task, row, runtime) for row in rows)
        )


def cursor_read(runtime, owner, endpoint, limit, cursor):
    if not cursor:
        return {
            "owner": digest(owner.owner_id),
            "endpoint": endpoint,
            "limit": limit,
            "snapshot": _utc(None).isoformat(),
            "expires": (_utc(None) + timedelta(seconds=900)).timestamp(),
            "last": None,
            "high": None,
        }
    try:
        encoded, tag = cursor.split(".")
        if len(cursor) > 2048 or not hmac.compare_digest(
            hmac.digest(runtime.cursor_key, encoded.encode(), "sha256").hex(), tag
        ):
            raise ValueError
        data = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if (
            set(data) != {"owner", "endpoint", "limit", "snapshot", "expires", "last", "high"}
            or data["owner"] != digest(owner.owner_id)
            or data["endpoint"] != endpoint
            or data["limit"] != limit
            or _utc(None).timestamp() >= data["expires"]
        ):
            raise ValueError
        return data
    except Exception:
        raise ApplicationError(400, "INVALID_CURSOR") from None


def cursor_write(runtime, data):
    encoded = (
        base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )
    return encoded + "." + hmac.digest(runtime.cursor_key, encoded.encode(), "sha256").hex()


def documents(db, owner, runtime, limit, cursor):
    data = cursor_read(runtime, owner, "/api/app/v1/documents", limit, cursor)
    snapshot = datetime.fromisoformat(data["snapshot"])
    with _transaction(db):
        query = select(DocumentResource).where(
            DocumentResource.owner_ref == owner.owner_id,
            DocumentResource.active.is_(True),
            DocumentResource.created_at <= snapshot,
        )
        if data["high"] is None:
            data["high"] = db.scalar(
                select(func.max(DocumentResource.resource_ref)).where(
                    DocumentResource.owner_ref == owner.owner_id,
                    DocumentResource.active.is_(True),
                    DocumentResource.created_at <= snapshot,
                )
            )
        if data["high"]:
            query = query.where(DocumentResource.resource_ref <= data["high"])
        if data["last"]:
            query = query.where(DocumentResource.resource_ref > data["last"])
        rows = list(db.scalars(query.order_by(DocumentResource.resource_ref).limit(limit + 1)))
        items = []
        for row in rows[:limit]:
            fixture = FIXTURES.get(row.storage_reference.removeprefix("ghost_demo_v1_"))
            if (
                not fixture
                or row.owner_ref != owner.owner_id
                or row.storage_reference not in STORAGE_REFERENCES
                or row.resource_type != "SYNTHETIC_TEXT"
                or (row.display_name, row.classification) != (fixture[1], fixture[2])
                or not re.fullmatch(r"resource_[0-9a-f]{32}", row.resource_ref)
                or not re.fullmatch(r"version_[0-9a-f]{32}", row.version_ref)
                or not re.fullmatch(r"[0-9a-f]{64}", row.content_digest)
            ):
                raise ApplicationError(503, "BACKEND_UNAVAILABLE")
            items.append(
                DocumentMetadata(
                    resource_id=row.resource_ref,
                    version_ref=row.version_ref,
                    display_name=row.display_name,
                    classification=row.classification,
                )
            )
        data["last"] = rows[limit - 1].resource_ref if len(rows) > limit else None
        return AppPage[DocumentMetadata](
            items=tuple(items),
            next_cursor=cursor_write(runtime, data) if data["last"] else None,
            snapshot_at=snapshot,
        )


def timeline(db, owner, task_ref, runtime, limit, cursor):
    endpoint = f"/api/app/v1/tasks/{task_ref}/timeline"
    data = cursor_read(runtime, owner, endpoint, limit, cursor)
    with _transaction(db):
        _owned_application(db, owner, task_ref)
        query = select(AuditEvent).where(
            AuditEvent.user_id == owner.owner_id,
            AuditEvent.detail["task_ref"].as_string() == task_ref,
            AuditEvent.event_type.in_(
                (
                    "gateway.authorization",
                    "gateway.approval.transition",
                    "gateway.approval.viewed",
                    "gateway.workflow.transition",
                )
            ),
        )
        if data["high"] is None:
            data["high"] = (
                db.scalar(
                    select(func.max(AuditEvent.id)).where(AuditEvent.user_id == owner.owner_id)
                )
                or 0
            )
        rows = list(
            db.scalars(
                query.where(AuditEvent.id <= data["high"], AuditEvent.id > (data["last"] or 0))
                .order_by(AuditEvent.id)
                .limit(limit + 1)
            )
        )
        items = []
        for row in rows[:limit]:
            detail = row.detail
            if row.user_id != owner.owner_id:
                continue
            operation = (
                db.get(GatewayOperation, detail.get("operation_ref"))
                if detail.get("operation_ref")
                else None
            )
            if operation is None or (operation.owner_id, operation.task_ref) != (
                owner.owner_id,
                task_ref,
            ):
                continue
            kind = {
                "gateway.authorization": "AUTHORIZATION",
                "gateway.approval.transition": "APPROVAL_TRANSITION",
                "gateway.approval.viewed": "APPROVAL_VIEWED",
                "gateway.workflow.transition": "WORKFLOW_TRANSITION",
            }[row.event_type]
            approved = None
            attempt = None
            state = (
                detail.get("operation_state")
                if kind == "AUTHORIZATION"
                else detail.get("phase")
                if kind == "WORKFLOW_TRANSITION"
                else detail.get("status")
            )
            if kind.startswith("APPROVAL") or kind == "WORKFLOW_TRANSITION":
                approved = (
                    db.get(PendingApproval, detail.get("approval_ref"))
                    if detail.get("approval_ref")
                    else None
                )
                if approved is None or (
                    approved.owner_id,
                    approved.task_ref,
                    approved.operation_ref,
                ) != (owner.owner_id, task_ref, operation.operation_ref):
                    continue
                allowed = (
                    ("PREPARING", "PAUSED", "ADMITTED", "RESUMING", "RESUMED", "DENIED")
                    if kind == "WORKFLOW_TRANSITION"
                    else ("PENDING", "APPROVED", "REJECTED", "EXPIRED", "REVOKED")
                )
                if state not in allowed:
                    continue
                if kind == "WORKFLOW_TRANSITION":
                    binding = db.get(WorkflowCheckpoint, detail.get("binding_ref"))
                    if binding is None or (
                        binding.owner_id,
                        binding.task_ref,
                        binding.operation_ref,
                        binding.approval_ref,
                    ) != (owner.owner_id, task_ref, operation.operation_ref, approved.approval_ref):
                        continue
            elif detail.get("attempt_ref"):
                attempt = db.get(ExecutionAttempt, detail["attempt_ref"])
                if attempt is None or attempt.operation_ref != operation.operation_ref:
                    continue
                kind = (
                    "EXECUTION_ADMISSION"
                    if state == "DISPATCHING"
                    else "EXECUTION_OUTCOME"
                    if state in ("SUCCEEDED", "FAILED", "UNKNOWN")
                    else "AUTHORIZATION"
                )
            if kind == "AUTHORIZATION" or kind.startswith("EXECUTION"):
                if (
                    detail.get("request_id") != operation.request_id
                    or detail.get("action") != operation.action
                ):
                    continue
            try:
                if row.event_type == "gateway.authorization":
                    if state not in (
                        "ADMITTED",
                        "PENDING_APPROVAL",
                        "READY",
                        "DENIED",
                        "DISPATCHING",
                        "SUCCEEDED",
                        "FAILED",
                        "UNKNOWN",
                    ) or row.outcome != detail.get("decision"):
                        continue
                    _history(db, operation)
                elif row.outcome != state:
                    continue
                items.append(
                    TimelineItem(
                        event_ref=f"event_{row.id}",
                        timestamp=row.created_at
                        if row.created_at.tzinfo
                        else row.created_at.replace(tzinfo=UTC),
                        kind=kind,
                        task_ref=task_ref,
                        operation_ref=operation.operation_ref,
                        attempt_ref=attempt.attempt_ref if attempt else None,
                        approval_ref=approved.approval_ref if approved else None,
                        state=state,
                        decision=detail.get("decision"),
                        execution_status=execution_status(state)
                        if row.event_type == "gateway.authorization"
                        else None,
                        reason_code=detail.get("reason_code"),
                    )
                )
            except (ValidationError, ValueError, TypeError):
                continue
        data["last"] = rows[limit - 1].id if len(rows) > limit else None
        return AppPage[TimelineItem](
            items=tuple(items),
            next_cursor=cursor_write(runtime, data) if data["last"] else None,
            snapshot_at=datetime.fromisoformat(data["snapshot"]),
        )
