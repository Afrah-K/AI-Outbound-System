"""
Campaign engine: walks every active campaign's leads through its sequence -
render each step's template for the lead, send it from one of the
campaign's inboxes inside the campaign's send window, schedule the next
step, and stop a lead as soon as they reply or bounce.

State lives entirely in the DB (CampaignLead.current_step / next_send_at
plus EmailLog), so a restart just picks up where it left off. Runs as a
periodic background loop like warmup - each cycle sends at most one email
per inbox, so volume drips out across the send window instead of bursting.

Restart safety: an EmailLog row is committed as SENDING *before* the Gmail
call. If the process dies mid-send, the next cycle finds that row, can't
know whether Gmail delivered it, and stops the lead (stop_reason
"send_interrupted") rather than risk emailing a prospect twice.
"""
import asyncio
import json
import random
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from typing import Optional
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.integrations.gmail import GmailService
from app.models import (
    Campaign,
    CampaignLead,
    CampaignLeadStatus,
    CampaignStatus,
    EmailLog,
    EmailStatus,
    EmailType,
    Inbox,
    LeadStatus,
    Person,
    SequenceStep,
)

logger = structlog.get_logger()

CYCLE_INTERVAL_SECONDS = 60
REPLY_CHECK_INTERVAL_SECONDS = 5 * 60
REPLY_LOOKBACK_DAYS = 30
MAX_THREADS_CHECKED_PER_INBOX = 200

MAX_SEND_ATTEMPTS = 3
SEND_RETRY_DELAY = timedelta(minutes=30)
GPT_RETRY_DELAY = timedelta(hours=1)

# Statuses meaning "this email actually went out" - used to find the thread a follow-up should join.
DELIVERED_STATUSES = (
    EmailStatus.SENT,
    EmailStatus.DELIVERED,
    EmailStatus.OPENED,
    EmailStatus.CLICKED,
    EmailStatus.REPLIED,
)

ACTIVE_LEAD_STATUSES = (CampaignLeadStatus.PENDING, CampaignLeadStatus.IN_PROGRESS)


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

# {{first_name}} or {{first_name|there}} - the part after | is the fallback when the lead has no value.
_VARIABLE_RE = re.compile(r"\{\{\s*(\w+)\s*(?:\|([^}]*))?\}\}")

KNOWN_VARIABLES = {
    "first_name": "Lead's first name",
    "last_name": "Lead's last name",
    "full_name": "Lead's full name",
    "email": "Lead's email address",
    "role": "Lead's job title",
    "company_name": "Lead's company name",
    "company_website": "Lead's company website",
    "industry": "Lead's company industry",
    "location": "Lead's company location",
    "personalization": "Personalization sentence for the lead (falls back to the company's hook)",
    "sender_name": "Display name of the sending inbox",
    "sender_first_name": "First word of the sending inbox's display name",
}

# Names the frontend's sequence editor advertises, mapped onto the canonical ones above.
VARIABLE_ALIASES = {
    "company": "company_name",
    "title": "role",
    "website": "company_website",
    "name": "full_name",
}


class MissingVariableError(Exception):
    def __init__(self, variables: list):
        self.variables = variables
        super().__init__(f"Lead has no value for: {', '.join(variables)}")


def _canonical(name: str) -> str:
    name = name.lower()
    return VARIABLE_ALIASES.get(name, name)


def find_unknown_variables(*texts: Optional[str]) -> list:
    unknown = []
    for text in texts:
        for match in _VARIABLE_RE.finditer(text or ""):
            if _canonical(match.group(1)) not in KNOWN_VARIABLES and match.group(1) not in unknown:
                unknown.append(match.group(1))
    return unknown


def build_variables(person: Person, inbox: Optional[Inbox] = None) -> dict:
    company = person.company
    full_name = person.full_name or " ".join(p for p in (person.first_name, person.last_name) if p)
    sender_name = (inbox.display_name if inbox else None) or ""
    return {
        "first_name": person.first_name or "",
        "last_name": person.last_name or "",
        "full_name": full_name,
        "email": person.email or "",
        "role": person.role or "",
        "company_name": company.name if company else "",
        "company_website": (company.website or company.domain or "") if company else "",
        "industry": (company.industry or "") if company else "",
        "location": (company.location or "") if company else "",
        "personalization": person.personalization_sentence
        or ((company.personalization_hook or "") if company else ""),
        "sender_name": sender_name,
        "sender_first_name": sender_name.split(" ")[0] if sender_name else "",
    }


