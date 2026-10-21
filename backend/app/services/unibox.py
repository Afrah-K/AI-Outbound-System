"""
Shared Unibox logic, used by the Unibox router and the reply agent:
collecting lead replies across every connected inbox, and sending a reply
that threads correctly in Gmail and in the recipient's own mail client.
"""
import asyncio
from datetime import datetime
from email.utils import parseaddr
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.integrations.gmail import GmailService
from app.models import (
    AgentDraft,
    Campaign,
    CampaignLead,
    EmailLog,
    EmailStatus,
    EmailType,
    Inbox,
    Person,
)
from app.services.campaign_engine import record_thread_event


def sync_tokens(inbox: Inbox, gmail: GmailService, db: Session):
    """Persist a refreshed access token if GmailService had to renew it."""
    updated = gmail.updated_tokens
    if updated["access_token"] != inbox.access_token:
        inbox.access_token = updated["access_token"]
        inbox.token_expiry = updated["token_expiry"]
        db.commit()


def connected_inboxes(db: Session) -> list:
    return db.query(Inbox).filter(Inbox.is_active == True).all()  # noqa: E712


def gmail_for(inbox: Inbox) -> GmailService:
    return GmailService(inbox.access_token, inbox.refresh_token, inbox.token_expiry)


def sender_address(msg: dict) -> str:
    return parseaddr(msg.get("from", ""))[1].lower()


def person_payload(person: Optional[Person]) -> Optional[dict]:
    if not person:
        return None
    name = person.full_name or " ".join(p for p in (person.first_name, person.last_name) if p) or None
    return {
        "id": person.id,
        "email": person.email,
        "name": name,
        "first_name": person.first_name,
        "role": person.role,
        "company_name": person.company.name if person.company else None,
        "status": person.status.value if person.status else None,
    }


def draft_payload(draft: Optional[AgentDraft]) -> Optional[dict]:
    if not draft:
        return None
    return {
        "id": draft.id,
        "category": draft.category,
        "summary": draft.summary,
        "suggested_status": draft.suggested_status,
        "draft_subject": draft.draft_subject,
        "draft_body": draft.draft_body,
        "status": draft.status,
        "error": draft.error,
        "lead_message_id": draft.lead_message_id,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
    }


def latest_draft(db: Session, inbox_id: int, thread_id: str) -> Optional[AgentDraft]:
    return (
        db.query(AgentDraft)
        .filter(AgentDraft.inbox_id == inbox_id, AgentDraft.thread_id == thread_id)
        .order_by(AgentDraft.created_at.desc())
        .first()
    )


def campaign_for_thread(db: Session, person: Person, inbox_id: int, thread_id: str) -> Optional[Campaign]:
    """The campaign whose email started this thread, else the lead's most recent campaign."""
    # Gmail thread ids are only unique within one mailbox, hence the inbox filter.
    log = (
        db.query(EmailLog)
        .filter(
            EmailLog.inbox_id == inbox_id,
            EmailLog.gmail_thread_id == thread_id,
            EmailLog.campaign_id.isnot(None),
        )
        .order_by(EmailLog.sent_at.desc())
        .first()
    )
    if log:
        return db.get(Campaign, log.campaign_id)
    lead = (
        db.query(CampaignLead)
        .filter(CampaignLead.person_id == person.id)
        .order_by(CampaignLead.created_at.desc())
        .first()
    )
    return lead.campaign if lead else None


def record_campaign_reply(db: Session, inbox_id: int, thread_id: str, msg: dict) -> bool:
    """If this thread came from a campaign and its reply isn't recorded yet, record it (stops follow-ups)."""
    already = (
        db.query(EmailLog)
        .filter(
            EmailLog.inbox_id == inbox_id,
            EmailLog.gmail_thread_id == thread_id,
            EmailLog.status.in_((EmailStatus.REPLIED, EmailStatus.BOUNCED)),
        )
        .first()
    )
    if already:
        return False
    log = (
        db.query(EmailLog)
        .filter(
            EmailLog.inbox_id == inbox_id,
            EmailLog.gmail_thread_id == thread_id,
            EmailLog.email_type == EmailType.CAMPAIGN,
            EmailLog.status == EmailStatus.SENT,
        )
        .order_by(EmailLog.sent_at.desc())
        .first()
    )
    if not log:
        return False
    record_thread_event(db, log, "replied", msg)
    db.flush()  # so the "already recorded" check sees it within this same request
    return True


