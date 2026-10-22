"""
Inbox warmup: gradually ramp a connected Gmail inbox's sending volume by
exchanging real emails with your other connected inboxes (open, reply,
build sender history) instead of just displaying a static progress bar.

Runs as a periodic background loop (see start_warmup_scheduler) rather
than a one-shot job - warmup is inherently a slow drip over weeks, not a
single run. Each cycle sends at most one warmup email per eligible inbox,
so volume spreads across the day instead of bursting all at once.
"""
import asyncio
import random
from datetime import datetime
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.integrations.mail import MailProvider, provider_for, sync_tokens
from app.models import Inbox, WarmupConfig, WarmupLog, WarmupStage
from app.services.placement import record_send

logger = structlog.get_logger()

CYCLE_INTERVAL_SECONDS = 30 * 60  # checked every 30 min; daily quota gates actual sends

STAGE_LIMIT_FIELD = {
    WarmupStage.STAGE_1: "stage_1_daily_limit",
    WarmupStage.STAGE_2: "stage_2_daily_limit",
    WarmupStage.STAGE_3: "stage_3_daily_limit",
}

WARMUP_TEMPLATES = [
    ("Quick check-in", "Hey, just making sure this inbox is behaving - how's your week going?"),
    ("Following up", "Wanted to follow up on nothing in particular - just keeping this thread alive. Hope you're well."),
    ("Hello again", "Dropping a quick note to say hi. Anything new on your end?"),
    ("Status check", "Just a short note to keep things ticking over. Talk soon."),
    ("Quick note", "Nothing urgent here - just a short hello to keep this conversation warm."),
]

REPLY_TEMPLATES = [
    "Thanks for the note - all good here, just testing things out too.",
    "Got it, thanks! Everything looks fine on my side.",
    "Appreciate the check-in - nothing new to report, all's well.",
    "Sounds good, thanks for looping back.",
]


def get_or_create_config(db: Session) -> WarmupConfig:
    config = db.query(WarmupConfig).first()
    if not config:
        config = WarmupConfig()
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def _start_of_today() -> datetime:
    now = datetime.utcnow()
    return datetime(now.year, now.month, now.day)


def _sent_today_count(db: Session, inbox_id: int) -> int:
    """Any real email that left this inbox today - initiating ('sent') or replying ('replied') both count against its own daily quota."""
    return (
        db.query(WarmupLog)
        .filter(
            WarmupLog.inbox_id == inbox_id,
            WarmupLog.action.in_(("sent", "replied")),
            WarmupLog.created_at >= _start_of_today(),
        )
        .count()
    )


def _advance_stage(inbox: Inbox, config: WarmupConfig) -> None:
    if inbox.warmup_stage == WarmupStage.NOT_STARTED:
        inbox.warmup_stage = WarmupStage.STAGE_1
        inbox.warmup_started_at = datetime.utcnow()
        return

    if inbox.warmup_stage == WarmupStage.COMPLETED or not inbox.warmup_started_at:
        return

    elapsed_days = (datetime.utcnow() - inbox.warmup_started_at).days
    d1 = config.stage_1_duration_days
    d2 = d1 + config.stage_2_duration_days
    d3 = d2 + config.stage_3_duration_days

    if elapsed_days >= d3:
        new_stage = WarmupStage.COMPLETED
    elif elapsed_days >= d2:
        new_stage = WarmupStage.STAGE_3
    elif elapsed_days >= d1:
        new_stage = WarmupStage.STAGE_2
    else:
        new_stage = WarmupStage.STAGE_1

    if new_stage != inbox.warmup_stage:
        logger.info(
            "warmup.stage_advanced",
            inbox=inbox.email_address,
            from_stage=inbox.warmup_stage.value,
            to_stage=new_stage.value,
        )
        inbox.warmup_stage = new_stage


def _check_auto_pause(inbox: Inbox, config: WarmupConfig) -> bool:
    """Returns True if the inbox was just paused this call."""
    if config.pause_on_spam_report and inbox.spam_report_count > 0:
        inbox.is_warmup_paused = True
        inbox.pause_reason = "Spam report detected"
        return True

    if inbox.emails_sent_7d >= 5:
        bounce_rate = (inbox.bounce_count_7d / inbox.emails_sent_7d) * 100
        if bounce_rate > config.bounce_rate_threshold:
            inbox.is_warmup_paused = True
            inbox.pause_reason = f"Bounce rate {bounce_rate:.1f}% exceeds {config.bounce_rate_threshold}% threshold"
            return True

    return False