def render_template(text: Optional[str], variables: dict) -> tuple:
    """Returns (rendered_text, missing) where missing lists variables that had no value and no fallback."""
    missing = []

    def replace(match):
        name = _canonical(match.group(1))
        fallback = match.group(2)
        value = (variables.get(name) or "").strip()
        if value:
            return value
        if fallback is not None:
            return fallback.strip()
        if match.group(1) not in missing:
            missing.append(match.group(1))
        return ""

    return _VARIABLE_RE.sub(replace, text or ""), missing


# ---------------------------------------------------------------------------
# Scheduling helpers
# ---------------------------------------------------------------------------

def _parse_hhmm(value: str):
    return datetime.strptime(value, "%H:%M").time()


def in_send_window(campaign: Campaign, now_utc: Optional[datetime] = None) -> bool:
    """Whether it's currently inside the campaign's sending hours, in the campaign's own timezone."""
    tz = ZoneInfo(campaign.timezone or settings.default_timezone)
    local = (now_utc or datetime.utcnow()).replace(tzinfo=timezone.utc).astimezone(tz)

    if not campaign.send_on_weekends and local.weekday() >= 5:
        return False

    start = _parse_hhmm(campaign.send_start_time or settings.default_send_start_time)
    end = _parse_hhmm(campaign.send_end_time or settings.default_send_end_time)
    current = local.time()
    if start <= end:
        return start <= current < end
    return current >= start or current < end  # window wraps past midnight


def next_window_start(campaign: Campaign, now_utc: Optional[datetime] = None) -> Optional[datetime]:
    """When the campaign's send window next opens (naive UTC), or None if it's open right now."""
    now_utc = now_utc or datetime.utcnow()
    if in_send_window(campaign, now_utc):
        return None
    tz = ZoneInfo(campaign.timezone or settings.default_timezone)
    local_now = now_utc.replace(tzinfo=timezone.utc).astimezone(tz)
    start = _parse_hhmm(campaign.send_start_time or settings.default_send_start_time)
    for day in range(8):
        candidate = datetime.combine(local_now.date() + timedelta(days=day), start, tzinfo=tz)
        if candidate <= local_now:
            continue
        if not campaign.send_on_weekends and candidate.weekday() >= 5:
            continue
        return candidate.astimezone(timezone.utc).replace(tzinfo=None)
    return None


def describe_sending_state(db: Session, campaign: Campaign, now: Optional[datetime] = None) -> dict:
    """
    What an active campaign is doing right now and when its next email is due,
    so a campaign that's waiting (outside hours, on a break, out of inbox quota)
    doesn't look broken. next_send_at is naive UTC, or None if unknown/not applicable.
    """
    now = now or datetime.utcnow()
    if campaign.status != CampaignStatus.ACTIVE:
        return {"state": campaign.status.value if campaign.status else "draft", "next_send_at": None}

    def result(state, when=None):
        return {"state": state, "next_send_at": when.isoformat() if when else None}

    active_leads = (
        db.query(CampaignLead)
        .filter(CampaignLead.campaign_id == campaign.id, CampaignLead.status.in_(ACTIVE_LEAD_STATUSES))
        .count()
    )
    if not active_leads:
        return result("finishing")

    try:
        opens = next_window_start(campaign, now)
    except Exception:
        return result("invalid_schedule")
    if opens:
        return result("outside_hours", opens)

    if campaign.next_send_after and campaign.next_send_after > now:
        return result("on_break", campaign.next_send_after)

    pool = [ci.inbox for ci in campaign.campaign_inboxes if ci.inbox and _inbox_connected(ci.inbox)]
    if not pool:
        return result("no_inboxes")
    start_of_today = datetime(now.year, now.month, now.day)
    def remaining(inbox):
        sent = 0 if (not inbox.last_reset_date or inbox.last_reset_date < start_of_today) else (inbox.emails_sent_today or 0)
        return (inbox.daily_limit or settings.default_daily_limit) - sent
    if all(remaining(i) <= 0 for i in pool):
        # Inbox counters reset at midnight UTC; sending also needs the window to be open then.
        reset = start_of_today + timedelta(days=1)
        return result("daily_limit", max(reset, next_window_start(campaign, reset) or reset))

    has_due = (
        db.query(CampaignLead)
        .filter(
            CampaignLead.campaign_id == campaign.id,
            (CampaignLead.status == CampaignLeadStatus.PENDING)
            | ((CampaignLead.status == CampaignLeadStatus.IN_PROGRESS) & (CampaignLead.next_send_at <= now)),
        )
        .first()
    )
    if not has_due:
        upcoming = (
            db.query(func.min(CampaignLead.next_send_at))
            .filter(CampaignLead.campaign_id == campaign.id, CampaignLead.status == CampaignLeadStatus.IN_PROGRESS)
            .scalar()
        )
        return result("waiting_followups", upcoming)

    return result("sending", now)


