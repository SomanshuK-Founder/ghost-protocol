import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import AuditEvent
from app.security import require_bearer
from app.services.policy import audit, authorize_tool, record_consent, set_tool_permission
from app.services.tools import TOOLS
from app.schemas import AuditEventResponse, ConsentRequest, ConsentResponse, ToolExecuteRequest, ToolPermissionRequest, ToolPermissionResponse

router = APIRouter(prefix="/api", tags=["project"])
logger = logging.getLogger("nvidia_project")
settings = get_settings()


@router.post("/consents", response_model=ConsentResponse, summary="Record a consent decision")
def update_consent(payload: ConsentRequest, user_id: str = Depends(require_bearer), db: Session = Depends(get_db)):
    try:
        return record_consent(db, user_id, payload.scope, payload.granted)
    except Exception as exc:
        db.rollback()
        logger.exception("Consent update failed")
        raise HTTPException(status_code=500, detail="Unable to record consent") from exc


@router.post("/tool-permissions", response_model=ToolPermissionResponse, summary="Set an allowlisted tool permission")
def update_tool_permission(payload: ToolPermissionRequest, user_id: str = Depends(require_bearer), db: Session = Depends(get_db)):
    if payload.tool_name not in TOOLS:
        raise HTTPException(status_code=400, detail="Unknown tool")
    try:
        set_tool_permission(db, user_id, payload.tool_name, payload.allowed)
        return payload
    except Exception as exc:
        db.rollback()
        logger.exception("Permission update failed")
        raise HTTPException(status_code=500, detail="Unable to update tool permission") from exc


@router.post("/tools/execute", summary="Execute an authorized project tool")
def execute_tool(payload: ToolExecuteRequest, user_id: str = Depends(require_bearer), db: Session = Depends(get_db)) -> dict:
    if payload.tool_name not in TOOLS:
        audit(db, user_id, "tool.execution", "rejected", {"tool": payload.tool_name, "reason": "unknown_tool"})
        db.commit()
        raise HTTPException(status_code=404, detail="Unknown tool")
    if not authorize_tool(db, user_id, payload.tool_name):
        audit(db, user_id, "tool.execution", "rejected", {"tool": payload.tool_name, "reason": "not_authorized"})
        db.commit()
        raise HTTPException(status_code=403, detail="Consent or tool permission is missing")
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(TOOLS[payload.tool_name], payload.arguments)
    try:
        result = future.result(timeout=settings.tool_timeout_seconds)
        audit(db, user_id, "tool.execution", "allowed", {"tool": payload.tool_name})
        db.commit()
        return {"result": result}
    except FuturesTimeout as exc:
        future.cancel()
        audit(db, user_id, "tool.execution", "error", {"tool": payload.tool_name, "reason": "timeout"})
        db.commit()
        raise HTTPException(status_code=504, detail="Tool execution timed out") from exc
    except ValueError as exc:
        audit(db, user_id, "tool.execution", "rejected", {"tool": payload.tool_name, "reason": "invalid_arguments"})
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Tool execution failed")
        raise HTTPException(status_code=500, detail="Tool execution failed") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


@router.get("/audit-events", response_model=list[AuditEventResponse], summary="List recent security audit events")
def list_audit_events(user_id: str = Depends(require_bearer), db: Session = Depends(get_db)):
    rows = db.query(AuditEvent).filter(AuditEvent.user_id == user_id).order_by(AuditEvent.id.desc()).limit(100).all()
    return rows
