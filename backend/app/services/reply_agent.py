"""
Reply agent: reads lead replies in the Lead Box, triages each one (what kind
of reply is it, what does the lead want, should their status change) and
drafts a response. Draft-only by design - every draft waits in the Lead Box
for a person to edit, send or dismiss; nothing here sends email.

Three ways it runs:
- "Run agent" in the Lead Box - every reply without a draft yet
- per conversation - draft (or redraft, with guidance) one thread on demand
- in the background - when auto-draft is on, new replies are drafted every
  few minutes and the human is pulled in by email (human in the loop)

Each lead message is handled once (AgentDraft.lead_message_id is unique),
so batch runs only pick up replies that arrived since.
"""
import asyncio
import json
import re
from datetime import datetime
from typing import Optional

import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AgentDraft, AgentSettings, Inbox, LeadStatus, Person
from app.services.calendly import booking_url
from app.services.campaign_engine import openai_configured
from app.services.notifications import send_notification_email
from app.services.personalization import build_company_context
from app.services.unibox import (
    campaign_for_thread,
    collect_lead_replies,
    gmail_for,
    sender_address,
    sync_tokens,
)

logger = structlog.get_logger()

MAX_THREADS_PER_RUN = 25
CONCURRENCY = 4
MAX_MESSAGES_IN_CONTEXT = 8
MAX_CHARS_PER_MESSAGE = 2500
AUTO_RUN_INTERVAL_SECONDS = 5 * 60

CATEGORIES = {
    "interested": "wants to talk, learn more, or take a next step",
    "question": "asks something (pricing, details, how it works) before deciding",
    "not_interested": "declines, not a fit, not now",
    "out_of_office": "automatic away/vacation reply",
    "unsubscribe": "asks to stop emailing / be removed",
    "wrong_person": "not the right contact, may point to someone else",
    "other": "anything else",
}

# Statuses the agent may suggest. It never applies them itself.
SUGGESTABLE_STATUSES = {"converted", "unsubscribed", "do_not_contact"}

SYSTEM_PROMPT = f"""You are a sales assistant handling replies to cold outreach emails. For the conversation given, you triage the lead's latest reply and draft our response. A human reviews every draft before anything is sent.

Categories:
{chr(10).join(f'- {name}: {desc}' for name, desc in CATEGORIES.items())}

Drafting rules:
- Reply to the lead's latest message. Plain text, short (2-5 sentences), match their tone, no exclamation points, no emoji, no marketing fluff.
- Answer questions directly. For "interested", propose one concrete next step consistent with the sender's instructions.
- Never invent facts - prices, links, dates, availability, case studies, features. If the reply needs a fact you don't have, put a placeholder in double square brackets, e.g. [[pricing for 10 seats]], so the human fills it in.
- Sign off with the sender's first name only.
- For "out_of_office", "unsubscribe" and "not_interested" with no question, set needs_reply false and leave draft empty - unless "not_interested" leaves a door open worth a one-line gracious close.
- For "wrong_person", thank them and ask who the right contact is (or acknowledge the referral they gave).
- If the human gives guidance for this draft, follow it - it overrides the defaults above, including writing a draft when needs_reply would otherwise be false.

suggested_status: one of "converted" (clearly interested / wants a meeting), "unsubscribed" (asked to stop), "do_not_contact" (hostile or legal threat), or null.

Respond with only a JSON object:
{{"category": "...", "summary": "one sentence: what the lead said or wants", "suggested_status": null, "needs_reply": true, "draft": "..."}}"""


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_settings(db: Session) -> AgentSettings:
    row = db.query(AgentSettings).first()
    if not row:
        row = AgentSettings(instructions="", auto_draft=True, email_alerts_enabled=False)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def settings_payload(row: AgentSettings) -> dict:
    try:
        last_result = json.loads(row.last_auto_result) if row.last_auto_result else None
    except ValueError:
        last_result = None
    return {
        "instructions": row.instructions or "",
        "auto_draft": bool(row.auto_draft),
        "auto_interval_minutes": AUTO_RUN_INTERVAL_SECONDS // 60,
        "email_alerts_enabled": bool(row.email_alerts_enabled),
        "notify_email": row.notify_email or "",
        "alert_inbox_id": row.alert_inbox_id,
        "openai_configured": openai_configured(),
        "last_auto_run_at": row.last_auto_run_at.isoformat() if row.last_auto_run_at else None,
        "last_auto_result": last_result,
    }


# ---------------------------------------------------------------------------
# Drafting
# ---------------------------------------------------------------------------