def _step_delay(step: SequenceStep) -> timedelta:
    return timedelta(days=step.delay_days or 0, hours=step.delay_hours or 0)


def ordered_steps(campaign: Campaign) -> list:
    """A lead's current_step is an index into this list, not SequenceStep.order itself."""
    if not campaign.sequence:
        return []
    return sorted(campaign.sequence.steps, key=lambda s: (s.order, s.id))


def _reply_subject(subject: Optional[str]) -> str:
    subject = (subject or "").strip()
    return subject if subject.lower().startswith("re:") else f"Re: {subject}"


def _strip_reply_prefix(subject: Optional[str]) -> str:
    return re.sub(r"^(re:\s*)+", "", (subject or "").strip(), flags=re.IGNORECASE).lower()


# ---------------------------------------------------------------------------
# Inbox helpers
# ---------------------------------------------------------------------------

def _inbox_connected(inbox: Inbox) -> bool:
    return bool(inbox.is_active and inbox.access_token and inbox.refresh_token)


def _reset_daily_counter(inbox: Inbox, now: datetime) -> None:
    start_of_today = datetime(now.year, now.month, now.day)
    if not inbox.last_reset_date or inbox.last_reset_date < start_of_today:
        inbox.emails_sent_today = 0
        inbox.last_reset_date = now


def _remaining_capacity(inbox: Inbox) -> int:
    return (inbox.daily_limit or settings.default_daily_limit) - (inbox.emails_sent_today or 0)


def _past_send_gap(db: Session, inbox: Inbox, now: datetime) -> bool:
    """Randomized gap between campaign sends from one inbox, so sends don't land on a fixed rhythm."""
    last_sent = (
        db.query(func.max(EmailLog.sent_at))
        .filter(EmailLog.inbox_id == inbox.id, EmailLog.email_type == EmailType.CAMPAIGN)
        .scalar()
    )
    if not last_sent:
        return True
    gap = random.uniform(settings.min_delay_seconds, settings.max_delay_seconds)
    return (now - last_sent).total_seconds() >= gap


def _sync_tokens(inbox: Inbox, gmail: GmailService) -> None:
    updated = gmail.updated_tokens
    if updated["access_token"] != inbox.access_token:
        inbox.access_token = updated["access_token"]
        inbox.token_expiry = updated["token_expiry"]


# ---------------------------------------------------------------------------
# GPT personalization
# ---------------------------------------------------------------------------

GPT_SYSTEM_PROMPT = """You personalize a cold email draft for one specific recipient.

Rules:
- Keep the draft's offer, structure, call to action and approximate length. You are tailoring it, not rewriting it.
- Weave in one concrete, specific detail about the recipient's company from the context given. If the context has nothing specific, leave the draft essentially as is - never invent details.
- Plain text, no exclamation points, no emoji, no placeholders like [Name].
- Follow any extra instructions given.

Respond with a JSON object: {"subject": "...", "body": "..."}"""


def openai_configured() -> bool:
    return bool(settings.openai_api_key) and not settings.openai_api_key.startswith("your_")


async def personalize_with_gpt(subject: str, body: str, person: Person, instructions: Optional[str] = None) -> dict:
    """Returns {subject, body} on success, or {error} on failure."""
    if not openai_configured():
        return {"error": "OPENAI_API_KEY is not configured"}

    from openai import AsyncOpenAI
    from app.services.personalization import build_company_context, build_minimal_context

    company = person.company
    context = build_company_context(company) if company else build_minimal_context("Unknown company")
    contact = person.full_name or person.first_name or person.email
    user_prompt = (
        f"Recipient: {contact}" + (f", {person.role}" if person.role else "")
        + f"\n\nRecipient's company:\n{context}"
        + f"\n\nDraft subject: {subject}\n\nDraft body:\n{body}"
    )
    if instructions:
        user_prompt += f"\n\nExtra instructions:\n{instructions}"

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": GPT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=600,
            temperature=0.6,
        )
        parsed = json.loads(resp.choices[0].message.content)
        if not parsed.get("body"):
            return {"error": "GPT returned an empty body"}
        return {"subject": parsed.get("subject") or subject, "body": parsed["body"]}
    except Exception as exc:
        logger.warning("campaign.gpt_failed", person=person.email, error=str(exc))
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Readiness checks
# ---------------------------------------------------------------------------

