from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from typing import Optional

from app.database import get_db
from app.models import EmailLog, EmailStatus, Inbox, Campaign, CampaignStatus, PlacementCheck
from app.services.placement import PLACEMENTS, run_placement_test

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


# ---------------------------------------------------------------------------
# Time-bucketed views (hour / day / month / year)
# ---------------------------------------------------------------------------

# period -> how many buckets the view shows
PERIODS = {"hour": 24, "day": 30, "month": 12, "year": 5}


def _bucket_start(moment: datetime, period: str) -> datetime:
    if period == "hour":
        return moment.replace(minute=0, second=0, microsecond=0)
    if period == "day":
        return moment.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "month":
        return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return moment.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)


def _step_back(start: datetime, period: str) -> datetime:
    if period == "hour":
        return start - timedelta(hours=1)
    if period == "day":
        return start - timedelta(days=1)
    if period == "month":
        return (start - timedelta(days=1)).replace(day=1)
    return start.replace(year=start.year - 1)


def _buckets(period: str) -> list:
    """Bucket start times (UTC), oldest first, ending with the current hour/day/month/year."""
    if period not in PERIODS:
        raise HTTPException(status_code=400, detail=f"period must be one of: {', '.join(PERIODS)}")
    starts = [_bucket_start(datetime.utcnow(), period)]
    for _ in range(PERIODS[period] - 1):
        starts.append(_step_back(starts[-1], period))
    return list(reversed(starts))


def _iso(moment: datetime) -> str:
    return moment.isoformat() + "Z"


@router.get("/timeseries")
async def get_timeseries(
    period: str = Query("day", description="hour (last 24h), day (30 days), month (12 months) or year (5 years)"),
    db: Session = Depends(get_db),
):
    """Emails sent, replies and bounces per hour/day/month/year."""
    starts = _buckets(period)
    since = starts[0]
    rows = {_iso(s): {"bucket": _iso(s), "emails_sent": 0, "replies": 0, "bounces": 0} for s in starts}

    for column, key in ((EmailLog.sent_at, "emails_sent"), (EmailLog.replied_at, "replies"), (EmailLog.bounced_at, "bounces")):
        for (moment,) in db.query(column).filter(column >= since):
            bucket = _iso(_bucket_start(moment, period))
            if bucket in rows:
                rows[bucket][key] += 1

    series = list(rows.values())
    totals = {k: sum(r[k] for r in series) for k in ("emails_sent", "replies", "bounces")}
    return {"period": period, "series": series, "totals": totals}


def _rates(counts: dict) -> dict:
    checked = sum(counts.get(p, 0) for p in PLACEMENTS)
    tabs = sum(counts.get(p, 0) for p in ("promotions", "updates", "social", "forums"))

    def pct(n):
        return round(n / checked * 100, 1) if checked else None

    return {
        "checked": checked,
        "inbox_rate": pct(counts.get("inbox", 0)),           # Primary inbox
        "tabs_rate": pct(tabs),                              # Promotions/Updates/... tabs
        "inbox_or_tabs_rate": pct(counts.get("inbox", 0) + tabs),
        "spam_rate": pct(counts.get("spam", 0)),
        "missing_rate": pct(counts.get("missing", 0) + counts.get("other", 0)),
    }


@router.get("/placement")
async def get_placement(
    period: str = Query("day", description="hour, day, month or year"),
    source: str = Query("all", description="all, warmup or test"),
    db: Session = Depends(get_db),
):
    """
    Inbox placement - how many emails between your own inboxes landed in the
    Primary inbox, a Gmail tab, Spam, or never arrived - per bucket, per
    sending inbox, and overall for the period's range.
    """
    starts = _buckets(period)
    query = db.query(PlacementCheck).filter(PlacementCheck.sent_at >= starts[0])
    if source in ("warmup", "test"):
        query = query.filter(PlacementCheck.source == source)
    checks = query.order_by(PlacementCheck.sent_at.desc()).all()

    empty = {p: 0 for p in PLACEMENTS}
    buckets = {_iso(s): {"bucket": _iso(s), "pending": 0, **empty} for s in starts}
    totals = {"pending": 0, **empty}
    per_sender: dict = {}
    inboxes = {i.id: i.email_address for i in db.query(Inbox).all()}

    for check in checks:
        placement = check.placement or "pending"
        bucket = buckets.get(_iso(_bucket_start(check.sent_at, period)))
        if bucket is not None and placement in bucket:
            bucket[placement] += 1
        totals[placement] = totals.get(placement, 0) + 1
        sender = per_sender.setdefault(check.sender_inbox_id, {"pending": 0, **empty})
        sender[placement] = sender.get(placement, 0) + 1

    series = []
    for b in buckets.values():
        rates = _rates(b)
        series.append({**b, "inbox_rate": rates["inbox_rate"], "spam_rate": rates["spam_rate"]})

    return {
        "period": period,
        "source": source,
        "totals": totals,
        **_rates(totals),
        "series": series,
        "by_sender": [
            {"inbox_id": iid, "email": inboxes.get(iid, "(removed inbox)"), **counts, **_rates(counts)}
            for iid, counts in sorted(per_sender.items(), key=lambda kv: -sum(kv[1].values()))
        ],
        "recent": [
            {
                "id": c.id,
                "source": c.source,
                "from": inboxes.get(c.sender_inbox_id),
                "to": inboxes.get(c.recipient_inbox_id),
                "subject": c.subject,
                "placement": c.placement,
                "sent_at": _iso(c.sent_at) if c.sent_at else None,
            }
            for c in checks[:20]
        ],
        "connected_inboxes": sum(1 for i in db.query(Inbox).filter(Inbox.is_active == True) if i.has_credentials),  # noqa: E712
    }


class PlacementTestRequest(BaseModel):
    campaign_id: Optional[int] = None  # send this campaign's first email; omit for a neutral test email


@router.post("/placement/test")
async def start_placement_test(payload: PlacementTestRequest, db: Session = Depends(get_db)):
    """
    Send a test email from each sending inbox to your other connected inboxes;
    where each one lands shows up in /placement about a minute later.
    """
    try:
        return await run_placement_test(db, payload.campaign_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
