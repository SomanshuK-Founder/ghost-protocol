"""Owner-scoped application tasks and durable one-run planning command identities."""

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import and_, or_, select

from app.agent_schemas import ResourceVersion, TaskScope
from app.application_contracts import (
    ApplicationError,
    PlanningView,
    Provenance,
    TaskDetail,
    TaskPage,
    TaskSummary,
)
from app.models import (
    ApplicationCommand,
    ExecutionAttempt,
    GatewayOperation,
    GatewayTask,
    User,
    WorkflowCheckpoint,
)
from app.services.agent_identity import (
    _active,
    _create_task_locked,
    _owned_task,
    _transaction,
    _utc,
)
from app.services.document_catalog import _owned_resource
from app.services.email_profile import arguments_for
from app.services.operation_ledger import _isolation

PROFILES = {
    "document_simulation_v1": ("files.read", "summarize_document"),
    "email_draft_v1": ("email.draft", "prepare_email"),
    "email_send_v1": ("email.send", "prepare_email"),
}


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode()
    ).hexdigest()


def command_identity(request, payload, owner):
    keys = request.headers.getlist("idempotency-key")
    if not keys:
        raise ApplicationError(400, "IDEMPOTENCY_KEY_REQUIRED")
    try:
        key = str(UUID(keys[0], version=4))
        if len(keys) != 1 or key != keys[0] or UUID(keys[0]).version != 4:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ApplicationError(400, "IDEMPOTENCY_KEY_INVALID") from None
    scope = digest({"method": request.method, "path": request.url.path})
    return (
        scope,
        key,
        digest({"owner": owner.owner_id, "scope": scope, "body": payload.model_dump(mode="json")}),
    )


