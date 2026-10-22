"""
Inbox placement tracking: did an email land in the recipient's Primary
inbox, a Gmail tab (Promotions, Updates...), or Spam?

You can't look inside a prospect's mailbox, so placement is measured on
mail sent between your own connected inboxes (the standard "seed inbox"
method): every warmup email is checked automatically, and a placement test
sends a campaign's real first email to your inboxes. A minute or so after
sending, the message is looked up in the recipient mailbox by its
Message-ID and its Gmail labels say where it landed. For an SMTP/IMAP
recipient inbox, the folder it's in does: INBOX, the Junk folder (spam), or
another folder (other) - plain IMAP has no Gmail-style tabs.

Caveat worth showing users: this reflects how Gmail treats your mail to
these particular inboxes - a strong signal for your sending reputation and
copy, not a guarantee for every prospect's mail provider.
"""
import asyncio
import random
from datetime import datetime, timedelta
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.integrations.mail import MailProvider, provider_for, sync_tokens
from app.models import Campaign, CampaignInbox, CampaignLead, Inbox, Person, PlacementCheck, SequenceStep

logger = structlog.get_logger()

CHECK_DELAY = timedelta(seconds=45)      # give Gmail time to deliver and file the message
GIVE_UP_AFTER = timedelta(minutes=30)    # not found by then -> "missing"
CHECK_INTERVAL_SECONDS = 60
MAX_CHECKS_PER_RUN = 25

TAB_LABELS = (
    ("CATEGORY_PROMOTIONS", "promotions"),
    ("CATEGORY_UPDATES", "updates"),
    ("CATEGORY_SOCIAL", "social"),
    ("CATEGORY_FORUMS", "forums"),
)
PLACEMENTS = ("inbox", "promotions", "updates", "social", "forums", "spam", "other", "missing")

TEST_FALLBACK_SUBJECT = "Quick question about your website"
TEST_FALLBACK_BODY = (
    "Hi there,\n\nI came across your studio's work and had a quick question about how you "
    "handle new client projects. Would you be open to a short call next week?\n\nThanks,\n"
)


def classify(labels: list) -> str:
    labels = set(labels or [])
    if "SPAM" in labels:
        return "spam"
    if "INBOX" in labels:
        for label, name in TAB_LABELS:
            if label in labels:
                return name
        return "inbox"
    return "other"  # archived by a filter, trashed, ...


def _sync_tokens(db: Session, inbox: Inbox, mail: MailProvider) -> None:
    sync_tokens(inbox, mail)


def record_send(
    db: Session,
    sender: Inbox,
    recipient: Inbox,
    gmail_message_id: str,
    source: str,
    subject: str = "",
    campaign_id: Optional[int] = None,
) -> None:
    """Queue a placement check for an email just sent sender -> recipient (both your inboxes)."""
    db.add(PlacementCheck(
        source=source,
        sender_inbox_id=sender.id,
        recipient_inbox_id=recipient.id,
        campaign_id=campaign_id,
        subject=(subject or "")[:500],
        sender_message_id=gmail_message_id,
        placement="pending",
    ))


async def resolve_pending(db: Session) -> dict:
    """Look up pending checks in their recipient mailboxes and record where each landed."""
    now = datetime.utcnow()
    pending = (
        db.query(PlacementCheck)
        .filter(PlacementCheck.placement == "pending", PlacementCheck.sent_at <= now - CHECK_DELAY)
        .order_by(PlacementCheck.sent_at)
        .limit(MAX_CHECKS_PER_RUN)
        .all()
    )
    summary = {"checked": 0, "resolved": 0}
    inboxes = {i.id: i for i in db.query(Inbox).all()}

    for check in pending:
        summary["checked"] += 1
        check.attempts = (check.attempts or 0) + 1
        sender, recipient = inboxes.get(check.sender_inbox_id), inboxes.get(check.recipient_inbox_id)
        try:
            if not sender or not recipient or not recipient.has_credentials:
                raise Exception("Inbox no longer connected")

            if not check.rfc822_message_id:
                sender_mail = provider_for(sender)
                check.rfc822_message_id = await asyncio.to_thread(sender_mail.get_rfc822_message_id, check.sender_message_id)
                _sync_tokens(db, sender, sender_mail)
                if not check.rfc822_message_id:
                    raise Exception("Sent message has no Message-ID header")

            recipient_mail = provider_for(recipient)
            labels = await asyncio.to_thread(recipient_mail.find_labels_by_rfc822_id, check.rfc822_message_id)
            _sync_tokens(db, recipient, recipient_mail)

            if labels is not None:
                check.placement = classify(labels)
                check.checked_at = now
                summary["resolved"] += 1
            elif now - check.sent_at > GIVE_UP_AFTER:
                check.placement = "missing"
                check.checked_at = now
                summary["resolved"] += 1
        except Exception as exc:  # noqa: BLE001 - keep checking the others
            check.error = str(exc)[:500]
            if now - check.sent_at > GIVE_UP_AFTER:
                check.placement = "missing"
                check.checked_at = now
                summary["resolved"] += 1
            logger.warning("placement.check_failed", check_id=check.id, error=str(exc))
        db.commit()

    return summary


