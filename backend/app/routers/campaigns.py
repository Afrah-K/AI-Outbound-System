from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.database import get_db
from app.models import (
    Campaign,
    CampaignStatus,
    CampaignLead,
    CampaignLeadStatus,
    CampaignInbox,
    EmailLog,
    EmailType,
    Inbox,
    LeadList,
    LeadListMember,
    LeadStatus,
    Person,
)
from app.services import campaign_engine
from app.services.lead_import import LeadImportError, import_leads_csv, is_csv_filename

router = APIRouter()

# Prospects in these states are never added to a campaign.
UNCONTACTABLE_STATUSES = (LeadStatus.UNSUBSCRIBED, LeadStatus.DO_NOT_CONTACT, LeadStatus.BOUNCED)


def _check_hhmm(value: Optional[str]) -> Optional[str]:
    if value is not None:
        try:
            datetime.strptime(value, "%H:%M")
        except ValueError:
            raise ValueError("must be a time in HH:MM format")
    return value


def _check_timezone(value: Optional[str]) -> Optional[str]:
    if value is not None:
        try:
            ZoneInfo(value)
        except Exception:
            raise ValueError(f"unknown timezone '{value}'")
    return value


class CampaignCreate(BaseModel):
    name: str
    description: Optional[str] = None
    sequence_id: Optional[int] = None
    send_start_time: str = "09:00"
    send_end_time: str = "17:00"
    timezone: str = "America/New_York"
    send_on_weekends: bool = False
    stop_on_reply: bool = True
    # Random pause between this campaign's emails, in minutes (0/0 = no pause)
    min_gap_minutes: int = Field(2, ge=0, le=240)
    max_gap_minutes: int = Field(5, ge=0, le=240)

    _valid_times = field_validator("send_start_time", "send_end_time")(_check_hhmm)
    _valid_timezone = field_validator("timezone")(_check_timezone)

    @model_validator(mode="after")
    def _gaps_in_order(self):
        _check_gap_order(self.min_gap_minutes, self.max_gap_minutes)
        return self


def _check_gap_order(low: Optional[int], high: Optional[int]) -> None:
    if low is not None and high is not None and low > high:
        raise ValueError("min_gap_minutes can't be more than max_gap_minutes")


class CampaignUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    sequence_id: Optional[int] = None
    send_start_time: Optional[str] = None
    send_end_time: Optional[str] = None
    timezone: Optional[str] = None
    send_on_weekends: Optional[bool] = None
    stop_on_reply: Optional[bool] = None
    min_gap_minutes: Optional[int] = Field(None, ge=0, le=240)
    max_gap_minutes: Optional[int] = Field(None, ge=0, le=240)

    _valid_times = field_validator("send_start_time", "send_end_time")(_check_hhmm)
    _valid_timezone = field_validator("timezone")(_check_timezone)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value):
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Campaign name can't be empty")
        return value


def _get_campaign_or_404(db: Session, campaign_id: int) -> Campaign:
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


def _check_sequence_exists(db: Session, sequence_id: Optional[int]) -> None:
    from app.models import Sequence

    if sequence_id is not None and not db.query(Sequence).filter(Sequence.id == sequence_id).first():
        raise HTTPException(status_code=400, detail=f"Sequence {sequence_id} not found")


def _refresh_total_leads(db: Session, campaign: Campaign) -> None:
    db.flush()
    campaign.total_leads = db.query(CampaignLead).filter(CampaignLead.campaign_id == campaign.id).count()


def _person_name(person: Optional[Person]) -> Optional[str]:
    if not person:
        return None
    return person.full_name or " ".join(p for p in (person.first_name, person.last_name) if p) or None