def validate_campaign_ready(db: Session, campaign: Campaign) -> list:
    """Everything that would stop a campaign from sending, as human-readable messages. Empty list = ready."""
    errors = []

    steps = ordered_steps(campaign)
    if not campaign.sequence_id or not campaign.sequence:
        errors.append("Campaign has no sequence assigned")
    elif not steps:
        errors.append("The campaign's sequence has no steps")
    else:
        if not (steps[0].subject or "").strip():
            errors.append("The first step needs a subject (only follow-ups can leave it blank to reply in-thread)")
        for index, step in enumerate(steps, start=1):
            unknown = find_unknown_variables(step.subject, step.body)
            if unknown:
                errors.append(f"Step {index} uses unknown variables: {', '.join(unknown)}")
            if not (step.body or "").strip():
                errors.append(f"Step {index} has an empty body")
        if any(s.use_gpt for s in steps) and not openai_configured():
            errors.append("A step uses GPT personalization but OPENAI_API_KEY is not configured")

    try:
        in_send_window(campaign)
    except Exception:
        errors.append(f"Invalid timezone or send window: {campaign.timezone} {campaign.send_start_time}-{campaign.send_end_time}")

    inboxes = [ci.inbox for ci in campaign.campaign_inboxes if ci.inbox]
    if not inboxes:
        errors.append("Campaign has no inboxes assigned")
    elif not any(_inbox_connected(i) for i in inboxes):
        errors.append("None of the campaign's inboxes are active and connected to Gmail")

    has_sendable_leads = (
        db.query(CampaignLead)
        .filter(CampaignLead.campaign_id == campaign.id, CampaignLead.status.in_(ACTIVE_LEAD_STATUSES))
        .first()
    )
    if not has_sendable_leads:
        errors.append("Campaign has no leads left to email")

    return errors


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def _stop_lead(lead: CampaignLead, reason: str) -> None:
    lead.status = CampaignLeadStatus.STOPPED
    lead.stop_reason = reason
    lead.next_send_at = None


def _complete_lead(lead: CampaignLead) -> None:
    lead.status = CampaignLeadStatus.COMPLETED
    lead.next_send_at = None


def _advance_lead(lead: CampaignLead, steps: list, now: datetime) -> None:
    lead.current_step = (lead.current_step or 0) + 1
    if lead.current_step >= len(steps):
        _complete_lead(lead)
    else:
        lead.next_send_at = now + _step_delay(steps[lead.current_step])


def _stop_reason_for(person: Optional[Person], campaign: Campaign) -> Optional[str]:
    if person is None:
        return "person_deleted"
    if person.status == LeadStatus.UNSUBSCRIBED:
        return "unsubscribed"
    if person.status == LeadStatus.DO_NOT_CONTACT:
        return "do_not_contact"
    if person.status == LeadStatus.BOUNCED:
        return "bounced"
    if person.status == LeadStatus.REPLIED and campaign.stop_on_reply:
        return "replied"
    return None


def _handle_interrupted_send(db: Session, campaign: Campaign, lead: CampaignLead) -> bool:
    """A SENDING row seen at the start of a cycle is left over from a crash mid-send. Returns True if the lead was stopped."""
    stuck = (
        db.query(EmailLog)
        .filter(
            EmailLog.campaign_id == campaign.id,
            EmailLog.person_id == lead.person_id,
            EmailLog.status == EmailStatus.SENDING,
        )
        .all()
    )
    if not stuck:
        return False
    for log in stuck:
        log.status = EmailStatus.FAILED
        log.error_message = "Interrupted mid-send - delivery unknown"
    _stop_lead(lead, "send_interrupted")
    db.commit()
    logger.warning("campaign.send_interrupted", campaign_id=campaign.id, person_id=lead.person_id)
    return True


def _pick_inbox(previous: Optional[EmailLog], pool: dict, available: dict) -> Optional[Inbox]:
    """
    Follow-ups go from the inbox that sent the earlier steps, so the lead sees
    one consistent sender in one thread. If that inbox is just busy or out of
    quota right now, wait for it; only if it has left the campaign (or been
    disconnected) does the lead move to another inbox.
    """
    if previous and previous.inbox_id in pool:
        return available.get(previous.inbox_id)
    if not available:
        return None
    return max(available.values(), key=_remaining_capacity)


