"""
Unibox: a single merged view of incoming mail across every connected Gmail
account, so replies don't have to be checked inbox-by-inbox.

/replies is the lead-focused view: only mail from known prospects (no
warmup chatter between your own inboxes, no newsletters), tagged with the
lead's company, campaign and the reply agent's triage. Loading it also
records any campaign reply the background checker hasn't caught yet, so
the lead's follow-ups stop.

/conversations is the mailbox view: every conversation you've had with a
lead (from the email log - fast, no Gmail calls), filed into "replied" (the
lead wrote last) and "awaiting" (you wrote last), so leads who haven't
answered can be followed up by hand.

/agent/* drives the reply agent: run it, then review its drafts - edit,
send or dismiss. The agent itself never sends.
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    AgentDraft,
    Campaign,
    CampaignLead,
    CampaignLeadStatus,
    EmailLog,
    EmailStatus,
    EmailType,
    Inbox,
    Person,
    SequenceStep,
)
from app.services.notifications import alert_inbox, send_notification_email, valid_email
from app.services.reply_agent import draft_thread, get_settings, run_reply_agent, settings_payload
from app.services.unibox import (
    campaign_for_thread,
    collect_lead_replies,
    connected_inboxes,
    draft_payload,
    mail_for,
    latest_draft,
    person_payload,
    send_thread_reply,
    sender_address,
    sync_tokens,
)

router = APIRouter()


def _connected_inbox_or_error(db: Session, inbox_id: int) -> Inbox:
    inbox = db.query(Inbox).filter(Inbox.id == inbox_id).first()
    if not inbox:
        raise HTTPException(status_code=404, detail="Inbox not found")
    if not inbox.has_credentials:
        raise HTTPException(status_code=400, detail="Inbox is not connected")
    return inbox


@router.get("/messages")
async def list_unibox_messages(
    per_inbox: int = Query(15, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Merge the most recent inbox messages across every connected inbox into one feed."""
    messages = []
    inbox_errors = []

    for inbox in connected_inboxes(db):
        if not inbox.has_credentials:
            inbox_errors.append({"inbox_id": inbox.id, "email": inbox.email_address, "error": "Not connected"})
            continue
        try:
            mail = mail_for(inbox)
            inbox_messages = mail.list_messages(max_results=per_inbox, label_ids=["INBOX"])
            sync_tokens(inbox, mail, db)
            for m in inbox_messages:
                m["inbox_id"] = inbox.id
                m["inbox_email"] = inbox.email_address
            messages.extend(inbox_messages)
        except Exception as exc:
            inbox_errors.append({"inbox_id": inbox.id, "email": inbox.email_address, "error": str(exc)})

    messages.sort(key=lambda m: int(m.get("internal_date") or 0), reverse=True)

    return {"messages": messages, "total": len(messages), "inbox_errors": inbox_errors}