def _pick_partner(db: Session, inbox: Inbox, candidates: list, config: WarmupConfig) -> Optional[Inbox]:
    """
    Pick another active, connected inbox to warm up against - whichever
    has sent the least so far, to spread load evenly. Excludes anyone
    already at their own daily quota, since replying counts as a real
    send from their mailbox too and shouldn't push them past their cap.
    """
    others = [c for c in candidates if c.id != inbox.id and c.has_credentials]

    def under_own_quota(c: Inbox) -> bool:
        if c.warmup_stage not in STAGE_LIMIT_FIELD:
            return True  # not started / completed - no quota concept to violate
        return _sent_today_count(db, c.id) < getattr(config, STAGE_LIMIT_FIELD[c.warmup_stage])

    others = [c for c in others if under_own_quota(c)]
    if not others:
        return None
    return min(others, key=lambda c: c.warmup_emails_sent)


def _sync_tokens(db: Session, inbox: Inbox, mail: MailProvider) -> None:
    if sync_tokens(inbox, mail):
        db.commit()


async def _send_and_log(db: Session, sender: Inbox, recipient: Inbox) -> bool:
    """Send one warmup email sender -> recipient, then have recipient reply back. Returns True if the initial send succeeded."""
    subject, body = random.choice(WARMUP_TEMPLATES)
    try:
        mail = provider_for(sender)
        sent = await asyncio.to_thread(
            mail.send_email, to=recipient.email_address, subject=subject, body=body, from_name=sender.display_name
        )
        _sync_tokens(db, sender, mail)
    except Exception as exc:
        logger.warning("warmup.send_failed", sender=sender.email_address, error=str(exc))
        return False

    sender.warmup_emails_sent = (sender.warmup_emails_sent or 0) + 1
    sender.emails_sent_today = (sender.emails_sent_today or 0) + 1
    db.add(WarmupLog(inbox_id=sender.id, sent_to=recipient.email_address, action="sent"))
    # Both ends are our own inboxes, so where this landed can be checked (see services/placement.py)
    record_send(db, sender, recipient, sent["message_id"], "warmup", subject)
    db.commit()

    # The other half of a real warmup exchange: the recipient opens and replies.
    # Not gated by the recipient's own daily quota - a reply is a response, not
    # a scheduled send, same as how a human would actually use their inbox.
    try:
        reply_mail = provider_for(recipient)
        reply = await asyncio.to_thread(
            reply_mail.send_email,
            to=sender.email_address,
            subject=f"Re: {subject}",
            body=random.choice(REPLY_TEMPLATES),
            from_name=recipient.display_name,
            # NOT sent["thread_id"] - Gmail thread IDs are scoped to the mailbox that
            # created them, so reusing the sender's thread_id from the recipient's
            # account 404s ("Requested entity was not found"). A plain "Re:" send
            # still threads correctly in each mailbox via subject/References matching.
        )
        _sync_tokens(db, recipient, reply_mail)
        recipient.warmup_emails_sent = (recipient.warmup_emails_sent or 0) + 1
        recipient.emails_sent_today = (recipient.emails_sent_today or 0) + 1
        recipient.reply_count_7d = (recipient.reply_count_7d or 0) + 1
        db.add(WarmupLog(inbox_id=sender.id, received_from=recipient.email_address, action="received"))
        db.add(WarmupLog(inbox_id=recipient.id, sent_to=sender.email_address, action="replied"))
        record_send(db, recipient, sender, reply["message_id"], "warmup", f"Re: {subject}")
        db.commit()
    except Exception as exc:
        logger.warning("warmup.reply_failed", recipient=recipient.email_address, error=str(exc))
        # The initial send already succeeded - don't report this as a failure.

    return True


_cycle_lock = asyncio.Lock()


