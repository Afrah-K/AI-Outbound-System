from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from typing import Optional

from app.database import get_db
from app.models import EmailLog, EmailStatus, Inbox, Campaign, CampaignStatus

router = APIRouter()


@router.get("/dashboard")
async def get_dashboard_metrics(db: Session = Depends(get_db)):
    """Get main dashboard metrics."""
    today = datetime.utcnow().date()
    seven_days_ago = datetime.utcnow() - timedelta(days=7)

    # Today's stats
    emails_sent_today = db.query(EmailLog).filter(
        func.date(EmailLog.sent_at) == today,
        EmailLog.status == EmailStatus.SENT
    ).count()

    replies_today = db.query(EmailLog).filter(
        func.date(EmailLog.replied_at) == today,
        EmailLog.status == EmailStatus.REPLIED
    ).count()

    # 7-day stats
    emails_sent_7d = db.query(EmailLog).filter(
        EmailLog.sent_at >= seven_days_ago,
        EmailLog.status == EmailStatus.SENT
    ).count()

    replies_7d = db.query(EmailLog).filter(
        EmailLog.replied_at >= seven_days_ago,
        EmailLog.status == EmailStatus.REPLIED
    ).count()

    # Active campaigns
    active_campaigns = db.query(Campaign).filter(
        Campaign.status == CampaignStatus.ACTIVE
    ).count()

    # Active inboxes
    active_inboxes = db.query(Inbox).filter(Inbox.is_active == True).count()

    # Average health score
    avg_health = db.query(func.avg(Inbox.health_score)).filter(
        Inbox.is_active == True
    ).scalar() or 100.0

    reply_rate_7d = (replies_7d / emails_sent_7d * 100) if emails_sent_7d > 0 else 0

    return {
        "today": {
            "emails_sent": emails_sent_today,
            "replies": replies_today,
        },
        "seven_days": {
            "emails_sent": emails_sent_7d,
            "replies": replies_7d,
            "reply_rate": round(reply_rate_7d, 2),
        },
        "active_campaigns": active_campaigns,
        "active_inboxes": active_inboxes,
        "average_health_score": round(avg_health, 1),
    }


@router.get("/inboxes")
async def get_inbox_analytics(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db)
):
    """Get per-inbox analytics."""
    start_date = datetime.utcnow() - timedelta(days=days)

    inboxes = db.query(Inbox).filter(Inbox.is_active == True).all()

    result = []
    for inbox in inboxes:
        sent = db.query(EmailLog).filter(
            EmailLog.inbox_id == inbox.id,
            EmailLog.sent_at >= start_date,
            EmailLog.status == EmailStatus.SENT
        ).count()

        replied = db.query(EmailLog).filter(
            EmailLog.inbox_id == inbox.id,
            EmailLog.replied_at >= start_date,
            EmailLog.status == EmailStatus.REPLIED
        ).count()

        bounced = db.query(EmailLog).filter(
            EmailLog.inbox_id == inbox.id,
            EmailLog.bounced_at >= start_date,
            EmailLog.status == EmailStatus.BOUNCED
        ).count()

        reply_rate = (replied / sent * 100) if sent > 0 else 0
        bounce_rate = (bounced / sent * 100) if sent > 0 else 0

        result.append({
            "id": inbox.id,
            "email": inbox.email_address,
            "health_score": inbox.health_score,
            "emails_sent": sent,
            "replies": replied,
            "bounces": bounced,
            "reply_rate": round(reply_rate, 2),
            "bounce_rate": round(bounce_rate, 2),
            "daily_limit": inbox.daily_limit,
            "emails_sent_today": inbox.emails_sent_today,
        })

    return {"inboxes": result, "period_days": days}


@router.get("/campaigns")
async def get_campaign_analytics(
    days: int = Query(30, ge=1, le=90),
    db: Session = Depends(get_db)
):
    """Get campaign performance analytics."""
    start_date = datetime.utcnow() - timedelta(days=days)

    campaigns = db.query(Campaign).filter(
        Campaign.created_at >= start_date
    ).order_by(Campaign.created_at.desc()).all()

    result = []
    for campaign in campaigns:
        reply_rate = (campaign.replies_received / campaign.emails_sent * 100) if campaign.emails_sent > 0 else 0
        bounce_rate = (campaign.bounces / campaign.emails_sent * 100) if campaign.emails_sent > 0 else 0

        result.append({
            "id": campaign.id,
            "name": campaign.name,
            "status": campaign.status.value if campaign.status else None,
            "total_leads": campaign.total_leads,
            "emails_sent": campaign.emails_sent,
            "replies": campaign.replies_received,
            "bounces": campaign.bounces,
            "reply_rate": round(reply_rate, 2),
            "bounce_rate": round(bounce_rate, 2),
            "started_at": campaign.started_at.isoformat() if campaign.started_at else None,
        })

    return {"campaigns": result, "period_days": days}


@router.get("/daily")
async def get_daily_stats(
    days: int = Query(14, ge=1, le=90),
    db: Session = Depends(get_db)
):
    """Get daily sending and reply statistics."""
    result = []

    for i in range(days):
        date = datetime.utcnow().date() - timedelta(days=i)

        sent = db.query(EmailLog).filter(
            func.date(EmailLog.sent_at) == date,
            EmailLog.status == EmailStatus.SENT
        ).count()

        replied = db.query(EmailLog).filter(
            func.date(EmailLog.replied_at) == date,
            EmailLog.status == EmailStatus.REPLIED
        ).count()

        bounced = db.query(EmailLog).filter(
            func.date(EmailLog.bounced_at) == date,
            EmailLog.status == EmailStatus.BOUNCED
        ).count()

        result.append({
            "date": date.isoformat(),
            "emails_sent": sent,
            "replies": replied,
            "bounces": bounced,
        })

    # Reverse to chronological order
    result.reverse()
    return {"daily_stats": result}


@router.get("/health-scores")
async def get_health_scores(db: Session = Depends(get_db)):
    """Get all inbox health scores."""
    inboxes = db.query(Inbox).filter(Inbox.is_active == True).all()

    return {
        "health_scores": [
            {
                "id": inbox.id,
                "email": inbox.email_address,
                "health_score": inbox.health_score,
                "bounce_count_7d": inbox.bounce_count_7d,
                "reply_count_7d": inbox.reply_count_7d,
                "emails_sent_7d": inbox.emails_sent_7d,
                "warmup_stage": inbox.warmup_stage.value if inbox.warmup_stage else None,
            }
            for inbox in inboxes
        ]
    }
