from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Inbox
from app.services.warmup import get_activity, get_status, run_warmup_cycle

router = APIRouter()


@router.get("/status")
async def warmup_status(db: Session = Depends(get_db)):
    """Per-inbox warmup progress: stage, today's send count vs quota, pause state."""
    return {"inboxes": get_status(db)}


@router.get("/activity")
async def warmup_activity(limit: int = Query(50, le=200), db: Session = Depends(get_db)):
    """Recent warmup send/receive/reply events, newest first."""
    return {"activity": get_activity(db, limit=limit)}


@router.post("/run")
async def warmup_run_now(db: Session = Depends(get_db)):
    """Manually trigger one warmup cycle immediately, instead of waiting for the next scheduled pass."""
    summary = await run_warmup_cycle(db)
    return summary


@router.post("/{inbox_id}/pause")
async def warmup_pause(inbox_id: int, db: Session = Depends(get_db)):
    inbox = db.query(Inbox).filter(Inbox.id == inbox_id).first()
    if not inbox:
        raise HTTPException(status_code=404, detail="Inbox not found")
    inbox.is_warmup_paused = True
    inbox.pause_reason = "Paused by user"
    db.commit()
    return {"success": True}


@router.post("/{inbox_id}/resume")
async def warmup_resume(inbox_id: int, db: Session = Depends(get_db)):
    inbox = db.query(Inbox).filter(Inbox.id == inbox_id).first()
    if not inbox:
        raise HTTPException(status_code=404, detail="Inbox not found")
    inbox.is_warmup_paused = False
    inbox.pause_reason = None
    db.commit()
    return {"success": True}