_QUOTE_START = re.compile(r"^(On .+wrote:|-----Original Message-----|From: .+|Sent from my )", re.IGNORECASE)


def strip_quoted(body: str) -> str:
    """Drop the quoted history mail clients append below a reply, so each message reads as just what was written."""
    kept = []
    for line in (body or "").splitlines():
        if _QUOTE_START.match(line.strip()):
            break
        if line.lstrip().startswith(">"):
            continue
        kept.append(line)
    text = "\n".join(kept).strip()
    return text or (body or "").strip()


def _format_thread(messages: list, our_address: str) -> str:
    parts = []
    for msg in messages[-MAX_MESSAGES_IN_CONTEXT:]:
        who = "US" if sender_address(msg) == our_address else "LEAD"
        body = strip_quoted(msg.get("body") or msg.get("snippet") or "")[:MAX_CHARS_PER_MESSAGE]
        parts.append(f"[{who}] {msg.get('date', '')}\nSubject: {msg.get('subject', '')}\n{body}")
    return "\n\n---\n\n".join(parts)


def _lead_context(person: Person) -> str:
    lines = [f"Name: {person.full_name or ' '.join(p for p in (person.first_name, person.last_name) if p) or 'unknown'}"]
    if person.role:
        lines.append(f"Role: {person.role}")
    if person.company:
        lines.append(build_company_context(person.company)[:2500])
    return "\n".join(lines)


async def _ask_model(user_prompt: str) -> dict:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=600,
        temperature=0.4,
    )
    return json.loads(resp.choices[0].message.content)


def _normalize(result: dict, guided: bool) -> dict:
    category = result.get("category") if result.get("category") in CATEGORIES else "other"
    status = result.get("suggested_status")
    draft = (result.get("draft") or "").strip()
    if result.get("needs_reply") is False and not guided:
        draft = ""
    return {
        "category": category,
        "summary": (result.get("summary") or "").strip()[:1000],
        "suggested_status": status if status in SUGGESTABLE_STATUSES else None,
        "draft": draft,
    }


async def _draft_conversation(
    db: Session,
    inbox: Inbox,
    thread_id: str,
    messages: list,
    lead_message: dict,
    person: Person,
    instructions: str,
    campaign_id: Optional[int] = None,
    guidance: str = "",
) -> AgentDraft:
    """Triage + draft one conversation and store it. Reuses the row if this lead message was drafted before (a redraft)."""
    our_address = inbox.email_address.lower()
    sender_name = inbox.display_name or inbox.email_address.split("@")[0]
    user_prompt = (
        f"Sender (us): {sender_name} <{inbox.email_address}>\n\n"
        f"Sender's instructions (offer, tone, next step to propose):\n{instructions.strip() or '(none given - keep it general and use placeholders for specifics)'}\n\n"
        f"Lead:\n{_lead_context(person)}\n\n"
        f"Conversation, oldest first:\n\n{_format_thread(messages, our_address)}"
    )
    booking = booking_url(db)
    if booking:
        user_prompt += f"\n\nBooking link - when proposing a call, offer this link (use it exactly as written): {booking}"
    if sender_address(messages[-1]) == our_address:
        user_prompt += "\n\nNote: we sent the last message and the lead hasn't answered it yet - draft a short, polite follow-up rather than a reply."
    if guidance.strip():
        user_prompt += f"\n\nHuman's guidance for this draft:\n{guidance.strip()}"

    draft = db.query(AgentDraft).filter(AgentDraft.lead_message_id == lead_message["id"]).first()
    if draft is None:
        draft = AgentDraft(inbox_id=inbox.id, thread_id=thread_id, lead_message_id=lead_message["id"])
    draft.person_id = person.id
    draft.campaign_id = campaign_id
    draft.draft_subject = lead_message.get("subject")
    draft.error = None
    draft.sent_at = None

    try:
        result = _normalize(await _ask_model(user_prompt), guided=bool(guidance.strip()))
        draft.category = result["category"]
        draft.summary = result["summary"]
        draft.suggested_status = result["suggested_status"]
        draft.draft_body = result["draft"]
        draft.status = "pending"
    except Exception as exc:
        logger.warning("agent.draft_failed", thread_id=thread_id, error=str(exc))
        draft.status = "failed"
        draft.error = str(exc)

    # Only one pending draft per conversation - an older one is replaced by this one.
    query = db.query(AgentDraft).filter(
        AgentDraft.inbox_id == inbox.id,
        AgentDraft.thread_id == thread_id,
        AgentDraft.status == "pending",
    )
    if draft.id:
        query = query.filter(AgentDraft.id != draft.id)
    query.update({"status": "superseded"}, synchronize_session=False)
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