@router.get("")
async def list_campaigns(
    status: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """List all campaigns."""
    query = db.query(Campaign)
    if status:
        try:
            status_enum = CampaignStatus(status)
            query = query.filter(Campaign.status == status_enum)
        except ValueError:
            pass

    total = query.count()
    campaigns = query.order_by(Campaign.created_at.desc()).offset(skip).limit(limit).all()

    return {
        "campaigns": [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "status": c.status.value if c.status else None,
                "sequence_id": c.sequence_id,
                "sequence_name": c.sequence.name if c.sequence else None,
                "total_leads": c.total_leads,
                "emails_sent": c.emails_sent,
                "replies_received": c.replies_received,
                "bounces": c.bounces,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "started_at": c.started_at.isoformat() if c.started_at else None,
                "completed_at": c.completed_at.isoformat() if c.completed_at else None,
                "sending": campaign_engine.describe_sending_state(db, c),
            }
            for c in campaigns
        ],
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.post("")
async def create_campaign(campaign: CampaignCreate, db: Session = Depends(get_db)):
    """Create a new campaign."""
    _check_sequence_exists(db, campaign.sequence_id)
    db_campaign = Campaign(
        name=campaign.name,
        description=campaign.description,
        sequence_id=campaign.sequence_id,
        send_start_time=campaign.send_start_time,
        send_end_time=campaign.send_end_time,
        timezone=campaign.timezone,
        send_on_weekends=campaign.send_on_weekends,
        stop_on_reply=campaign.stop_on_reply,
        min_gap_minutes=campaign.min_gap_minutes,
        max_gap_minutes=campaign.max_gap_minutes,
        status=CampaignStatus.DRAFT,
    )
    db.add(db_campaign)
    db.commit()
    db.refresh(db_campaign)
    return {"id": db_campaign.id, "message": "Campaign created"}


# Declared before /{campaign_id} routes so these literal paths aren't parsed as an id.
@router.post("/run-cycle")
async def run_cycle_now(db: Session = Depends(get_db)):
    """Manually trigger one sending pass immediately, instead of waiting for the scheduler."""
    return await campaign_engine.run_campaign_cycle(db)


@router.post("/check-replies")
async def check_replies_now(db: Session = Depends(get_db)):
    """Manually scan recent campaign threads for replies and bounces."""
    return await campaign_engine.check_replies(db)


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    """Get campaign details."""
    campaign = _get_campaign_or_404(db, campaign_id)

    try:
        window_open = campaign_engine.in_send_window(campaign)
    except Exception:
        window_open = False

    return {
        "id": campaign.id,
        "name": campaign.name,
        "description": campaign.description,
        "status": campaign.status.value if campaign.status else None,
        "sequence_id": campaign.sequence_id,
        "sequence_name": campaign.sequence.name if campaign.sequence else None,
        "step_count": len(campaign.sequence.steps) if campaign.sequence else 0,
        "send_start_time": campaign.send_start_time,
        "send_end_time": campaign.send_end_time,
        "timezone": campaign.timezone,
        "send_on_weekends": campaign.send_on_weekends,
        "stop_on_reply": campaign.stop_on_reply,
        "min_gap_minutes": campaign.min_gap_minutes if campaign.min_gap_minutes is not None else 2,
        "max_gap_minutes": campaign.max_gap_minutes if campaign.max_gap_minutes is not None else 5,
        "next_send_after": campaign.next_send_after.isoformat() if campaign.next_send_after else None,
        "total_leads": campaign.total_leads,
        "emails_sent": campaign.emails_sent,
        "replies_received": campaign.replies_received,
        "bounces": campaign.bounces,
        "inbox_ids": [ci.inbox_id for ci in campaign.campaign_inboxes],
        "inboxes": [
            {
                "id": ci.inbox.id,
                "email_address": ci.inbox.email_address,
                "display_name": ci.inbox.display_name,
                "is_active": ci.inbox.is_active,
                "connected": bool(ci.inbox.access_token and ci.inbox.refresh_token),
                "daily_limit": ci.inbox.daily_limit,
                "emails_sent_today": ci.inbox.emails_sent_today,
            }
            for ci in campaign.campaign_inboxes
            if ci.inbox
        ],
        "in_send_window": window_open,
        "sending": campaign_engine.describe_sending_state(db, campaign),
        "readiness_errors": campaign_engine.validate_campaign_ready(db, campaign)
        if campaign.status in (CampaignStatus.DRAFT, CampaignStatus.PAUSED)
        else [],
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        "started_at": campaign.started_at.isoformat() if campaign.started_at else None,
        "completed_at": campaign.completed_at.isoformat() if campaign.completed_at else None,
    }


@router.put("/{campaign_id}")
async def update_campaign(
    campaign_id: int,
    update: CampaignUpdate,
    db: Session = Depends(get_db)
):
    """Update campaign settings."""
    campaign = _get_campaign_or_404(db, campaign_id)

    update_data = update.model_dump(exclude_unset=True)
    if "sequence_id" in update_data and update_data["sequence_id"] != campaign.sequence_id:
        if campaign.status == CampaignStatus.ACTIVE:
            raise HTTPException(status_code=400, detail="Pause the campaign before changing its sequence")
        _check_sequence_exists(db, update_data["sequence_id"])

    try:
        _check_gap_order(
            update_data.get("min_gap_minutes", campaign.min_gap_minutes),
            update_data.get("max_gap_minutes", campaign.max_gap_minutes),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    for field, value in update_data.items():
        setattr(campaign, field, value)

    # A shorter pause takes effect now instead of after the old, longer one finishes.
    if campaign.next_send_after and "max_gap_minutes" in update_data:
        campaign.next_send_after = min(
            campaign.next_send_after,
            datetime.utcnow() + timedelta(minutes=campaign.max_gap_minutes or 0),
        )

    db.commit()
    return {"message": "Campaign updated"}


@router.delete("/{campaign_id}")
async def delete_campaign(campaign_id: int, db: Session = Depends(get_db)):
    """Delete a campaign. Its email history is kept in the email log."""
    campaign = _get_campaign_or_404(db, campaign_id)
    if campaign.status == CampaignStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Pause the campaign before deleting it")

    db.delete(campaign)
    db.commit()
    return {"message": "Campaign deleted"}


@router.post("/{campaign_id}/start")
async def start_campaign(campaign_id: int, db: Session = Depends(get_db)):
    """
    Start/activate a campaign. The scheduler picks up its leads on the next
    cycle and sends within the campaign's send window.
    """
    campaign = _get_campaign_or_404(db, campaign_id)

    if campaign.status == CampaignStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Campaign is already active")
    if campaign.status == CampaignStatus.PAUSED:
        raise HTTPException(status_code=400, detail="Campaign is paused - use resume instead")
    if campaign.status == CampaignStatus.ARCHIVED:
        raise HTTPException(status_code=400, detail="Campaign is archived")

    errors = campaign_engine.validate_campaign_ready(db, campaign)
    if errors:
        raise HTTPException(status_code=400, detail={"message": "Campaign is not ready to start", "errors": errors})

    campaign.status = CampaignStatus.ACTIVE
    campaign.next_send_after = None  # first email goes out on the next cycle
    if not campaign.started_at:
        campaign.started_at = datetime.utcnow()
    campaign.completed_at = None
    db.commit()
    return {"message": "Campaign started", "in_send_window": campaign_engine.in_send_window(campaign)}


@router.post("/{campaign_id}/pause")
async def pause_campaign(campaign_id: int, db: Session = Depends(get_db)):
    """Pause a campaign. Leads keep their place in the sequence."""
    campaign = _get_campaign_or_404(db, campaign_id)
    if campaign.status != CampaignStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Only an active campaign can be paused")

    campaign.status = CampaignStatus.PAUSED
    db.commit()
    return {"message": "Campaign paused"}


@router.post("/{campaign_id}/resume")
async def resume_campaign(campaign_id: int, db: Session = Depends(get_db)):
    """
    Resume a paused campaign. Follow-ups that came due while paused go out
    on the next cycles rather than being skipped.
    """
    campaign = _get_campaign_or_404(db, campaign_id)

    if campaign.status != CampaignStatus.PAUSED:
        raise HTTPException(status_code=400, detail="Campaign is not paused")

    errors = campaign_engine.validate_campaign_ready(db, campaign)
    if errors:
        raise HTTPException(status_code=400, detail={"message": "Campaign is not ready to resume", "errors": errors})

    campaign.status = CampaignStatus.ACTIVE
    db.commit()
    return {"message": "Campaign resumed"}


@router.post("/{campaign_id}/archive")
async def archive_campaign(campaign_id: int, db: Session = Depends(get_db)):
    """Archive a campaign - it stops sending permanently but keeps its history."""
    campaign = _get_campaign_or_404(db, campaign_id)
    campaign.status = CampaignStatus.ARCHIVED
    db.commit()
    return {"message": "Campaign archived"}


@router.get("/{campaign_id}/stats")
async def get_campaign_stats(campaign_id: int, db: Session = Depends(get_db)):
    """Lead status breakdown, per-step send counts, reply/bounce rates."""
    campaign = _get_campaign_or_404(db, campaign_id)
    return campaign_engine.get_campaign_stats(db, campaign)


@router.get("/{campaign_id}/activity")
async def get_campaign_activity(
    campaign_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """Emails this campaign has sent (or tried to), newest first."""
    _get_campaign_or_404(db, campaign_id)

    query = db.query(EmailLog).filter(
        EmailLog.campaign_id == campaign_id,
        EmailLog.email_type == EmailType.CAMPAIGN,
    )
    total = query.count()
    logs = query.order_by(EmailLog.queued_at.desc()).offset(skip).limit(limit).all()

    return {
        "activity": [
            {
                "id": log.id,
                "person_id": log.person_id,
                "to_email": log.to_email,
                "from_email": log.from_email,
                "sequence_step_id": log.sequence_step_id,
                "subject": log.subject,
                "body": log.body,
                "status": log.status.value if log.status else None,
                "error_message": log.error_message,
                "gmail_thread_id": log.gmail_thread_id,
                "inbox_id": log.inbox_id,
                "sent_at": log.sent_at.isoformat() if log.sent_at else None,
                "replied_at": log.replied_at.isoformat() if log.replied_at else None,
                "bounced_at": log.bounced_at.isoformat() if log.bounced_at else None,
            }
            for log in logs
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/{campaign_id}/preview")
async def preview_campaign_email(
    campaign_id: int,
    person_id: Optional[int] = None,
    step: int = Query(0, ge=0, description="Step index in the sequence (0 = first email)"),
    db: Session = Depends(get_db)
):
    """
    Render one step's template for one lead, exactly as the scheduler would
    (minus GPT personalization). Defaults to the campaign's first lead.
    """
    campaign = _get_campaign_or_404(db, campaign_id)
    steps = campaign_engine.ordered_steps(campaign)
    if not steps:
        raise HTTPException(status_code=400, detail="Campaign has no sequence steps")
    if step >= len(steps):
        raise HTTPException(status_code=400, detail=f"Sequence only has {len(steps)} steps")

    if person_id is None:
        first = db.query(CampaignLead).filter(CampaignLead.campaign_id == campaign_id).order_by(CampaignLead.id).first()
        if not first:
            raise HTTPException(status_code=400, detail="Campaign has no leads to preview with")
        person_id = first.person_id
    person = db.query(Person).filter(Person.id == person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    inbox = next((ci.inbox for ci in campaign.campaign_inboxes if ci.inbox), None)
    variables = campaign_engine.build_variables(person, inbox)
    target = steps[step]
    subject, missing_subject = campaign_engine.render_template(target.subject, variables)
    body, missing_body = campaign_engine.render_template(target.body, variables)

    return {
        "person_id": person.id,
        "to_email": person.email,
        "from_email": inbox.email_address if inbox else None,
        "step": step,
        "subject": subject or "(replies in the previous thread)",
        "body": body,
        "use_gpt": target.use_gpt,
        "missing_variables": list(dict.fromkeys(missing_subject + missing_body)),
        "unknown_variables": campaign_engine.find_unknown_variables(target.subject, target.body),
    }


@router.get("/{campaign_id}/leads")
async def get_campaign_leads(
    campaign_id: int,
    status: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Get leads assigned to a campaign."""
    _get_campaign_or_404(db, campaign_id)

    query = db.query(CampaignLead).filter(CampaignLead.campaign_id == campaign_id)
    if status:
        try:
            query = query.filter(CampaignLead.status == CampaignLeadStatus(status))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown lead status '{status}'")
    total = query.count()
    leads = query.order_by(CampaignLead.id).offset(skip).limit(limit).all()

    return {
        "leads": [
            {
                "id": cl.id,
                "person_id": cl.person_id,
                "email": cl.person.email if cl.person else None,
                "name": _person_name(cl.person),
                "company_name": cl.person.company.name if cl.person and cl.person.company else None,
                "current_step": cl.current_step,
                "status": cl.status.value if cl.status else None,
                "stop_reason": cl.stop_reason,
                "next_send_at": cl.next_send_at.isoformat() if cl.next_send_at else None,
            }
            for cl in leads
        ],
        "total": total,
        "skip": skip,
        "limit": limit
    }


def _add_people_to_campaign(db: Session, campaign: Campaign, person_ids: List[int]) -> dict:
    """
    Shared by every way of adding leads. Leads added to a running campaign
    start the sequence on the next cycle. Unknown, duplicate, and
    do-not-contact prospects are skipped. Commits.
    """
    if campaign.status == CampaignStatus.ARCHIVED:
        raise HTTPException(status_code=400, detail="Campaign is archived")

    requested = list(dict.fromkeys(person_ids))
    people = {p.id: p for p in db.query(Person).filter(Person.id.in_(requested)).all()} if requested else {}
    existing = {
        pid
        for (pid,) in db.query(CampaignLead.person_id).filter(
            CampaignLead.campaign_id == campaign.id,
            CampaignLead.person_id.in_(requested),
        )
    } if requested else set()

    added, skipped = 0, {"not_found": 0, "already_in_campaign": 0, "uncontactable": 0}
    for person_id in requested:
        person = people.get(person_id)
        if not person:
            skipped["not_found"] += 1
        elif person_id in existing:
            skipped["already_in_campaign"] += 1
        elif person.status in UNCONTACTABLE_STATUSES:
            skipped["uncontactable"] += 1
        else:
            db.add(CampaignLead(campaign_id=campaign.id, person_id=person_id))
            added += 1

    # A finished campaign that gets new leads picks back up.
    if added and campaign.status == CampaignStatus.COMPLETED:
        campaign.status = CampaignStatus.ACTIVE
        campaign.completed_at = None

    _refresh_total_leads(db, campaign)
    db.commit()
    return {"message": f"Added {added} leads to campaign", "added": added, "skipped": skipped}


@router.post("/{campaign_id}/leads")
async def add_leads_to_campaign(
    campaign_id: int,
    person_ids: List[int],
    db: Session = Depends(get_db)
):
    """Add specific prospects to a campaign by id."""
    campaign = _get_campaign_or_404(db, campaign_id)
    return _add_people_to_campaign(db, campaign, person_ids)


class AddFromListRequest(BaseModel):
    # An uploaded lead list's id, or null to add every prospect.
    list_id: Optional[int] = None


@router.post("/{campaign_id}/leads/from-list")
async def add_lead_list_to_campaign(
    campaign_id: int,
    payload: AddFromListRequest,
    db: Session = Depends(get_db)
):
    """Add everyone in an uploaded lead list to the campaign (or every prospect, when list_id is null)."""
    campaign = _get_campaign_or_404(db, campaign_id)

    if payload.list_id is None:
        person_ids = [pid for (pid,) in db.query(Person.id)]
    else:
        lead_list = db.query(LeadList).filter(LeadList.id == payload.list_id, LeadList.deleted_at.is_(None)).first()
        if not lead_list:
            raise HTTPException(status_code=404, detail="Lead list not found")
        person_ids = [
            pid for (pid,) in db.query(LeadListMember.person_id).filter(LeadListMember.lead_list_id == lead_list.id)
        ]

    return _add_people_to_campaign(db, campaign, person_ids)


@router.post("/{campaign_id}/leads/upload")
async def upload_leads_to_campaign(
    campaign_id: int,
    file: UploadFile = File(...),
    update_existing: bool = Query(True, description="Refresh existing prospects' details from the file"),
    db: Session = Depends(get_db)
):
    """
    Upload a CSV straight into the campaign: the rows are imported as
    prospects (saved as a lead list named after the file) and everyone in
    the file is added to this campaign.
    """
    campaign = _get_campaign_or_404(db, campaign_id)
    if campaign.status == CampaignStatus.ARCHIVED:
        raise HTTPException(status_code=400, detail="Campaign is archived")
    if not is_csv_filename(file.filename):
        raise HTTPException(status_code=400, detail="File must be a CSV (.csv, .tsv or .txt)")

    try:
        imported = import_leads_csv(db, await file.read(), file.filename, update_existing)
    except LeadImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not imported["person_ids"]:
        raise HTTPException(
            status_code=400,
            detail=imported["warnings"][0] if imported["warnings"] else "No rows with an email address found in the file",
        )

    result = _add_people_to_campaign(db, campaign, imported.pop("person_ids"))
    return {**result, "import": imported}


@router.delete("/{campaign_id}/leads/all")
async def remove_all_leads_from_campaign(campaign_id: int, db: Session = Depends(get_db)):
    """
    Remove every lead from the campaign ("Remove all"). The prospects stay in
    Prospects, and anything already sent stays in the email log.
    """
    campaign = _get_campaign_or_404(db, campaign_id)
    removed = db.query(CampaignLead).filter(CampaignLead.campaign_id == campaign_id).delete(synchronize_session=False)
    _refresh_total_leads(db, campaign)
    db.commit()
    return {"message": f"Removed {removed} leads from campaign", "removed": removed}


@router.delete("/{campaign_id}/leads")
async def remove_leads_from_campaign(
    campaign_id: int,
    person_ids: List[int],
    db: Session = Depends(get_db)
):
    """Remove leads from a campaign. Anything already sent stays in the email log."""
    campaign = _get_campaign_or_404(db, campaign_id)

    removed = db.query(CampaignLead).filter(
        CampaignLead.campaign_id == campaign_id,
        CampaignLead.person_id.in_(person_ids),
    ).delete(synchronize_session=False)

    _refresh_total_leads(db, campaign)
    db.commit()
    return {"message": f"Removed {removed} leads from campaign", "removed": removed}


@router.post("/{campaign_id}/leads/{person_id}/stop")
async def stop_campaign_lead(campaign_id: int, person_id: int, db: Session = Depends(get_db)):
    """Stop the sequence for one lead (e.g. they replied somewhere the system can't see)."""
    lead = db.query(CampaignLead).filter(
        CampaignLead.campaign_id == campaign_id,
        CampaignLead.person_id == person_id,
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead is not in this campaign")

    lead.status = CampaignLeadStatus.STOPPED
    lead.stop_reason = "manual"
    lead.next_send_at = None
    db.commit()
    return {"message": "Lead stopped"}


@router.post("/{campaign_id}/inboxes")
async def assign_inboxes(
    campaign_id: int,
    inbox_ids: List[int],
    db: Session = Depends(get_db)
):
    """Assign inboxes to a campaign, replacing the current pool."""
    _get_campaign_or_404(db, campaign_id)

    requested = list(dict.fromkeys(inbox_ids))
    found = {i.id for i in db.query(Inbox).filter(Inbox.id.in_(requested)).all()} if requested else set()
    missing = [i for i in requested if i not in found]
    if missing:
        raise HTTPException(status_code=400, detail=f"Inboxes not found: {missing}")

    db.query(CampaignInbox).filter(CampaignInbox.campaign_id == campaign_id).delete()
    for inbox_id in requested:
        db.add(CampaignInbox(campaign_id=campaign_id, inbox_id=inbox_id))

    db.commit()
    return {"message": f"Assigned {len(requested)} inboxes to campaign"}