async def collect_lead_replies(db: Session, days: int = 30, per_inbox: int = 50) -> dict:
    """
    Conversations where a known prospect wrote back, newest first - one entry
    per thread (its newest lead message), across every connected inbox.
    Also records campaign replies the background checker hasn't caught yet.
    """
    inboxes = connected_inboxes(db)
    own_addresses = {i.email_address.lower() for i in inboxes}
    query = f"in:inbox newer_than:{days}d"

    def fetch(inbox: Inbox):
        gmail = gmail_for(inbox)
        return gmail, gmail.list_message_metadata(query=query, max_results=per_inbox)

    connected = [i for i in inboxes if i.access_token and i.refresh_token]
    inbox_errors = [
        {"inbox_id": i.id, "email": i.email_address, "error": "Not connected"}
        for i in inboxes if i not in connected
    ]
    results = await asyncio.gather(*(asyncio.to_thread(fetch, i) for i in connected), return_exceptions=True)

    candidates = []  # (inbox, message, sender)
    for inbox, result in zip(connected, results):
        if isinstance(result, Exception):
            inbox_errors.append({"inbox_id": inbox.id, "email": inbox.email_address, "error": str(result)})
            continue
        gmail, messages = result
        sync_tokens(inbox, gmail, db)
        for msg in messages:
            sender = sender_address(msg)
            if sender and sender not in own_addresses:
                candidates.append((inbox, msg, sender))

    senders = {sender for _, _, sender in candidates}
    people = {
        p.email.lower(): p
        for p in db.query(Person).filter(func.lower(Person.email).in_(senders)).all()
    } if senders else {}

    # Keep the newest message per thread, from known prospects only.
    threads = {}
    for inbox, msg, sender in candidates:
        person = people.get(sender)
        if not person:
            continue
        key = (inbox.id, msg["thread_id"])
        if key not in threads or int(msg.get("internal_date") or 0) > int(threads[key][1].get("internal_date") or 0):
            threads[key] = (inbox, msg, person)

    newly_recorded = 0
    replies = []
    for inbox, msg, person in threads.values():
        if record_campaign_reply(db, inbox.id, msg["thread_id"], msg):
            newly_recorded += 1
        campaign = campaign_for_thread(db, person, inbox.id, msg["thread_id"])
        draft = latest_draft(db, inbox.id, msg["thread_id"])
        replies.append({
            "inbox_id": inbox.id,
            "inbox_email": inbox.email_address,
            "inbox_display_name": inbox.display_name,
            "thread_id": msg["thread_id"],
            "message_id": msg["id"],
            "subject": msg.get("subject", ""),
            "snippet": msg.get("snippet", ""),
            "from": msg.get("from", ""),
            "internal_date": msg.get("internal_date"),
            "unread": "UNREAD" in (msg.get("label_ids") or []),
            "person": person_payload(person),
            "person_id": person.id,
            "campaign": {"id": campaign.id, "name": campaign.name} if campaign else None,
            "agent": draft_payload(draft),
        })
    if newly_recorded:
        db.commit()

    replies.sort(key=lambda r: int(r.get("internal_date") or 0), reverse=True)
    return {
        "replies": replies,
        "total": len(replies),
        "newly_recorded": newly_recorded,
        "inbox_errors": inbox_errors,
    }


async def send_thread_reply(
    db: Session,
    inbox: Inbox,
    thread_id: str,
    to: str,
    body: str,
    subject: Optional[str] = None,
) -> dict:
    """
    Reply inside an existing thread, with In-Reply-To/References set from the
    thread's last message, and log it as a manual email. Raises on failure.
    """
    gmail = gmail_for(inbox)
    thread_messages = await asyncio.to_thread(gmail.get_thread, thread_id)
    last = thread_messages[-1] if thread_messages else {}

    subject = subject or last.get("subject") or ""
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}".strip()

    result = await asyncio.to_thread(
        gmail.send_email,
        to=to,
        subject=subject,
        body=body,
        from_name=inbox.display_name,
        thread_id=thread_id,
        in_reply_to=last.get("message_id_header") or None,
        references=last.get("references") or None,
    )
    sync_tokens(inbox, gmail, db)

    person = db.query(Person).filter(func.lower(Person.email) == to.lower()).first()
    db.add(EmailLog(
        inbox_id=inbox.id,
        person_id=person.id if person else None,
        email_type=EmailType.MANUAL,
        to_email=to,
        from_email=inbox.email_address,
        subject=subject,
        body=body,
        gmail_message_id=result["message_id"],
        gmail_thread_id=result["thread_id"],
        status=EmailStatus.SENT,
        sent_at=datetime.utcnow(),
    ))
    db.commit()
    return result