async def _process_reply(db: Session, inbox: Inbox, reply: dict, instructions: str) -> dict:
    """Batch-run handling for one conversation from the lead-replies feed."""
    gmail = gmail_for(inbox)
    messages = await asyncio.to_thread(gmail.get_thread, reply["thread_id"])
    sync_tokens(inbox, gmail, db)

    if not messages or sender_address(messages[-1]) == inbox.email_address.lower():
        return {"result": "skipped", "reason": "already answered"}

    person = db.get(Person, reply["person_id"])
    if person.status in (LeadStatus.UNSUBSCRIBED, LeadStatus.DO_NOT_CONTACT):
        return {"result": "skipped", "reason": f"lead is {person.status.value}"}

    lead_message = next((m for m in reversed(messages) if m["id"] == reply["message_id"]), messages[-1])
    draft = await _draft_conversation(
        db, inbox, reply["thread_id"], messages, lead_message, person, instructions,
        campaign_id=(reply.get("campaign") or {}).get("id"),
    )
    return {"result": "failed" if draft.status == "failed" else "created", "draft_id": draft.id, "category": draft.category}


async def draft_thread(db: Session, inbox_id: int, thread_id: str, guidance: str = "") -> AgentDraft:
    """
    Draft (or redraft) a reply for one conversation on demand - works even if
    the batch run already handled it or skipped it. Raises ValueError for
    conversations it can't draft (not a known lead, OpenAI not configured).
    """
    if not openai_configured():
        raise ValueError("OPENAI_API_KEY is not configured in backend/.env")
    inbox = db.query(Inbox).filter(Inbox.id == inbox_id).first()
    if not inbox or not inbox.access_token or not inbox.refresh_token:
        raise ValueError("Inbox is not connected to Gmail")

    gmail = gmail_for(inbox)
    messages = await asyncio.to_thread(gmail.get_thread, thread_id)
    sync_tokens(inbox, gmail, db)
    if not messages:
        raise ValueError("Conversation not found")

    our_address = inbox.email_address.lower()
    lead_message = next((m for m in reversed(messages) if sender_address(m) != our_address), None)
    if not lead_message:
        raise ValueError("The other side hasn't written in this conversation yet")
    person = db.query(Person).filter(func.lower(Person.email) == sender_address(lead_message)).first()
    if not person:
        raise ValueError("The agent only drafts for prospects in your Prospects list")

    campaign = campaign_for_thread(db, person, inbox.id, thread_id)
    instructions = get_settings(db).instructions or ""
    return await _draft_conversation(
        db, inbox, thread_id, messages, lead_message, person, instructions,
        campaign_id=campaign.id if campaign else None, guidance=guidance,
    )


_run_lock = asyncio.Lock()


async def run_reply_agent(db: Session, instructions: Optional[str] = None, days: int = 30) -> dict:
    """Triage and draft every lead reply that doesn't have a draft yet. Never sends anything."""
    if not openai_configured():
        raise ValueError("OPENAI_API_KEY is not configured in backend/.env")
    if _run_lock.locked():
        raise RuntimeError("The agent is already running")
    if instructions is None:
        instructions = get_settings(db).instructions or ""

    async with _run_lock:
        feed = await collect_lead_replies(db, days=days)
        handled = {
            mid for (mid,) in db.query(AgentDraft.lead_message_id).filter(
                AgentDraft.lead_message_id.in_([r["message_id"] for r in feed["replies"]])
            )
        } if feed["replies"] else set()
        todo = [r for r in feed["replies"] if r["message_id"] not in handled]
        inboxes = {i.id: i for i in db.query(Inbox).filter(Inbox.id.in_({r["inbox_id"] for r in todo})).all()} if todo else {}

        summary = {"replies_found": feed["total"], "already_drafted": feed["total"] - len(todo), "drafted": 0,
                   "skipped": 0, "failed": 0, "deferred": max(0, len(todo) - MAX_THREADS_PER_RUN),
                   "categories": {}, "draft_ids": [], "errors": feed["inbox_errors"]}

        # Gmail + OpenAI calls run concurrently; DB writes happen between awaits, so they don't interleave.
        semaphore = asyncio.Semaphore(CONCURRENCY)

        async def handle(reply):
            async with semaphore:
                try:
                    return await _process_reply(db, inboxes[reply["inbox_id"]], reply, instructions)
                except Exception as exc:
                    db.rollback()
                    logger.warning("agent.thread_failed", thread_id=reply["thread_id"], error=str(exc))
                    return {"result": "failed", "error": str(exc)}

        for outcome in await asyncio.gather(*(handle(r) for r in todo[:MAX_THREADS_PER_RUN])):
            key = {"created": "drafted", "skipped": "skipped", "failed": "failed"}[outcome["result"]]
            summary[key] += 1
            if outcome["result"] == "created":
                summary["draft_ids"].append(outcome["draft_id"])
            if outcome.get("category"):
                summary["categories"][outcome["category"]] = summary["categories"].get(outcome["category"], 0) + 1

        return summary