async def run_warmup_cycle(db: Session) -> dict:
    """
    One pass: check auto-pause and advance stage for every active inbox
    (cheap, no sends), then initiate at most ONE warmup email total for
    whichever single eligible inbox is furthest below its daily quota.
    Capped to one real send+reply pair per call - serialized by a lock so
    overlapping calls (manual /run plus the scheduler, say) can't stack.
    """
    async with _cycle_lock:
        config = get_or_create_config(db)
        active_inboxes = db.query(Inbox).filter(Inbox.is_active == True).all()  # noqa: E712

        summary = {"checked": 0, "sent": 0, "paused": [], "advanced": []}
        eligible = []

        for inbox in active_inboxes:
            summary["checked"] += 1

            if inbox.is_warmup_paused:
                continue

            if _check_auto_pause(inbox, config):
                db.commit()
                summary["paused"].append(inbox.email_address)
                continue

            previous_stage = inbox.warmup_stage
            _advance_stage(inbox, config)
            if inbox.warmup_stage != previous_stage:
                db.commit()
                summary["advanced"].append({"inbox": inbox.email_address, "stage": inbox.warmup_stage.value})

            if inbox.warmup_stage == WarmupStage.COMPLETED:
                continue
            if not inbox.has_credentials:
                continue

            daily_quota = getattr(config, STAGE_LIMIT_FIELD[inbox.warmup_stage])
            sent_today = _sent_today_count(db, inbox.id)
            if sent_today >= daily_quota:
                continue

            eligible.append((inbox, daily_quota - sent_today))

        if eligible:
            # Whoever is furthest below their quota goes first, so volume stays balanced across inboxes.
            inbox, _ = max(eligible, key=lambda pair: pair[1])
            partner = _pick_partner(db, inbox, active_inboxes, config)
            if partner and await _send_and_log(db, inbox, partner):
                summary["sent"] += 1

        return summary


def get_status(db: Session) -> list:
    """Per-inbox warmup status for the frontend: stage, today's progress, pause state."""
    config = get_or_create_config(db)
    inboxes = db.query(Inbox).filter(Inbox.is_active == True).all()  # noqa: E712

    status = []
    for inbox in inboxes:
        daily_quota = (
            getattr(config, STAGE_LIMIT_FIELD[inbox.warmup_stage])
            if inbox.warmup_stage in STAGE_LIMIT_FIELD
            else None
        )
        status.append({
            "inbox_id": inbox.id,
            "email_address": inbox.email_address,
            "warmup_stage": inbox.warmup_stage.value if inbox.warmup_stage else None,
            "warmup_emails_sent": inbox.warmup_emails_sent,
            "sent_today": _sent_today_count(db, inbox.id),
            "daily_quota": daily_quota,
            "is_warmup_paused": inbox.is_warmup_paused,
            "pause_reason": inbox.pause_reason,
            "has_partner": any(
                i.id != inbox.id and i.has_credentials for i in inboxes
            ),
        })
    return status


def get_activity(db: Session, limit: int = 50) -> list:
    logs = (
        db.query(WarmupLog)
        .order_by(WarmupLog.created_at.desc())
        .limit(limit)
        .all()
    )
    inbox_names = {i.id: i.email_address for i in db.query(Inbox).all()}
    return [
        {
            "id": log.id,
            "inbox": inbox_names.get(log.inbox_id, f"inbox {log.inbox_id}"),
            "action": log.action,
            "sent_to": log.sent_to,
            "received_from": log.received_from,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


_scheduler_task: Optional[asyncio.Task] = None


async def _scheduler_loop(interval_seconds: int):
    from app.database import SessionLocal

    from app.tenancy import run_per_owner

    while True:
        try:
            # Per account: an account's inboxes only ever warm up with each other
            results = await run_per_owner(run_warmup_cycle)
            for owner_id, result in results.items():
                if result["sent"] or result["paused"] or result["advanced"]:
                    logger.info("warmup.cycle_complete", owner_id=owner_id, **result)
        except Exception as exc:
            logger.error("warmup.cycle_failed", error=str(exc))

        await asyncio.sleep(interval_seconds)


def start_warmup_scheduler(interval_seconds: int = CYCLE_INTERVAL_SECONDS):
    global _scheduler_task
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(_scheduler_loop(interval_seconds))
        logger.info("warmup.scheduler_started", interval_seconds=interval_seconds)


def stop_warmup_scheduler():
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        logger.info("warmup.scheduler_stopped")
