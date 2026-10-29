"""Shared trusted dispatch; authorization-only HTTP admission remains nondispatching."""

import secrets
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import timedelta
from threading import BoundedSemaphore
from uuid import uuid4

from pydantic import SecretStr, ValidationError
from sqlalchemy import select

from app.gateway_contracts import (
    Authorization,
    DocumentFileResult,
    EmailDraftResult,
    EmailSendResult,
    SimulatedFileResult,
    ToolRequest,
    ToolResponse,
)
from app.models import (
    AuditEvent,
    DocumentResource,
    EmailArtifact,
    ExecutionAttempt,
    GatewayOperation,
)
from app.services.agent_identity import (
    AgentIdentityError,
    _task,
    _transaction,
    _utc,
    authenticated_task,
)
from app.services.document_reader import READ_ERRORS, SyntheticDocumentReader
from app.services.email_profile import TEMPLATE_REF, send_guard
from app.services.mailpit_email import EMAIL_ERRORS, SyntheticEmailExecutor
from app.services.operation_ledger import (
    OperationError,
    _approval_state,
    _audit,
    _candidates,
    _history,
    _isolation,
    _match,
    request_digests,
    validate_future_dispatch,
    validate_transition,
)
from app.services.resource_catalog import EMPTY_CATALOG
from app.services.scoped_consent import evaluate_locked_authorization
from app.services.synthetic_executor import (
    DocumentBinding,
    ExecutionContext,
    ExecutionInput,
    ExecutionOutcome,
    ExecutionReport,
    Executor,
    SyntheticExecutor,
)

_WORKERS = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ghost-simulation")
_CAPACITY = BoundedSemaphore(4)