# ---------------------------------------------------------------------------
# Human in the loop: email alerts
# ---------------------------------------------------------------------------

def _thread_link(draft: AgentDraft) -> str:
    return f"{settings.app_base_url.rstrip('/')}/leadbox?inbox={draft.inbox_id}&thread={draft.thread_id}"


def build_drafts_email(drafts: list) -> tuple:
    """(subject, body) for one alert covering every new draft, so a burst of replies is one email, not many."""
    needing_reply = [d for d in drafts if d.draft_body]
    count = len(needing_reply)
    subject = f"{count} lead repl{'y' if count == 1 else 'ies'} drafted - waiting for your approval"

    sections = []
    for draft in needing_reply:
        person = draft.person
        who = (person.full_name or " ".join(p for p in (person.first_name, person.last_name) if p) or person.email) if person else "A lead"
        company = f" ({person.company.name})" if person and person.company else ""
        label = (draft.category or "other").replace("_", " ")
        sections.append(
            f"{who}{company} - {label}\n"
            f"{draft.summary}\n\n"
            f"Agent's draft:\n{draft.draft_body}\n\n"
            f"Review, edit and send: {_thread_link(draft)}"
        )

    body = (
        f"The reply agent drafted {count} response{'' if count == 1 else 's'} to new lead replies. "
        "Nothing has been sent - each one waits for you in the Lead Box.\n\n"
        + "\n\n----------\n\n".join(sections)
        + "\n\n-- Outbound agent (turn these alerts off in the Lead Box agent panel)"
    )
    return subject, body


async def notify_new_drafts(db: Session, draft_ids: list) -> Optional[dict]:
    """Email the human about new drafts that need a reply. No-op unless alerts are switched on."""
    row = get_settings(db)
    if not (row.email_alerts_enabled and row.notify_email):
        return None
    drafts = db.query(AgentDraft).filter(AgentDraft.id.in_(draft_ids), AgentDraft.status == "pending").all() if draft_ids else []
    if not any(d.draft_body for d in drafts):
        return None  # e.g. only out-of-office replies - nothing for the human to approve
    subject, body = build_drafts_email(drafts)
    return await send_notification_email(db, row.notify_email, subject, body, inbox_id=row.alert_inbox_id)


async def auto_run_once(db: Session) -> Optional[dict]:
    """One background pass: draft new replies if auto-draft is on, then text the human if anything is waiting."""
    row = get_settings(db)
    if not row.auto_draft or not openai_configured() or _run_lock.locked():
        return None

    result = await run_reply_agent(db, instructions=row.instructions or "")
    try:
        alert = await notify_new_drafts(db, result["draft_ids"])
        result["email_alert"] = "sent" if alert else "not sent"
    except Exception as exc:
        result["email_alert"] = f"failed: {exc}"

    row = get_settings(db)
    row.last_auto_run_at = datetime.utcnow()
    row.last_auto_result = json.dumps({k: v for k, v in result.items() if k != "errors"})
    db.commit()
    return result


_scheduler_task: Optional[asyncio.Task] = None


async def _scheduler_loop(interval_seconds: int):
    from app.database import SessionLocal

    from app.tenancy import run_per_owner

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            # Each account's own agent settings, inboxes and alert address
            results = await run_per_owner(auto_run_once)
            for owner_id, result in results.items():
                if result and (result["drafted"] or result["failed"]):
                    logger.info("agent.auto_run", owner_id=owner_id, drafted=result["drafted"], failed=result["failed"], email_alert=result.get("email_alert"))
        except Exception as exc:
            logger.error("agent.auto_run_failed", error=str(exc))


def start_agent_scheduler(interval_seconds: int = AUTO_RUN_INTERVAL_SECONDS):
    global _scheduler_task
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(_scheduler_loop(interval_seconds))
        logger.info("agent.scheduler_started", interval_seconds=interval_seconds)


def stop_agent_scheduler():
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        logger.info("agent.scheduler_stopped")