async def _process_lead(
    db: Session,
    campaign: Campaign,
    lead: CampaignLead,
    steps: list,
    pool: dict,
    available: dict,
    now: datetime,
) -> tuple:
    """Returns (outcome, inbox_id_used). outcome: sent, failed, stopped, completed, deferred, waiting."""
    person = lead.person
    reason = _stop_reason_for(person, campaign)
    if reason:
        _stop_lead(lead, reason)
        db.commit()
        return "stopped", None

    if (lead.current_step or 0) >= len(steps):
        _complete_lead(lead)
        db.commit()
        return "completed", None

    if _handle_interrupted_send(db, campaign, lead):
        return "stopped", None

    step = steps[lead.current_step or 0]
    previous = (
        db.query(EmailLog)
        .filter(
            EmailLog.campaign_id == campaign.id,
            EmailLog.person_id == person.id,
            EmailLog.status.in_(DELIVERED_STATUSES),
        )
        .order_by(EmailLog.sent_at.desc())
        .first()
    )

    inbox = _pick_inbox(previous, pool, available)
    if inbox is None:
        return "waiting", None

    variables = build_variables(person, inbox)
    subject, missing_subject = render_template(step.subject, variables)
    body, missing_body = render_template(step.body, variables)
    missing = list(dict.fromkeys(missing_subject + missing_body))
    if missing:
        # Better to skip the lead than send "Hi ," - use {{var|fallback}} in the template to allow blanks.
        _stop_lead(lead, f"missing_variable:{','.join(missing)}")
        db.commit()
        return "stopped", None

    # A follow-up with a blank subject (or the same subject) replies in the earlier thread.
    thread_id = None
    in_same_thread = previous and previous.inbox_id == inbox.id and previous.gmail_thread_id
    if in_same_thread and (not subject.strip() or _strip_reply_prefix(subject) == _strip_reply_prefix(previous.subject)):
        subject = _reply_subject(previous.subject)
        thread_id = previous.gmail_thread_id
    elif not subject.strip():
        # No earlier thread to join from this inbox - fall back to the first step's subject.
        subject, _ = render_template(steps[0].subject, variables)

    if step.use_gpt:
        result = await personalize_with_gpt(subject, body, person, step.gpt_prompt)
        if "error" in result:
            lead.next_send_at = now + GPT_RETRY_DELAY
            db.commit()
            return "deferred", None
        body = result["body"]
        if not thread_id:  # a threaded reply must keep its "Re:" subject
            subject = result["subject"]

    log = EmailLog(
        inbox_id=inbox.id,
        person_id=person.id,
        campaign_id=campaign.id,
        sequence_step_id=step.id,
        email_type=EmailType.CAMPAIGN,
        to_email=person.email,
        from_email=inbox.email_address,
        subject=subject,
        body=body,
        status=EmailStatus.SENDING,
    )
    db.add(log)
    db.commit()

    try:
        gmail = GmailService(
            access_token=inbox.access_token,
            refresh_token=inbox.refresh_token,
            token_expiry=inbox.token_expiry,
        )
        sent = await asyncio.to_thread(
            gmail.send_email,
            to=person.email,
            subject=subject,
            body=body,
            from_name=inbox.display_name,
            thread_id=thread_id,
        )
        _sync_tokens(inbox, gmail)
    except Exception as exc:
        log.status = EmailStatus.FAILED
        log.error_message = str(exc)
        db.commit()
        attempts = (
            db.query(EmailLog)
            .filter(
                EmailLog.campaign_id == campaign.id,
                EmailLog.person_id == person.id,
                EmailLog.sequence_step_id == step.id,
                EmailLog.status == EmailStatus.FAILED,
            )
            .count()
        )
        log.retry_count = attempts - 1
        if attempts >= MAX_SEND_ATTEMPTS:
            _stop_lead(lead, "send_failed")
        else:
            lead.next_send_at = now + SEND_RETRY_DELAY
        db.commit()
        logger.warning("campaign.send_failed", campaign_id=campaign.id, to=person.email, attempt=attempts, error=str(exc))
        return "failed", inbox.id

    log.status = EmailStatus.SENT
    log.sent_at = datetime.utcnow()
    log.gmail_message_id = sent["message_id"]
    log.gmail_thread_id = sent["thread_id"]
    inbox.emails_sent_today = (inbox.emails_sent_today or 0) + 1
    campaign.emails_sent = (campaign.emails_sent or 0) + 1
    if person.status == LeadStatus.NEW:
        person.status = LeadStatus.CONTACTED
    _advance_lead(lead, steps, now)
    db.commit()
    logger.info("campaign.email_sent", campaign_id=campaign.id, to=person.email, step=lead.current_step, inbox=inbox.email_address)
    return "sent", inbox.id


