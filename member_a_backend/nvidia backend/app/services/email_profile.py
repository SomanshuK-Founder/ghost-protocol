"""Immutable synthetic configuration; never populated from requests or document text."""

from types import MappingProxyType

from app.gateway_contracts import EmailArguments

TEMPLATE_REF = "synthetic_mail_v1"
SENDER = "ghost-demo@example.test"
SUBJECT = "Ghost Protocol synthetic demonstration"
BODY = "SYNTHETIC TEST ONLY. This message contains no document or personal information."
RECIPIENTS = MappingProxyType(
    {"local-user": frozenset({"teammate@example.test", "reviewer@example.test"})}
)


def recipient_allowed(owner_id, recipient):
    return isinstance(recipient, str) and recipient in RECIPIENTS.get(owner_id, ())


def arguments_for(recipient):
    return EmailArguments(recipient=recipient, subject=SUBJECT, body=BODY)


def email_scope_reason(owner_id, scope, request):
    """One fixed template, no attachments or source resources; no sharing authority inferred."""
    if scope.recipient is None:
        return "ACTION_DISABLED"
    if not recipient_allowed(owner_id, scope.recipient) or (
        request.arguments.recipient != scope.recipient
    ):
        return "RECIPIENT_NOT_AUTHORIZED"
    if scope.resource_ids or request.arguments != arguments_for(scope.recipient):
        return "EMAIL_CONTENT_NOT_AUTHORIZED"
    return None


def send_guard(db, task, operation_ref=None):
    """Serialize owner send admission; an unresolved prior effect blocks replacement tasks."""
    from sqlalchemy import select

    from app.models import GatewayOperation, User

    db.scalar(select(User).where(User.id == task.owner_id).with_for_update())
    unresolved = select(GatewayOperation.operation_ref).where(
        GatewayOperation.owner_id == task.owner_id,
        GatewayOperation.action == "email.send",
        GatewayOperation.operation_status.in_(("DISPATCHING", "UNKNOWN")),
    )
    if operation_ref is not None:
        unresolved = unresolved.where(GatewayOperation.operation_ref != operation_ref)
    return "SEND_RECONCILIATION_REQUIRED" if db.scalar(unresolved.limit(1)) else None