def _attempt(db, operation):
    attempt = db.scalar(
        select(ExecutionAttempt)
        .where(ExecutionAttempt.operation_ref == operation.operation_ref)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if attempt is None or not (
        attempt.mode in ("SIMULATED", "SYNTHETIC_READ", "EMAIL_DRAFT", "MAILPIT_SEND")
        and attempt.state == operation.operation_status
        and attempt.dispatch_at == operation.execution_started_at
        and attempt.completed_at == operation.execution_finished_at
        and attempt.audit_event_id == operation.audit_event_id
        and attempt.sanitized_error_code == operation.sanitized_error_code
    ):
        raise OperationError(503, "GATEWAY_UNAVAILABLE", execution_uncertain=True)
    if attempt.mode == "SYNTHETIC_READ" and (
        attempt.result_json is not None or attempt.result_expires_at is not None
    ):
        raise OperationError(503, "GATEWAY_UNAVAILABLE", execution_uncertain=True)
    event = db.get(AuditEvent, attempt.audit_event_id)
    if event is None or event.detail.get("attempt_ref") != attempt.attempt_ref:
        raise OperationError(503, "GATEWAY_UNAVAILABLE", execution_uncertain=True)
    return attempt


def recorded_response(db, context, task, request, operation, catalog, now):
    """Historical outcome disclosure never grants permission to dispatch again."""
    attempt = _attempt(db, operation)
    if attempt.state == "DISPATCHING":
        raise OperationError(409, "OPERATION_IN_PROGRESS", execution_uncertain=True)
    result = None
    if attempt.state == "SUCCEEDED":
        checked = evaluate_locked_authorization(db, context, request, task, catalog, now, operation)
        if checked.decision != "ALLOW":
            raise OperationError(403, "RESULT_ACCESS_DENIED")
        if (
            attempt.mode == "SYNTHETIC_READ"
            or attempt.result_expires_at is None
            or now >= attempt.result_expires_at
        ):
            raise OperationError(410, "RESULT_EXPIRED")
        try:
            if attempt.mode in ("EMAIL_DRAFT", "MAILPIT_SEND"):
                result = (
                    EmailDraftResult if attempt.mode == "EMAIL_DRAFT" else EmailSendResult
                ).model_validate(attempt.result_json)
                ref = result.draft_ref if attempt.mode == "EMAIL_DRAFT" else result.receipt_ref
                artifact = db.get(EmailArtifact, ref, populate_existing=True)
                if artifact is None or (
                    artifact.operation_ref != operation.operation_ref
                    or artifact.attempt_ref != attempt.attempt_ref
                    or artifact.kind != attempt.mode
                    or artifact.template_ref != TEMPLATE_REF
                    or artifact.payload_digest != operation.canonical_request_digest
                ):
                    raise ValueError("Invalid email artifact")
            else:
                result = SimulatedFileResult.model_validate(attempt.result_json)
                pin = next(
                    p
                    for p in context.approved_scope.resource_versions
                    if p.resource_id == request.arguments.resource_id
                )
                if result.resource_id != pin.resource_id or result.version_ref != pin.version_ref:
                    raise ValueError("Result identity mismatch")
        except (ValidationError, ValueError, AttributeError, StopIteration):
            raise OperationError(503, "GATEWAY_UNAVAILABLE", execution_uncertain=True) from None
    return ToolResponse(
        request_id=request.request_id,
        decision="ALLOW",
        reason_code=operation.reason_code,
        execution_status=attempt.state,
        result=result,
        audit_event_ref=operation.audit_event_ref,
    )


def _execution_audit(db, task, request, operation, attempt, timestamp):
    _audit(
        db,
        task,
        request,
        Authorization(decision=operation.decision, reason_code=operation.reason_code),
        operation,
        timestamp,
    )
    event = db.get(AuditEvent, operation.audit_event_id)
    event.detail = {**event.detail, "attempt_ref": attempt.attempt_ref, "mode": attempt.mode}
    attempt.audit_event_id = operation.audit_event_id


def _claim(db, token, request, catalog, now, mode="SIMULATED", controlled_hint=None):
    """Transaction A: task first, then operation, authority, attempt. Commit before return."""
    with authenticated_task(db, token=token, task_ref=request.task_ref, now=now) as (context, task):
        _isolation(db)
        wire, binding = request_digests(context.owner_id, request, context.approved_scope)
        operation = _match(_candidates(db, task, request, wire), task, request, wire)
        if operation is None:
            raise OperationError(404, "NOT_FOUND")
        _history(db, operation)
        approval = _approval_state(db, task, operation, catalog, now)
        timestamp = _utc(now)
        controlled = None
        if controlled_hint is not None:
            from app.services.controlled_execution import check_workflow_execution

            controlled = check_workflow_execution(
                db, task, operation, approval, controlled_hint, timestamp
            )
        if operation.operation_status in ("SUCCEEDED", "FAILED", "UNKNOWN", "DISPATCHING"):
            if _attempt(db, operation).mode != mode:
                raise OperationError(409, "NOT_RESUMABLE")
            response = recorded_response(db, context, task, request, operation, catalog, timestamp)
            return ExecutionReport(
                operation.operation_ref,
                _attempt(db, operation).attempt_ref,
                response,
                operation.sanitized_error_code,
                mode=mode,
                untrusted_document=mode == "SYNTHETIC_READ",
                controlled_replay=controlled_hint is not None,
            )
        if operation.binding_digest != binding:
            raise OperationError(409, "NOT_RESUMABLE")
        email = mode in ("EMAIL_DRAFT", "MAILPIT_SEND")
        expected_action = {"EMAIL_DRAFT": "email.draft", "MAILPIT_SEND": "email.send"}.get(
            mode, "files.read"
        )
        if request.action != expected_action:
            raise OperationError(403, "ACTION_DISABLED")
        if request.action == "email.send":
            blocked = send_guard(db, task, operation.operation_ref)
            if blocked:
                raise OperationError(403, blocked)
            if operation.send_slot_task_ref != task.task_ref:
                raise OperationError(503, "GATEWAY_UNAVAILABLE")
        if (
            db.scalar(
                select(ExecutionAttempt.attempt_ref).where(
                    ExecutionAttempt.operation_ref == operation.operation_ref
                )
            )
            is not None
        ):
            raise OperationError(503, "GATEWAY_UNAVAILABLE", execution_uncertain=True)
        # UNKNOWN conservatively occupies its task slot until separate reconciliation exists.
        if (
            db.scalar(
                select(GatewayOperation.operation_ref).where(
                    GatewayOperation.task_ref == task.task_ref,
                    GatewayOperation.operation_status.in_(("DISPATCHING", "UNKNOWN")),
                )
            )
            is not None
        ):
            raise OperationError(429, "CAPACITY_EXCEEDED")
        from app.models import ScopedConsent

        consents = list(
            db.scalars(
                select(ScopedConsent)
                .where(
                    ScopedConsent.task_ref == task.task_ref, ScopedConsent.owner_id == task.owner_id
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        resolved = catalog.resolve(db, context.approved_scope, task.owner_id)
        timestamp = _utc(now)  # Resource-lock waits must not freeze the authorization clock.
        if controlled is not None and (controlled[2] is None or timestamp >= controlled[2]):
            raise OperationError(409, "NOT_RESUMABLE")
        checked = validate_future_dispatch(
            context,
            request,
            task,
            consents,
            operation,
            catalog=resolved,
            now=timestamp,
            approval=approval,
        )
        if checked.decision != "ALLOW":
            raise OperationError(403, checked.reason_code)
        pin = (
            None
            if email
            else next(
                p
                for p in context.approved_scope.resource_versions
                if p.resource_id == request.arguments.resource_id
            )
        )
        document = None
        if mode == "SYNTHETIC_READ":
            row = db.scalar(
                select(DocumentResource)
                .where(DocumentResource.resource_ref == request.arguments.resource_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                row is None
                or not row.active
                or row.owner_ref != task.owner_id
                or (row.version_ref != pin.version_ref or row.resource_type != "SYNTHETIC_TEXT")
            ):
                raise OperationError(403, "RESOURCE_NOT_AUTHORIZED")
            document = DocumentBinding(
                row.resource_ref,
                row.owner_ref,
                row.storage_reference,
                row.content_digest,
                row.classification,
            )
        attempt = ExecutionAttempt(
            attempt_ref=f"attempt_{uuid4().hex}",
            operation_ref=operation.operation_ref,
            dispatch_nonce=secrets.token_hex(32),
            mode=mode,
            state="DISPATCHING",
            dispatch_at=timestamp,
            workflow_binding_ref=controlled[0] if controlled else None,
            resume_hint_digest=controlled[1] if controlled else None,
        )
        operation.operation_status, operation.decision = "DISPATCHING", "ALLOW"
        operation.reason_code = "EXECUTION_UNCONFIRMED"
        operation.execution_started_at = operation.updated_at = timestamp
        operation.revision += 1
        if approval is not None:
            approval.consumed_at, approval.resume_ref = timestamp, None
        _execution_audit(db, task, request, operation, attempt, timestamp)
        db.add(attempt)
        db.flush()  # UNIQUE(operation_ref) is the database fence, never an in-memory lock.
        value = ExecutionInput(
            operation.operation_ref,
            task.task_ref,
            request.request_id,
            request.idempotency_key,
            wire,
            request.action,
            request.arguments,
            "" if email else pin.version_ref,
            ExecutionContext(attempt.attempt_ref, timestamp, mode),
            document,
            task.owner_id if email else None,
        )
        nonce = attempt.dispatch_nonce
    return value, nonce


def _finish(db, value, nonce, request, outcome, error, now):
    """Transaction B uses the persisted fence, not credentials that may since be revoked."""
    with _transaction(db):
        _isolation(db)
        task = _task(db, value.task_ref)
        if task is None:
            raise OperationError(503, "GATEWAY_UNAVAILABLE", execution_uncertain=True)
        operation = db.scalar(
            select(GatewayOperation)
            .where(
                GatewayOperation.operation_ref == value.operation_ref,
                GatewayOperation.task_ref == task.task_ref,
                GatewayOperation.owner_id == task.owner_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if operation is None:
            raise OperationError(503, "GATEWAY_UNAVAILABLE", execution_uncertain=True)
        _history(db, operation)
        attempt = _attempt(db, operation)
        if not secrets.compare_digest(attempt.dispatch_nonce, nonce):
            raise OperationError(503, "GATEWAY_UNAVAILABLE", execution_uncertain=True)
        if attempt.attempt_ref != value.context.attempt_ref or attempt.mode != value.context.mode:
            raise OperationError(503, "GATEWAY_UNAVAILABLE", execution_uncertain=True)
        validate_transition(operation.operation_status, outcome.status)
        timestamp = max(_utc(now), attempt.dispatch_at)
        operation.operation_status = attempt.state = outcome.status
        operation.reason_code = {
            "SUCCEEDED": "EXECUTION_SUCCEEDED",
            "FAILED": "TOOL_FAILED_NO_EFFECT",
            "UNKNOWN": "EXECUTION_UNCONFIRMED",
        }[outcome.status]
        operation.sanitized_error_code = attempt.sanitized_error_code = error
        operation.updated_at = timestamp
        operation.revision += 1
        if outcome.status != "UNKNOWN":
            operation.execution_finished_at = attempt.completed_at = timestamp
        if outcome.status == "SUCCEEDED" and attempt.mode != "SYNTHETIC_READ":
            attempt.result_json = outcome.result.model_dump(mode="json")
            attempt.result_expires_at = timestamp + timedelta(minutes=15)
            if attempt.mode in ("EMAIL_DRAFT", "MAILPIT_SEND"):
                ref = (
                    outcome.result.draft_ref
                    if attempt.mode == "EMAIL_DRAFT"
                    else outcome.result.receipt_ref
                )
                db.add(
                    EmailArtifact(
                        artifact_ref=ref,
                        operation_ref=operation.operation_ref,
                        attempt_ref=attempt.attempt_ref,
                        kind=attempt.mode,
                        template_ref=TEMPLATE_REF,
                        payload_digest=operation.canonical_request_digest,
                        created_at=timestamp,
                    )
                )
        _execution_audit(db, task, request, operation, attempt, timestamp)
        response = ToolResponse(
            request_id=request.request_id,
            decision="ALLOW",
            reason_code=operation.reason_code,
            execution_status=outcome.status,
            result=outcome.result,
            audit_event_ref=operation.audit_event_ref,
        )
        report = ExecutionReport(
            value.operation_ref,
            attempt.attempt_ref,
            response,
            error,
            mode=attempt.mode,
            untrusted_document=attempt.mode == "SYNTHETIC_READ",
        )
    return report


def _dispatch(
    db,
    *,
    token,
    request: ToolRequest,
    catalog=EMPTY_CATALOG,
    executor: Executor | None = None,
    now=None,
    timeout_seconds=1.0,
    mode="SIMULATED",
    controlled_hint=None,
):
    """Trusted dispatcher; controlled HTTP callers additionally require the workflow fence."""
    if not isinstance(token, SecretStr):
        raise OperationError(401, "AUTH_INVALID")
    try:
        request = ToolRequest.model_validate_json(request.model_dump_json(warnings=False))
    except (ValidationError, ValueError, AttributeError, TypeError):
        raise OperationError(422, "INVALID_REQUEST") from None
    if not 0 < timeout_seconds <= 5:
        raise ValueError("Execution timeout must be between zero and five seconds")
    if not _CAPACITY.acquire(blocking=False):
        raise OperationError(429, "CAPACITY_EXCEEDED")
    submitted = False
    try:
        claimed = _claim(db, token, request, catalog, now, mode, controlled_hint)
        if isinstance(claimed, ExecutionReport):
            return claimed
        value, nonce = claimed
        try:
            future = _WORKERS.submit((executor or SyntheticExecutor()).execute, value)
            submitted = True
            future.add_done_callback(lambda _: _CAPACITY.release())
            outcome = future.result(timeout=timeout_seconds)
            if not isinstance(outcome, ExecutionOutcome) or outcome.status not in (
                "SUCCEEDED",
                "FAILED",
                "UNKNOWN",
            ):
                raise ValueError("Invalid executor outcome")
            if mode == "SIMULATED":
                expected = SimulatedFileResult(
                    resource_id=value.arguments.resource_id, version_ref=value.version_ref
                )
                if outcome.result != (expected if outcome.status == "SUCCEEDED" else None):
                    raise ValueError("Invalid synthetic outcome")
                error = (
                    None
                    if outcome.status == "SUCCEEDED"
                    else (
                        "SIMULATED_FAILURE" if outcome.status == "FAILED" else "SIMULATED_UNKNOWN"
                    )
                )
            elif mode == "SYNTHETIC_READ":
                if outcome.status == "SUCCEEDED":
                    if not isinstance(outcome.result, DocumentFileResult) or (
                        outcome.result.resource_id != value.arguments.resource_id
                        or outcome.result.version_ref != value.version_ref
                    ):
                        raise ValueError("Invalid document identity")
                    error = None
                else:
                    if (
                        outcome.result is not None
                        or outcome.sanitized_error_code not in READ_ERRORS
                    ):
                        raise ValueError("Invalid document failure")
                    error = outcome.sanitized_error_code
            else:
                expected_type = EmailDraftResult if mode == "EMAIL_DRAFT" else EmailSendResult
                if outcome.status == "SUCCEEDED":
                    if not isinstance(outcome.result, expected_type) or (
                        mode == "EMAIL_DRAFT"
                        and outcome.result.payload_digest != value.canonical_request_digest
                    ):
                        raise ValueError("Invalid email outcome")
                    error = None
                else:
                    if (
                        outcome.result is not None
                        or outcome.sanitized_error_code not in EMAIL_ERRORS
                    ):
                        raise ValueError("Invalid email failure")
                    error = outcome.sanitized_error_code
        except TimeoutError:
            outcome, error = ExecutionOutcome("UNKNOWN"), "EXECUTOR_TIMEOUT"
        except Exception:
            # Arbitrary exception text never enters the ledger, audit, or response.
            outcome, error = ExecutionOutcome("UNKNOWN"), "EXECUTOR_UNCONFIRMED"
        return _finish(db, value, nonce, request, outcome, error, now)
    except AgentIdentityError as exc:
        if exc.status_code == 503:
            raise OperationError(503, "GATEWAY_UNAVAILABLE", execution_uncertain=True) from None
        raise
    finally:
        if not submitted:
            _CAPACITY.release()


def dispatch_simulated(
    db, *, token, request, catalog=EMPTY_CATALOG, executor=None, now=None, timeout_seconds=1.0
):
    return _dispatch(
        db,
        token=token,
        request=request,
        catalog=catalog,
        executor=executor,
        now=now,
        timeout_seconds=timeout_seconds,
    )


def dispatch_email(db, *, token, request, transport=None, now=None, timeout_seconds=1.0):
    """Internal composition only: EMAIL_DRAFT or MAILPIT_SEND, never a real-delivery claim."""
    if not isinstance(request, ToolRequest):
        raise OperationError(422, "INVALID_REQUEST")
    if request.action not in ("email.draft", "email.send"):
        raise OperationError(403, "ACTION_DISABLED")
    return _dispatch(
        db,
        token=token,
        request=request,
        executor=SyntheticEmailExecutor(transport),
        now=now,
        timeout_seconds=timeout_seconds,
        mode="EMAIL_DRAFT" if request.action == "email.draft" else "MAILPIT_SEND",
    )


def dispatch_document_read(
    db, *, token, request, now=None, storage=None, max_bytes=32768, timeout_seconds=1.0
):
    """Trusted backend composition only; document text is ephemeral and explicitly untrusted."""
    reader = SyntheticDocumentReader(storage, max_bytes=max_bytes)
    report = _dispatch(
        db,
        token=token,
        request=request,
        executor=reader,
        now=now,
        timeout_seconds=timeout_seconds,
        mode="SYNTHETIC_READ",
    )
    if report.response.execution_status == "SUCCEEDED":
        # Outcome recording survives later revocation; content disclosure requires fresh authority.
        with authenticated_task(db, token=token, task_ref=request.task_ref, now=now) as (
            context,
            task,
        ):
            _isolation(db)
            operation = db.get(GatewayOperation, report.operation_ref, populate_existing=True)
            if operation is None:
                raise OperationError(503, "GATEWAY_UNAVAILABLE", execution_uncertain=True)
            _history(db, operation)
            allowed = evaluate_locked_authorization(
                db, context, request, task, EMPTY_CATALOG, now, operation
            )
            if (
                allowed.decision != "ALLOW"
                or operation.authorization_version != task.authorization_version
            ):
                raise OperationError(403, "RESULT_ACCESS_DENIED")
    return report
