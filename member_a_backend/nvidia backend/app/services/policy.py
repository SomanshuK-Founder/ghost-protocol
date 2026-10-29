from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, ConsentRecord, ToolPermission, User


def ensure_user(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None:
        user = User(id=user_id)
        db.add(user)
        db.flush()
    return user


def audit(db: Session, user_id: str | None, event_type: str, outcome: str, detail: dict | None = None) -> None:
    db.add(AuditEvent(user_id=user_id, event_type=event_type, outcome=outcome, detail=detail or {}))


def record_consent(db: Session, user_id: str, scope: str, granted: bool) -> ConsentRecord:
    ensure_user(db, user_id)
    item = ConsentRecord(user_id=user_id, scope=scope, granted=granted)
    db.add(item)
    audit(db, user_id, "consent.updated", "granted" if granted else "denied", {"scope": scope})
    db.commit()
    db.refresh(item)
    return item


def set_tool_permission(db: Session, user_id: str, tool_name: str, allowed: bool) -> None:
    ensure_user(db, user_id)
    item = db.scalar(select(ToolPermission).where(ToolPermission.user_id == user_id, ToolPermission.tool_name == tool_name))
    if item is None:
        db.add(ToolPermission(user_id=user_id, tool_name=tool_name, allowed=allowed))
    else:
        item.allowed = allowed
    audit(db, user_id, "tool_permission.updated", "allowed" if allowed else "denied", {"tool": tool_name})
    db.commit()


def authorize_tool(db: Session, user_id: str, tool_name: str) -> bool:
    consent = db.scalar(select(ConsentRecord).where(ConsentRecord.user_id == user_id, ConsentRecord.scope == "tools:execute").order_by(ConsentRecord.recorded_at.desc(), ConsentRecord.id.desc()))
    permission = db.scalar(select(ToolPermission).where(ToolPermission.user_id == user_id, ToolPermission.tool_name == tool_name))
    return bool(consent and consent.granted and permission and permission.allowed)
