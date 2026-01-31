from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.config import settings

router = APIRouter()


@router.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """API health check."""
    # Check database connection
    try:
        db.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    return {
        "status": "healthy" if db_status == "healthy" else "unhealthy",
        "database": db_status,
    }


@router.get("/status")
async def system_status(db: Session = Depends(get_db)):
    """Get detailed system status."""
    from app.models import Inbox, Campaign, Person, Company, EmailLog, SendQueue, QueueStatus

    return {
        "app_name": settings.app_name,
        "debug_mode": settings.debug,
        "counts": {
            "inboxes": db.query(Inbox).count(),
            "active_inboxes": db.query(Inbox).filter(Inbox.is_active == True).count(),
            "campaigns": db.query(Campaign).count(),
            "people": db.query(Person).count(),
            "companies": db.query(Company).count(),
            "emails_logged": db.query(EmailLog).count(),
            "queue_pending": db.query(SendQueue).filter(SendQueue.status == QueueStatus.PENDING).count(),
        },
        "config": {
            "default_daily_limit": settings.default_daily_limit,
            "min_delay_seconds": settings.min_delay_seconds,
            "max_delay_seconds": settings.max_delay_seconds,
            "default_timezone": settings.default_timezone,
            "gmail_configured": bool(settings.google_client_id),
            "openai_configured": bool(settings.openai_api_key),
        }
    }


@router.get("/config")
async def get_config():
    """Get public system configuration."""
    return {
        "sending": {
            "default_daily_limit": settings.default_daily_limit,
            "min_delay_seconds": settings.min_delay_seconds,
            "max_delay_seconds": settings.max_delay_seconds,
            "default_send_start_time": settings.default_send_start_time,
            "default_send_end_time": settings.default_send_end_time,
            "default_timezone": settings.default_timezone,
        },
        "warmup": {
            "stage_1_limit": settings.warmup_stage_1_limit,
            "stage_1_days": settings.warmup_stage_1_days,
            "stage_2_limit": settings.warmup_stage_2_limit,
            "stage_2_days": settings.warmup_stage_2_days,
            "stage_3_limit": settings.warmup_stage_3_limit,
            "stage_3_days": settings.warmup_stage_3_days,
        },
        "integrations": {
            "gmail_configured": bool(settings.google_client_id),
            "openai_configured": bool(settings.openai_api_key),
        }
    }