def _maybe_complete(db: Session, campaign: Campaign, now: datetime) -> bool:
    remaining = (
        db.query(CampaignLead)
        .filter(CampaignLead.campaign_id == campaign.id, CampaignLead.status.in_(ACTIVE_LEAD_STATUSES))
        .count()
    )
    if remaining == 0 and campaign.status == CampaignStatus.ACTIVE:
        campaign.status = CampaignStatus.COMPLETED
        campaign.completed_at = now
        db.commit()
        logger.info("campaign.completed", campaign_id=campaign.id)
        return True
    return False


def _schedule_break(campaign: Campaign, now: datetime) -> bool:
    """After a send, set when this campaign may send next. Returns False when pacing is off (0/0)."""
    low = max(0, campaign.min_gap_minutes or 0)
    high = max(low, campaign.max_gap_minutes or 0)
    if high <= 0:
        return False
    campaign.next_send_after = now + timedelta(minutes=random.uniform(low, high))
    return True


async def _process_campaign(db: Session, campaign: Campaign, now: datetime, busy_inbox_ids: set, summary: dict) -> None:
    steps = ordered_steps(campaign)
    if not steps:
        return

    # Leads added since the last cycle (or before start) join the sequence at step 0.
    pending = (
        db.query(CampaignLead)
        .filter(CampaignLead.campaign_id == campaign.id, CampaignLead.status == CampaignLeadStatus.PENDING)
        .all()
    )
    for lead in pending:
        lead.status = CampaignLeadStatus.IN_PROGRESS
        lead.current_step = 0
        lead.next_send_at = now + _step_delay(steps[0])
    if pending:
        db.commit()
        summary["activated"] += len(pending)

    if not in_send_window(campaign, now):
        return

    # Taking a break between emails (see Campaign.min/max_gap_minutes).
    if campaign.next_send_after and now < campaign.next_send_after:
        return

    pool = {ci.inbox.id: ci.inbox for ci in campaign.campaign_inboxes if ci.inbox and _inbox_connected(ci.inbox)}
    for inbox in pool.values():
        _reset_daily_counter(inbox, now)
    db.commit()

    available = {
        inbox_id: inbox
        for inbox_id, inbox in pool.items()
        if inbox_id not in busy_inbox_ids and _remaining_capacity(inbox) > 0 and _past_send_gap(db, inbox, now)
    }
    if not available:
        return

    due = (
        db.query(CampaignLead)
        .filter(
            CampaignLead.campaign_id == campaign.id,
            CampaignLead.status == CampaignLeadStatus.IN_PROGRESS,
            CampaignLead.next_send_at <= now,
        )
        .order_by(CampaignLead.next_send_at)
        .limit(max(50, len(available) * 10))
        .all()
    )

    for lead in due:
        if not available:
            break
        outcome, inbox_id = await _process_lead(db, campaign, lead, steps, pool, available, now)
        summary[outcome] += 1
        if inbox_id is not None:
            available.pop(inbox_id, None)
            busy_inbox_ids.add(inbox_id)
        if outcome == "sent" and _schedule_break(campaign, now):
            db.commit()
            break  # one email, then a pause before the next


_engine_lock = asyncio.Lock()


async def run_campaign_cycle(db: Session) -> dict:
    """One pass over every active campaign. At most one send per inbox per pass, across all campaigns."""
    async with _engine_lock:
        now = datetime.utcnow()
        summary = defaultdict(int)
        busy_inbox_ids: set = set()
        completed = []

        campaigns = db.query(Campaign).filter(Campaign.status == CampaignStatus.ACTIVE).all()
        random.shuffle(campaigns)  # campaigns sharing inboxes take turns getting first pick

        for campaign in campaigns:
            try:
                await _process_campaign(db, campaign, now, busy_inbox_ids, summary)
                if _maybe_complete(db, campaign, now):
                    completed.append(campaign.id)
            except Exception as exc:
                db.rollback()
                logger.error("campaign.cycle_error", campaign_id=campaign.id, error=str(exc))
                summary["errors"] += 1

        return {"campaigns_checked": len(campaigns), "completed_campaigns": completed, **summary}


# ---------------------------------------------------------------------------
# Reply & bounce detection
# ---------------------------------------------------------------------------

_BOUNCE_SENDERS = ("mailer-daemon", "postmaster")
_BOUNCE_SUBJECTS = ("delivery status notification", "undeliverable", "undelivered mail", "mail delivery failed")
_AUTO_REPLY_SUBJECTS = ("automatic reply", "auto-reply", "autoreply", "out of office", "out of the office")