@router.get("/replies")
async def list_lead_replies(
    days: int = Query(30, ge=1, le=180),
    per_inbox: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """
    Conversations where a known prospect wrote back, newest first - one entry
    per thread, across every connected inbox, with the agent's latest triage/draft.
    """
    return await collect_lead_replies(db, days=days, per_inbox=per_inbox)


FOLDERS = ("all", "replied", "awaiting")


def _epoch_ms(moment: Optional[datetime]) -> Optional[int]:
    return int((moment - datetime(1970, 1, 1)).total_seconds() * 1000) if moment else None


@router.get("/conversations")
async def list_conversations(
    folder: str = Query("all", description="all | replied (lead wrote last) | awaiting (you wrote last, no reply yet)"),
    days: int = Query(90, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """
    Every conversation with a lead in the last `days`, newest activity first -
    built from the email log, so it lists instantly. Open one with
    /threads/{inbox_id}/{thread_id} to read it and follow up by hand.
    """
    if folder not in FOLDERS:
        raise HTTPException(status_code=400, detail=f"folder must be one of: {', '.join(FOLDERS)}")

    since = datetime.utcnow() - timedelta(days=days)
    logs = (
        db.query(EmailLog)
        .filter(
            EmailLog.gmail_thread_id.isnot(None),
            EmailLog.email_type.in_((EmailType.CAMPAIGN, EmailType.MANUAL)),
            EmailLog.sent_at >= since,
        )
        .order_by(EmailLog.sent_at)
        .all()
    )

    threads: dict = {}
    for log in logs:
        t = threads.setdefault((log.inbox_id, log.gmail_thread_id), {
            "inbox_id": log.inbox_id, "thread_id": log.gmail_thread_id, "subject": log.subject,
            "person_id": None, "to_email": log.to_email, "campaign_id": None,
            "emails_sent": 0, "last_sent_at": None, "last_body": "", "replied_at": None, "bounced": False,
        })
        t["emails_sent"] += 1
        t["last_sent_at"] = log.sent_at
        t["last_body"] = log.body or ""
        t["person_id"] = t["person_id"] or log.person_id
        t["campaign_id"] = t["campaign_id"] or log.campaign_id
        if log.replied_at and (not t["replied_at"] or log.replied_at > t["replied_at"]):
            t["replied_at"] = log.replied_at
        if log.status == EmailStatus.BOUNCED:
            t["bounced"] = True

    person_ids = {t["person_id"] for t in threads.values() if t["person_id"]}
    people = {p.id: p for p in db.query(Person).filter(Person.id.in_(person_ids))} if person_ids else {}
    campaign_ids = {t["campaign_id"] for t in threads.values() if t["campaign_id"]}
    campaigns = {c.id: c for c in db.query(Campaign).filter(Campaign.id.in_(campaign_ids))} if campaign_ids else {}
    inboxes = {i.id: i for i in db.query(Inbox).all()}

    conversations, counts = [], {"all": 0, "replied": 0, "awaiting": 0}
    for t in threads.values():
        # Who wrote last: a reply after our latest email puts the ball in our court
        lead_wrote_last = bool(t["replied_at"] and t["replied_at"] >= t["last_sent_at"])
        state = "bounced" if t["bounced"] else "replied" if lead_wrote_last else "awaiting"
        counts["all"] += 1
        if state in counts:
            counts[state] += 1
        if folder != "all" and state != folder:
            continue

        person = people.get(t["person_id"])
        campaign = campaigns.get(t["campaign_id"])
        inbox = inboxes.get(t["inbox_id"])
        last_activity = max(filter(None, (t["last_sent_at"], t["replied_at"])))
        snippet = " ".join(t["last_body"].split())[:140]
        conversations.append({
            "inbox_id": t["inbox_id"],
            "inbox_email": inbox.email_address if inbox else None,
            "thread_id": t["thread_id"],
            "message_id": f"{t['inbox_id']}-{t['thread_id']}",
            "subject": t["subject"] or "",
            "snippet": "Lead replied" if lead_wrote_last else (f"You: {snippet}" if snippet else ""),
            "internal_date": _epoch_ms(last_activity),
            "state": state,
            "emails_sent": t["emails_sent"],
            "days_since_last_email": (datetime.utcnow() - t["last_sent_at"]).days,
            "person": person_payload(person) if person else {"email": t["to_email"], "name": None},
            "person_id": person.id if person else None,
            "campaign": {"id": campaign.id, "name": campaign.name} if campaign else None,
            "unread": False,
        })

    conversations.sort(key=lambda c: c["internal_date"] or 0, reverse=True)
    return {"conversations": conversations, "total": len(conversations), "counts": counts, "folder": folder}


def _automation_payload(db: Session, person: Optional[Person], campaign: Optional[Campaign]) -> Optional[dict]:
    """The lead's automatic follow-ups in this campaign - so a manual follow-up doesn't double up with one."""
    if not person or not campaign:
        return None
    lead = (
        db.query(CampaignLead)
        .filter(CampaignLead.campaign_id == campaign.id, CampaignLead.person_id == person.id)
        .first()
    )
    if not lead:
        return None
    total_steps = (
        db.query(SequenceStep).filter(SequenceStep.sequence_id == campaign.sequence_id).count()
        if campaign.sequence_id else 0
    )
    active = lead.status in (CampaignLeadStatus.PENDING, CampaignLeadStatus.IN_PROGRESS)
    return {
        "campaign_id": campaign.id,
        "status": lead.status.value if lead.status else None,
        "active": active and (lead.current_step or 0) < total_steps,
        "current_step": lead.current_step or 0,
        "total_steps": total_steps,
        "next_send_at": lead.next_send_at.isoformat() + "Z" if (active and lead.next_send_at) else None,
        "campaign_running": campaign.status.value == "active" if campaign.status else False,
        "stop_reason": lead.stop_reason,
    }


@router.get("/threads/{inbox_id}/{thread_id}")
async def get_unibox_thread(inbox_id: int, thread_id: str, db: Session = Depends(get_db)):
    """Full conversation for one message, from the inbox it belongs to, plus the lead and agent draft (if any)."""
    inbox = _connected_inbox_or_error(db, inbox_id)

    try:
        mail = mail_for(inbox)
        thread_messages = await asyncio.to_thread(mail.get_thread, thread_id)
        sync_tokens(inbox, mail, db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load thread: {exc}")

    own = inbox.email_address.lower()
    for msg in thread_messages:
        msg["from_me"] = sender_address(msg) == own

    other = next((m for m in reversed(thread_messages) if not m["from_me"]), None)
    person = None
    if other:
        person = db.query(Person).filter(func.lower(Person.email) == sender_address(other)).first()
    if person is None:
        # Nobody has replied yet - the lead is whoever we emailed in this thread
        log = (
            db.query(EmailLog)
            .filter(EmailLog.inbox_id == inbox.id, EmailLog.gmail_thread_id == thread_id)
            .order_by(EmailLog.sent_at.desc())
            .first()
        )
        if log:
            person = db.get(Person, log.person_id) if log.person_id else (
                db.query(Person).filter(func.lower(Person.email) == log.to_email.lower()).first()
            )
    campaign = campaign_for_thread(db, person, inbox.id, thread_id) if person else None

    return {
        "inbox_id": inbox.id,
        "inbox_email": inbox.email_address,
        "messages": thread_messages,
        "person": person_payload(person),
        "campaign": {"id": campaign.id, "name": campaign.name} if campaign else None,
        "automation": _automation_payload(db, person, campaign),
        "agent": draft_payload(latest_draft(db, inbox.id, thread_id)),
    }


class ReplyRequest(BaseModel):
    to: str
    body: str
    subject: Optional[str] = None
    # Stop this lead's automatic follow-ups in the thread's campaign - you're taking over by hand
    stop_followups: bool = False


@router.post("/threads/{inbox_id}/{thread_id}/reply")
async def reply_to_thread(inbox_id: int, thread_id: str, payload: ReplyRequest, db: Session = Depends(get_db)):
    """Send a reply that lands in the same thread - in Gmail and in the recipient's own mail client."""
    inbox = _connected_inbox_or_error(db, inbox_id)
    if not payload.body.strip():
        raise HTTPException(status_code=400, detail="Reply is empty")

    try:
        result = await send_thread_reply(db, inbox, thread_id, payload.to, payload.body, payload.subject)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to send reply: {exc}")

    stopped_followups = False
    if payload.stop_followups:
        person = db.query(Person).filter(func.lower(Person.email) == payload.to.strip().lower()).first()
        campaign = campaign_for_thread(db, person, inbox.id, thread_id) if person else None
        lead = (
            db.query(CampaignLead)
            .filter(CampaignLead.campaign_id == campaign.id, CampaignLead.person_id == person.id)
            .first()
        ) if campaign else None
        if lead and lead.status in (CampaignLeadStatus.PENDING, CampaignLeadStatus.IN_PROGRESS):
            lead.status = CampaignLeadStatus.STOPPED
            lead.stop_reason = "manual_followup"
            lead.next_send_at = None
            stopped_followups = True

    # A hand-written reply answers the conversation, so a pending agent draft is no longer needed.
    db.query(AgentDraft).filter(
        AgentDraft.inbox_id == inbox.id,
        AgentDraft.thread_id == thread_id,
        AgentDraft.status == "pending",
    ).update({"status": "dismissed"}, synchronize_session=False)
    db.commit()

    return {"success": True, "stopped_followups": stopped_followups, **result}


# ---------------------------------------------------------------------------
# Reply agent
# ---------------------------------------------------------------------------

def _agent_settings_response(db: Session) -> dict:
    row = get_settings(db)
    sender = alert_inbox(db, row.alert_inbox_id)
    return {**settings_payload(row), "alert_sent_from": sender.email_address if sender else None}


@router.get("/agent/settings")
async def agent_get_settings(db: Session = Depends(get_db)):
    """Agent instructions, auto-draft and email-alert settings, and the last background run."""
    return _agent_settings_response(db)


class AgentSettingsUpdate(BaseModel):
    instructions: Optional[str] = None
    auto_draft: Optional[bool] = None
    email_alerts_enabled: Optional[bool] = None
    notify_email: Optional[str] = None
    alert_inbox_id: Optional[int] = None


@router.put("/agent/settings")
async def agent_update_settings(payload: AgentSettingsUpdate, db: Session = Depends(get_db)):
    row = get_settings(db)
    data = payload.model_dump(exclude_unset=True)
    if data.get("notify_email"):
        data["notify_email"] = data["notify_email"].strip()
        if not valid_email(data["notify_email"]):
            raise HTTPException(status_code=400, detail="That doesn't look like a valid email address")
    if data.get("alert_inbox_id") and not db.query(Inbox).filter(Inbox.id == data["alert_inbox_id"]).first():
        raise HTTPException(status_code=400, detail="Inbox not found")
    for field, value in data.items():
        setattr(row, field, value)
    if row.email_alerts_enabled and not row.notify_email:
        db.rollback()
        raise HTTPException(status_code=400, detail="Add the email address to notify before turning alerts on")
    db.commit()
    return _agent_settings_response(db)


@router.post("/agent/test-alert")
async def agent_test_alert(db: Session = Depends(get_db)):
    """Send a test alert email to the notification address."""
    row = get_settings(db)
    if not row.notify_email:
        raise HTTPException(status_code=400, detail="Add the email address to notify first")
    try:
        return await send_notification_email(
            db,
            row.notify_email,
            "Test alert from your reply agent",
            "Email alerts are working. You'll get an email like this when lead replies are drafted and waiting for your approval in the Lead Box.",
            inbox_id=row.alert_inbox_id,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class AgentRunRequest(BaseModel):
    # Overrides the saved instructions for this run only; omit to use the saved ones.
    instructions: Optional[str] = None
    days: int = 30


@router.post("/agent/run")
async def agent_run(payload: AgentRunRequest, db: Session = Depends(get_db)):
    """Triage every new lead reply and draft responses. Drafts wait for approval - nothing is sent."""
    try:
        return await run_reply_agent(db, instructions=payload.instructions, days=payload.days)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


class ThreadDraftRequest(BaseModel):
    # Optional steer for this draft, e.g. "shorter", "offer Thursday 2pm", "mention the Acme case study".
    guidance: str = ""


@router.post("/agent/threads/{inbox_id}/{thread_id}/draft")
async def agent_draft_thread(inbox_id: int, thread_id: str, payload: ThreadDraftRequest, db: Session = Depends(get_db)):
    """Have the agent draft (or redraft) a reply for this one conversation. Nothing is sent."""
    try:
        draft = await draft_thread(db, inbox_id, thread_id, guidance=payload.guidance)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if draft.status == "failed":
        raise HTTPException(status_code=502, detail=f"The agent couldn't draft this reply: {draft.error}")
    return draft_payload(draft)


@router.get("/agent/drafts")
async def agent_drafts(
    status: Optional[str] = Query("pending"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Agent drafts, newest first (pending by default; pass status= empty for all)."""
    query = db.query(AgentDraft)
    if status:
        query = query.filter(AgentDraft.status == status)
    drafts = query.order_by(AgentDraft.created_at.desc()).limit(limit).all()
    return {
        "drafts": [
            {
                **draft_payload(d),
                "inbox_id": d.inbox_id,
                "thread_id": d.thread_id,
                "person": person_payload(d.person),
            }
            for d in drafts
        ]
    }


def _get_draft_or_404(db: Session, draft_id: int) -> AgentDraft:
    draft = db.query(AgentDraft).filter(AgentDraft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


class DraftUpdate(BaseModel):
    draft_body: Optional[str] = None
    draft_subject: Optional[str] = None


@router.put("/agent/drafts/{draft_id}")
async def agent_update_draft(draft_id: int, payload: DraftUpdate, db: Session = Depends(get_db)):
    """Save edits to a draft without sending it."""
    draft = _get_draft_or_404(db, draft_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(draft, field, value)
    db.commit()
    return draft_payload(draft)


class DraftSend(BaseModel):
    # The final text to send - lets the UI send exactly what's in the editor.
    body: Optional[str] = None


@router.post("/agent/drafts/{draft_id}/send")
async def agent_send_draft(draft_id: int, payload: DraftSend, db: Session = Depends(get_db)):
    """Approve and send a draft as a reply in its conversation."""
    draft = _get_draft_or_404(db, draft_id)
    if draft.status != "pending":
        raise HTTPException(status_code=400, detail=f"Draft is {draft.status}, not pending")

    body = (payload.body if payload.body is not None else draft.draft_body or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="Draft is empty")
    if "[[" in body:
        raise HTTPException(status_code=400, detail="Fill in the [[placeholders]] before sending")
    if not draft.person:
        raise HTTPException(status_code=400, detail="The lead for this draft no longer exists")

    inbox = _connected_inbox_or_error(db, draft.inbox_id)
    try:
        result = await send_thread_reply(db, inbox, draft.thread_id, draft.person.email, body, draft.draft_subject)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to send reply: {exc}")

    draft.draft_body = body
    draft.status = "sent"
    draft.sent_at = datetime.utcnow()
    db.commit()
    return {"success": True, **result}


@router.post("/agent/drafts/{draft_id}/dismiss")
async def agent_dismiss_draft(draft_id: int, db: Session = Depends(get_db)):
    """Discard a draft. The agent won't re-draft this reply; a new message from the lead gets a fresh draft."""
    draft = _get_draft_or_404(db, draft_id)
    draft.status = "dismissed"
    db.commit()
    return {"success": True}
