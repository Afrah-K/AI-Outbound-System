from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Inbox, WarmupStage
from app.services.warmup import get_activity, get_status, run_warmup_cycle

router = APIRouter()

WARMUP_CANCELLED = "Warmup cancelled"


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


def _get_inbox(db: Session, inbox_id: int) -> Inbox:
    inbox = db.query(Inbox).filter(Inbox.id == inbox_id).first()
    if not inbox:
        raise HTTPException(status_code=404, detail="Inbox not found")
    return inbox


@router.post("/{inbox_id}/pause")
async def warmup_pause(inbox_id: int, db: Session = Depends(get_db)):
    """Stop warmup for this inbox but keep its stage, so resuming picks up where it left off."""
    inbox = _get_inbox(db, inbox_id)
    inbox.is_warmup_paused = True
    inbox.pause_reason = "Paused by user"
    db.commit()
    return {"success": True}


@router.post("/{inbox_id}/resume")
async def warmup_resume(inbox_id: int, db: Session = Depends(get_db)):
    """Resume a paused warmup, or start a cancelled one over from stage 1."""
    inbox = _get_inbox(db, inbox_id)
    inbox.is_warmup_paused = False
    inbox.pause_reason = None
    db.commit()
    return {"success": True}


@router.post("/{inbox_id}/cancel")
async def warmup_cancel(inbox_id: int, db: Session = Depends(get_db)):
    """
    End warmup for this inbox: progress goes back to not started and it stays
    paused, so the scheduler doesn't start it again on its own. Resume starts over.
    """
    inbox = _get_inbox(db, inbox_id)
    inbox.warmup_stage = WarmupStage.NOT_STARTED
    inbox.warmup_started_at = None
    inbox.is_warmup_paused = True
    inbox.pause_reason = WARMUP_CANCELLED
    db.commit()
    return {"success": True}