def _classify_thread(messages: list, our_address: str) -> Optional[tuple]:
    """Returns ("replied" | "bounced", message) for the first real response in the thread, or None."""
    our_address = our_address.lower()
    for msg in messages:
        sender = parseaddr(msg.get("from", ""))[1].lower()
        if not sender or sender == our_address:
            continue
        subject = (msg.get("subject") or "").lower()
        if sender.split("@")[0] in _BOUNCE_SENDERS or any(s in subject for s in _BOUNCE_SUBJECTS):
            return "bounced", msg
        if any(subject.startswith(s) for s in _AUTO_REPLY_SUBJECTS):
            continue  # out-of-office isn't a reply - keep the sequence going
        return "replied", msg
    return None


def _message_time(msg: dict) -> datetime:
    try:
        return datetime.utcfromtimestamp(int(msg["internal_date"]) / 1000)
    except (KeyError, TypeError, ValueError):
        return datetime.utcnow()


def record_thread_event(db: Session, log: EmailLog, event: str, msg: dict) -> None:
    campaign = db.get(Campaign, log.campaign_id)
    person = log.person
    lead = (
        db.query(CampaignLead)
        .filter(CampaignLead.campaign_id == log.campaign_id, CampaignLead.person_id == log.person_id)
        .first()
    )
    at = _message_time(msg)
    lead_is_active = lead is not None and lead.status in ACTIVE_LEAD_STATUSES

    if event == "replied":
        log.status = EmailStatus.REPLIED
        log.replied_at = at
        if campaign:
            campaign.replies_received = (campaign.replies_received or 0) + 1
        if person and person.status in (LeadStatus.NEW, LeadStatus.CONTACTED):
            person.status = LeadStatus.REPLIED
        if lead_is_active and campaign and campaign.stop_on_reply:
            _stop_lead(lead, "replied")
    else:
        log.status = EmailStatus.BOUNCED
        log.bounced_at = at
        if campaign:
            campaign.bounces = (campaign.bounces or 0) + 1
        if person and person.status not in (LeadStatus.CONVERTED, LeadStatus.DO_NOT_CONTACT):
            person.status = LeadStatus.BOUNCED
        if lead_is_active:
            _stop_lead(lead, "bounced")