def _existing(db, owner, identity):
    scope, key, hashed = identity
    row = db.scalar(
        select(ApplicationCommand)
        .where(
            ApplicationCommand.owner_id == owner.owner_id,
            ApplicationCommand.scope_digest == scope,
            ApplicationCommand.client_key == key,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row and row.request_digest != hashed:
        raise ApplicationError(409, "IDEMPOTENCY_CONFLICT")
    return row


def _command(
    owner, identity, kind, timestamp, *, task_ref=None, runtime_ref=None, command_ref=None
):
    scope, key, hashed = identity
    return ApplicationCommand(
        command_ref=command_ref or f"cmd_{uuid4().hex}",
        owner_id=owner.owner_id,
        task_ref=task_ref,
        scope_digest=scope,
        client_key=key,
        request_digest=hashed,
        kind=kind,
        state="CLAIMED",
        runtime_ref=runtime_ref,
        created_at=timestamp,
        updated_at=timestamp,
        planning_task_ref=task_ref if kind == "PLANNING" else None,
        creation_task_ref=task_ref if kind == "TASK_CREATE" else None,
    )


def _owned_application(db, owner, task_ref):
    task = _owned_task(db, owner, task_ref)
    creation = db.scalar(
        select(ApplicationCommand).where(
            ApplicationCommand.task_ref == task.task_ref,
            ApplicationCommand.owner_id == owner.owner_id,
            ApplicationCommand.kind == "TASK_CREATE",
            ApplicationCommand.state == "SUCCEEDED",
        )
    )
    if (
        creation is None
        or not isinstance(creation.safe_result, dict)
        or set(creation.safe_result) != {"profile_id"}
    ):
        raise ApplicationError(404, "NOT_FOUND")
    profile = creation.safe_result["profile_id"]
    if profile not in PROFILES:
        raise ApplicationError(503, "BACKEND_UNAVAILABLE")
    return task, profile


def _planning(db, task, runtime):
    row = db.scalar(
        select(ApplicationCommand)
        .where(
            ApplicationCommand.task_ref == task.task_ref,
            ApplicationCommand.owner_id == task.owner_id,
            ApplicationCommand.kind == "PLANNING",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        row
        and row.state == "CLAIMED"
        and (row.runtime_ref != runtime.identity or not runtime.active(row.command_ref))
    ):
        row.state, row.failure_code, row.failure_http_status = "UNCERTAIN", "COMMAND_UNCERTAIN", 409
        row.updated_at = max(_utc(None), row.created_at)
    return row


def planning_view(row, task_ref):
    if row is None:
        return PlanningView(task_ref=task_ref)
    if row.state == "SUCCEEDED":
        try:
            view = PlanningView.model_validate_json(json.dumps(row.safe_result), strict=True)
            if (view.task_ref, view.planning_ref) != (task_ref, row.command_ref):
                raise ValueError
            return view
        except (ValueError, ValidationError):
            raise ApplicationError(503, "BACKEND_UNAVAILABLE") from None
    uncertain = row.state == "UNCERTAIN"
    return PlanningView(
        task_ref=task_ref,
        planning_ref=row.command_ref,
        state="UNCERTAIN" if uncertain else "FAILED" if row.state == "FAILED" else "RUNNING",
        outcome="FAILED" if row.state == "FAILED" else None,
        error_code="COMMAND_UNCERTAIN" if uncertain else row.failure_code,
        started_at=row.created_at,
        finished_at=row.updated_at if row.state == "FAILED" else None,
        provenance=Provenance(planning_source="UNATTESTED", evidence="UNATTESTED"),
    )


def _detail(db, task, profile, runtime):
    plan = planning_view(_planning(db, task, runtime), task.task_ref)
    operation = db.scalar(
        select(GatewayOperation)
        .where(
            GatewayOperation.task_ref == task.task_ref, GatewayOperation.owner_id == task.owner_id
        )
        .order_by(GatewayOperation.created_at.desc())
        .limit(1)
    )
    workflow = db.scalar(
        select(WorkflowCheckpoint).where(
            WorkflowCheckpoint.task_ref == task.task_ref,
            WorkflowCheckpoint.owner_id == task.owner_id,
        )
    )
    scope = TaskScope.model_validate_json(json.dumps(task.authorization_scope))
    if scope.allowed_actions != (PROFILES[profile][0],) or scope.purpose != PROFILES[profile][1]:
        raise ApplicationError(503, "BACKEND_UNAVAILABLE")
    state = "EXPIRED" if task.status == "OPEN" and _utc(None) >= task.expires_at else task.status
    uncertain = (
        plan.state == "UNCERTAIN"
        or operation is not None
        and operation.operation_status in ("DISPATCHING", "UNKNOWN")
    )
    provenance = plan.provenance
    if operation is not None:
        attempt = db.scalar(
            select(ExecutionAttempt).where(
                ExecutionAttempt.operation_ref == operation.operation_ref
            )
        )
        if attempt is not None or operation.operation_status in (
            "DISPATCHING",
            "SUCCEEDED",
            "FAILED",
            "UNKNOWN",
        ):
            # Mode alone cannot attest which trusted transport an external operator used.
            provenance = Provenance(
                planning_source=plan.provenance.planning_source,
                execution_mode=attempt.mode
                if attempt and attempt.mode in ("SIMULATED", "EMAIL_DRAFT", "MAILPIT_SEND")
                else None,
                effect="UNCONFIRMED",
                evidence="UNATTESTED",
            )
    return TaskDetail(
        task_ref=task.task_ref,
        profile_id=profile,
        authority_state=state,
        created_at=task.created_at,
        expires_at=task.expires_at,
        planning_state=plan.state,
        approval_ref=plan.approval_ref,
        workflow_phase=workflow.phase if workflow else None,
        operation_state=operation.operation_status if operation else None,
        provenance=provenance,
        purpose=scope.purpose,
        resource_ids=scope.resource_ids,
        allowed_action=scope.allowed_actions[0],
        authorization_version=task.authorization_version,
        in_flight=operation is not None
        and operation.operation_status in ("DISPATCHING", "UNKNOWN"),
        reconciliation_required=uncertain,
    )


def create_task(db, owner, payload, identity, runtime):
    with _transaction(db):
        _isolation(db)
        # Same owner lock as the existing creation service; task+command commit together.
        user = db.scalar(select(User).where(User.id == owner.owner_id).with_for_update())
        if user is None:
            db.add(User(id=owner.owner_id))
            db.flush()
        previous = _existing(db, owner, identity)
        if previous:
            task, profile = _owned_application(db, owner, previous.task_ref)
            return _detail(db, task, profile, runtime), True
        now = _utc(None)
        action, purpose = PROFILES[payload.profile_id]
        pins = ()
        if payload.resource_id is not None:
            resource = _owned_resource(db, owner, payload.resource_id)
            if not resource.active:
                raise ApplicationError(404, "NOT_FOUND")
            pins = (
                ResourceVersion(
                    resource_id=resource.resource_ref,
                    version_ref=resource.version_ref,
                    classification=resource.classification,
                ),
            )
        scope = TaskScope(
            purpose=purpose,
            allowed_actions=(action,),
            resource_ids=tuple(p.resource_id for p in pins),
            resource_versions=pins,
            recipient="teammate@example.test" if not pins else None,
            approval_enabled=True,
        )
        task = _create_task_locked(
            db, owner=owner, scope=scope, now=now, expires_at=now + timedelta(seconds=900)
        )
        db.flush()
        row = _command(owner, identity, "TASK_CREATE", now, task_ref=task.task_ref)
        row.state, row.safe_result = "SUCCEEDED", {"profile_id": payload.profile_id}
        db.add(row)
        db.flush()
        return _detail(db, task, payload.profile_id, runtime), False


def get_task(db, owner, task_ref, runtime):
    with _transaction(db):
        task, profile = _owned_application(db, owner, task_ref)
        return _detail(db, task, profile, runtime)


def get_planning(db, owner, task_ref, runtime):
    with _transaction(db):
        task, _ = _owned_application(db, owner, task_ref)
        return planning_view(_planning(db, task, runtime), task.task_ref)


def _retry(row, task_ref, runtime):
    if row.state == "SUCCEEDED":
        return planning_view(row, task_ref)
    if row.state == "FAILED":
        raise ApplicationError(
            row.failure_http_status, row.failure_code, command_ref=row.command_ref
        )
    if row.state == "UNCERTAIN":
        raise ApplicationError(
            409, "COMMAND_UNCERTAIN", command_ref=row.command_ref, uncertain=True
        )
    raise ApplicationError(409, "COMMAND_IN_PROGRESS", command_ref=row.command_ref)


def planning_replay(db, owner, task_ref, identity, runtime):
    with _transaction(db):
        task, _ = _owned_application(db, owner, task_ref)
        row = _planning(db, task, runtime)
        previous = _existing(db, owner, identity)
        if previous:
            return _retry(previous, task_ref, runtime)
        if row:
            raise ApplicationError(409, "PLANNING_ALREADY_STARTED")
        if not _active(task, _utc(None)):
            raise ApplicationError(409, "TASK_NOT_ACTIVE")
    return None


def claim_planning(db, owner, task_ref, identity, runtime, command_ref):
    with _transaction(db):
        task, profile = _owned_application(db, owner, task_ref)
        if _planning(db, task, runtime):
            raise ApplicationError(409, "PLANNING_ALREADY_STARTED")
        if not _active(task, _utc(None)):
            raise ApplicationError(409, "TASK_NOT_ACTIVE")
        row = _command(
            owner,
            identity,
            "PLANNING",
            _utc(None),
            task_ref=task_ref,
            runtime_ref=runtime.identity,
            command_ref=command_ref,
        )
        db.add(row)
        db.flush()
        scope = TaskScope.model_validate_json(json.dumps(task.authorization_scope))
        arguments = (
            {"resource_id": scope.resource_ids[0]}
            if profile == "document_simulation_v1"
            else arguments_for(scope.recipient).model_dump(mode="json")
        )
        return scope.allowed_actions[0], scope.purpose, arguments


def finish_planning(db, owner, task_ref, command_ref, observation=None, failure=None):
    with _transaction(db):
        task, _ = _owned_application(db, owner, task_ref)
        row = db.get(ApplicationCommand, command_ref, populate_existing=True)
        if (
            row is None
            or row.task_ref != task_ref
            or row.owner_id != owner.owner_id
            or row.state != "CLAIMED"
        ):
            raise ApplicationError(
                409, "COMMAND_UNCERTAIN", command_ref=command_ref, uncertain=True
            )
        now = max(_utc(None), row.created_at)
        if failure:
            row.state = "UNCERTAIN" if failure.uncertain else "FAILED"
            row.failure_code, row.failure_http_status = failure.code, failure.status
        else:
            expected = TaskScope.model_validate_json(json.dumps(task.authorization_scope))
            plan = observation.plan
            if observation.task_ref != task_ref or plan and plan.task_ref != task_ref:
                raise ValueError("Wrong planning identity")
            if observation.request_id is None and any(
                (
                    observation.decision,
                    observation.reason_code,
                    observation.approval_ref,
                    observation.binding_ref,
                )
            ):
                raise ValueError("Authorization must correlate with the durable ledger")
            if observation.decision != "APPROVAL_REQUIRED" and any(
                (observation.approval_ref, observation.binding_ref)
            ):
                raise ValueError("Only pending approvals can bind a paused workflow")
            if observation.outcome == "FAILED":
                if plan is not None or observation.request_id is not None:
                    raise ValueError("Failed planning cannot claim authorization")
            else:
                if (
                    plan is None
                    or plan.requires_external_action != bool(plan.proposed_actions)
                    or plan.clarification_required
                    and plan.proposed_actions
                ):
                    raise ValueError("Invalid plan flags")
                if observation.outcome == "PLAN_READY" and (
                    plan.intent != expected.purpose
                    or plan.proposed_actions != expected.allowed_actions
                ):
                    raise ValueError("Out of scope plan")
                if observation.outcome != "PLAN_READY" and plan.proposed_actions:
                    raise ValueError("Non-action outcome has actions")
                if observation.outcome == "CLARIFICATION_REQUIRED" and (
                    plan.intent != "clarify_request" or not plan.clarification_required
                ):
                    raise ValueError("Invalid clarification outcome")
                if (
                    observation.outcome == "UNSUPPORTED_OPERATION"
                    and plan.intent != "unsupported_operation"
                ):
                    raise ValueError("Invalid unsupported outcome")
                if observation.outcome != "PLAN_READY" and observation.request_id is not None:
                    raise ValueError("Non-action outcome cannot authorize")
            operation = None
            if observation.request_id:
                operation = db.scalar(
                    select(GatewayOperation).where(
                        GatewayOperation.task_ref == task_ref,
                        GatewayOperation.owner_id == owner.owner_id,
                        GatewayOperation.request_id == observation.request_id,
                    )
                )
                if operation is None or (operation.decision, operation.reason_code) != (
                    observation.decision,
                    observation.reason_code,
                ):
                    raise ValueError("Uncorrelated authorization")
                if operation.operation_status not in ("ADMITTED", "DENIED", "PENDING_APPROVAL"):
                    raise ValueError("Planning cannot execute")
            if observation.decision == "APPROVAL_REQUIRED":
                binding = db.get(WorkflowCheckpoint, observation.binding_ref)
                if binding is None or (
                    binding.task_ref,
                    binding.owner_id,
                    binding.operation_ref,
                    binding.approval_ref,
                    binding.phase,
                ) != (
                    task_ref,
                    owner.owner_id,
                    operation.operation_ref,
                    observation.approval_ref,
                    "PAUSED",
                ):
                    raise ValueError("A genuine paused workflow is required")
            view = PlanningView(
                task_ref=task_ref,
                planning_ref=command_ref,
                state="FAILED" if observation.outcome == "FAILED" else "FINISHED",
                outcome=observation.outcome,
                intent=plan.intent if plan else None,
                proposed_actions=plan.proposed_actions if plan else (),
                authorization_decision=observation.decision,
                reason_code=observation.reason_code,
                request_id=observation.request_id,
                operation_ref=operation.operation_ref if operation else None,
                approval_ref=observation.approval_ref,
                error_code=(
                    "PLAN_OUT_OF_SCOPE"
                    if observation.error == "PLAN_OUT_OF_SCOPE"
                    else "PLANNING_FAILED"
                )
                if observation.outcome == "FAILED"
                else "AUTHORIZATION_UNAVAILABLE"
                if observation.error
                and observation.outcome == "PLAN_READY"
                and observation.error != "GATEWAY_NOT_EXECUTED"
                and observation.request_id is None
                else None,
                started_at=row.created_at,
                finished_at=now,
                provenance=Provenance(planning_source="MOCK_MODEL"),
            )
            row.state, row.safe_result = "SUCCEEDED", view.model_dump(mode="json")
        row.updated_at = now
        db.flush()
        return planning_view(row, task_ref)


def task_page(db, owner, runtime, *, limit, cursor=None):
    now = _utc(None)
    data = None
    if cursor:
        try:
            encoded, tag = cursor.split(".")
            if len(cursor) > 2048 or not hmac.compare_digest(
                hmac.digest(runtime.cursor_key, encoded.encode(), "sha256").hex(), tag
            ):
                raise ValueError
            data = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
            if (
                set(data) != {"owner", "endpoint", "limit", "snapshot", "high", "last", "expires"}
                or data["owner"] != digest(owner.owner_id)
                or data["endpoint"] != "/api/app/v1/tasks"
                or data["limit"] != limit
                or now.timestamp() >= data["expires"]
            ):
                raise ValueError
            snapshot = datetime.fromisoformat(data["snapshot"])
            last_time, last_ref = datetime.fromisoformat(data["last"][0]), data["last"][1]
            high_time, high_ref = datetime.fromisoformat(data["high"][0]), data["high"][1]
        except Exception:
            raise ApplicationError(400, "INVALID_CURSOR") from None
    else:
        snapshot = now
    with _transaction(db):
        query = (
            select(GatewayTask)
            .join(
                ApplicationCommand,
                and_(
                    ApplicationCommand.task_ref == GatewayTask.task_ref,
                    ApplicationCommand.owner_id == GatewayTask.owner_id,
                    ApplicationCommand.kind == "TASK_CREATE",
                    ApplicationCommand.state == "SUCCEEDED",
                ),
            )
            .where(GatewayTask.owner_id == owner.owner_id, GatewayTask.created_at <= snapshot)
        )
        if data:
            query = query.where(
                or_(
                    GatewayTask.created_at < high_time,
                    and_(GatewayTask.created_at == high_time, GatewayTask.task_ref <= high_ref),
                )
            )
            query = query.where(
                or_(
                    GatewayTask.created_at < last_time,
                    and_(GatewayTask.created_at == last_time, GatewayTask.task_ref < last_ref),
                )
            )
        tasks = list(
            db.scalars(
                query.order_by(GatewayTask.created_at.desc(), GatewayTask.task_ref.desc()).limit(
                    limit + 1
                )
            )
        )
        high = (
            data["high"]
            if data
            else [tasks[0].created_at.isoformat(), tasks[0].task_ref]
            if tasks
            else None
        )
        items = []
        for task in tasks[:limit]:
            _, profile = _owned_application(db, owner, task.task_ref)
            detail = _detail(db, task, profile, runtime)
            items.append(
                TaskSummary.model_validate(
                    {key: getattr(detail, key) for key in TaskSummary.model_fields}
                )
            )
        next_cursor = None
        if len(tasks) > limit:
            last = tasks[limit - 1]
            value = dict(
                owner=digest(owner.owner_id),
                endpoint="/api/app/v1/tasks",
                limit=limit,
                snapshot=snapshot.isoformat(),
                high=high,
                last=[last.created_at.isoformat(), last.task_ref],
                expires=data["expires"] if data else (now + timedelta(seconds=900)).timestamp(),
            )
            encoded = (
                base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode())
                .rstrip(b"=")
                .decode()
            )
            next_cursor = (
                encoded + "." + hmac.digest(runtime.cursor_key, encoded.encode(), "sha256").hex()
            )
        return TaskPage(items=tuple(items), next_cursor=next_cursor, snapshot_at=snapshot)