def _connected(inboxes: list) -> list:
    return [i for i in inboxes if i.is_connected]


def _test_copy(db: Session, campaign: Optional[Campaign], sender: Inbox) -> tuple:
    """(subject, body) for a placement test: the campaign's first email, personalised for a real lead when possible."""
    if not campaign or not campaign.sequence_id:
        return TEST_FALLBACK_SUBJECT, TEST_FALLBACK_BODY + (sender.display_name or "")

    from app.services.campaign_engine import build_variables, render_template

    step = (
        db.query(SequenceStep)
        .filter(SequenceStep.sequence_id == campaign.sequence_id)
        .order_by(SequenceStep.order)
        .first()
    )
    if not step:
        return TEST_FALLBACK_SUBJECT, TEST_FALLBACK_BODY + (sender.display_name or "")

    lead = (
        db.query(Person)
        .join(CampaignLead, CampaignLead.person_id == Person.id)
        .filter(CampaignLead.campaign_id == campaign.id)
        .first()
    )
    variables = build_variables(lead, sender) if lead else {
        "first_name": "Alex", "full_name": "Alex Morgan", "company_name": "Northwind Studio",
        "company_website": "northwind.studio", "sender_name": sender.display_name or "",
        "sender_first_name": (sender.display_name or "").split(" ")[0],
    }
    subject, _ = render_template(step.subject, variables)
    body, _ = render_template(step.body, variables)
    return subject, body


async def run_placement_test(db: Session, campaign_id: Optional[int] = None) -> dict:
    """
    Send a test email from each sending inbox to each of your other connected
    inboxes, and queue a placement check for every one.
    """
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first() if campaign_id else None
    all_connected = _connected(db.query(Inbox).all())
    if campaign:
        sender_ids = {ci.inbox_id for ci in db.query(CampaignInbox).filter(CampaignInbox.campaign_id == campaign.id)}
        senders = [i for i in all_connected if i.id in sender_ids]
        if not senders:
            raise ValueError("This campaign has no connected sending inboxes yet")
    else:
        senders = all_connected

    pairs = [(s, r) for s in senders for r in all_connected if r.id != s.id]
    if not pairs:
        raise ValueError("Placement tests need at least two connected inboxes - one to send from and one to receive")

    sent, errors = 0, []
    for sender, recipient in pairs:
        subject, body = _test_copy(db, campaign, sender)
        try:
            mail = provider_for(sender)
            result = await asyncio.to_thread(
                mail.send_email, to=recipient.email_address, subject=subject, body=body, from_name=sender.display_name
            )
            _sync_tokens(db, sender, mail)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{sender.email_address} -> {recipient.email_address}: {exc}")
            continue
        sender.emails_sent_today = (sender.emails_sent_today or 0) + 1
        record_send(db, sender, recipient, result["message_id"], "test", subject, campaign.id if campaign else None)
        db.commit()
        sent += 1
        await asyncio.sleep(random.uniform(1, 3))

    return {"sent": sent, "errors": errors, "check_after_seconds": int(CHECK_DELAY.total_seconds()) + CHECK_INTERVAL_SECONDS}


_scheduler_task: Optional[asyncio.Task] = None


async def _scheduler_loop():
    from app.database import SessionLocal

    from app.tenancy import run_per_owner

    while True:
        try:
            results = await run_per_owner(resolve_pending)
            for owner_id, result in results.items():
                if result["resolved"]:
                    logger.info("placement.checks_resolved", owner_id=owner_id, **result)
        except Exception as exc:
            logger.error("placement.cycle_failed", error=str(exc))
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def start_placement_scheduler():
    global _scheduler_task
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(_scheduler_loop())
        logger.info("placement.scheduler_started", interval_seconds=CHECK_INTERVAL_SECONDS)


def stop_placement_scheduler():
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
    _scheduler_task = None