async def check_replies(db: Session) -> dict:
    """Scan recent campaign threads for replies and bounces, and stop those leads' sequences."""
    async with _engine_lock:
        since = datetime.utcnow() - timedelta(days=REPLY_LOOKBACK_DAYS)
        summary = {"threads_checked": 0, "replies": 0, "bounces": 0, "errors": []}

        # A thread that already produced a reply/bounce is settled - don't count it twice.
        settled = {
            thread_id
            for (thread_id,) in db.query(EmailLog.gmail_thread_id).filter(
                EmailLog.email_type == EmailType.CAMPAIGN,
                EmailLog.status.in_((EmailStatus.REPLIED, EmailStatus.BOUNCED)),
                EmailLog.sent_at >= since,
            )
        }
        logs = (
            db.query(EmailLog)
            .filter(
                EmailLog.email_type == EmailType.CAMPAIGN,
                EmailLog.status == EmailStatus.SENT,
                EmailLog.gmail_thread_id.isnot(None),
                EmailLog.sent_at >= since,
            )
            .order_by(EmailLog.sent_at.desc())
            .all()
        )

        # Latest send per thread, grouped by the inbox that owns the thread.
        threads_by_inbox = defaultdict(dict)
        for log in logs:
            if log.gmail_thread_id in settled:
                continue
            threads_by_inbox[log.inbox_id].setdefault(log.gmail_thread_id, log)

        for inbox_id, threads in threads_by_inbox.items():
            inbox = db.get(Inbox, inbox_id)
            if not inbox or not _inbox_connected(inbox):
                continue
            try:
                gmail = GmailService(inbox.access_token, inbox.refresh_token, inbox.token_expiry)
            except Exception as exc:
                summary["errors"].append({"inbox": inbox.email_address, "error": str(exc)})
                continue

            for thread_id, log in list(threads.items())[:MAX_THREADS_CHECKED_PER_INBOX]:
                try:
                    messages = await asyncio.to_thread(gmail.get_thread, thread_id)
                except Exception as exc:
                    summary["errors"].append({"inbox": inbox.email_address, "thread_id": thread_id, "error": str(exc)})
                    continue
                summary["threads_checked"] += 1
                found = _classify_thread(messages, inbox.email_address)
                if found:
                    event, msg = found
                    record_thread_event(db, log, event, msg)
                    summary["replies" if event == "replied" else "bounces"] += 1
                    logger.info(f"campaign.{event}", campaign_id=log.campaign_id, person=log.to_email)

            _sync_tokens(inbox, gmail)
            db.commit()

        return summary


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def get_campaign_stats(db: Session, campaign: Campaign) -> dict:
    lead_counts = dict(
        db.query(CampaignLead.status, func.count(CampaignLead.id))
        .filter(CampaignLead.campaign_id == campaign.id)
        .group_by(CampaignLead.status)
        .all()
    )
    stop_reasons = dict(
        db.query(CampaignLead.stop_reason, func.count(CampaignLead.id))
        .filter(CampaignLead.campaign_id == campaign.id, CampaignLead.status == CampaignLeadStatus.STOPPED)
        .group_by(CampaignLead.stop_reason)
        .all()
    )
    sent_statuses = DELIVERED_STATUSES + (EmailStatus.BOUNCED,)
    per_step = defaultdict(lambda: defaultdict(int))
    for step_id, status, count in (
        db.query(EmailLog.sequence_step_id, EmailLog.status, func.count(EmailLog.id))
        .filter(EmailLog.campaign_id == campaign.id, EmailLog.email_type == EmailType.CAMPAIGN)
        .group_by(EmailLog.sequence_step_id, EmailLog.status)
        .all()
    ):
        per_step[step_id][status.value] = count
        if status in sent_statuses:
            per_step[step_id]["total_sent"] += count

    now = datetime.utcnow()
    start_of_today = datetime(now.year, now.month, now.day)
    sent_today = (
        db.query(EmailLog)
        .filter(
            EmailLog.campaign_id == campaign.id,
            EmailLog.email_type == EmailType.CAMPAIGN,
            EmailLog.sent_at >= start_of_today,
        )
        .count()
    )
    next_send_at = (
        db.query(func.min(CampaignLead.next_send_at))
        .filter(CampaignLead.campaign_id == campaign.id, CampaignLead.status == CampaignLeadStatus.IN_PROGRESS)
        .scalar()
    )

    contacted = (
        db.query(func.count(func.distinct(EmailLog.person_id)))
        .filter(EmailLog.campaign_id == campaign.id, EmailLog.status.in_(sent_statuses))
        .scalar()
    ) or 0
    replies = campaign.replies_received or 0
    bounces = campaign.bounces or 0

    try:
        window_open = in_send_window(campaign, now)
    except Exception:
        window_open = False

    return {
        "leads": {status.value: lead_counts.get(status, 0) for status in CampaignLeadStatus},
        "stop_reasons": {reason or "unknown": count for reason, count in stop_reasons.items()},
        "emails_sent": campaign.emails_sent or 0,
        "sent_today": sent_today,
        "leads_contacted": contacted,
        "replies": replies,
        "bounces": bounces,
        "reply_rate": round(replies / contacted * 100, 2) if contacted else 0,
        "bounce_rate": round(bounces / contacted * 100, 2) if contacted else 0,
        "steps": [
            {"step_index": index, "step_id": step.id, "subject": step.subject, **per_step.get(step.id, {"total_sent": 0})}
            for index, step in enumerate(ordered_steps(campaign))
        ],
        "next_send_at": next_send_at.isoformat() if next_send_at else None,
        "in_send_window": window_open,
    }


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

_scheduler_task: Optional[asyncio.Task] = None


async def _scheduler_loop(interval_seconds: int, reply_interval_seconds: int):
    from app.tenancy import current_owner_id, run_per_owner

    async def cycle(db, check_for_replies: bool):
        # One account's workspace at a time (see app/tenancy.py)
        owner = current_owner_id.get()
        result = await run_campaign_cycle(db)
        if result.get("sent") or result.get("failed") or result.get("activated") or result["completed_campaigns"]:
            logger.info("campaign.cycle_complete", owner_id=owner, **result)
        if check_for_replies:
            replies = await check_replies(db)
            if replies["replies"] or replies["bounces"] or replies["errors"]:
                logger.info("campaign.reply_check_complete", owner_id=owner, **replies)

    last_reply_check = 0.0
    while True:
        try:
            check_for_replies = time.monotonic() - last_reply_check >= reply_interval_seconds
            if check_for_replies:
                last_reply_check = time.monotonic()
            await run_per_owner(cycle, check_for_replies)
        except Exception as exc:
            logger.error("campaign.scheduler_failed", error=str(exc))

        await asyncio.sleep(interval_seconds)


def start_campaign_scheduler(
    interval_seconds: int = CYCLE_INTERVAL_SECONDS,
    reply_interval_seconds: int = REPLY_CHECK_INTERVAL_SECONDS,
):
    global _scheduler_task
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(_scheduler_loop(interval_seconds, reply_interval_seconds))
        logger.info("campaign.scheduler_started", interval_seconds=interval_seconds)


def stop_campaign_scheduler():
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        logger.info("campaign.scheduler_stopped")
