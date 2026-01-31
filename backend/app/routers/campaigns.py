from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel
from datetime import datetime

from app.database import get_db
from app.models import Campaign, CampaignStatus, CampaignLead, CampaignInbox

router = APIRouter()


class CampaignCreate(BaseModel):
    name: str
    description: Optional[str] = None
    sequence_id: Optional[int] = None
    send_start_time: str = "09:00"
    send_end_time: str = "17:00"
    timezone: str = "America/New_York"
    send_on_weekends: bool = False
    stop_on_reply: bool = True


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    sequence_id: Optional[int] = None
    send_start_time: Optional[str] = None
    send_end_time: Optional[str] = None
    timezone: Optional[str] = None
    send_on_weekends: Optional[bool] = None
    stop_on_reply: Optional[bool] = None


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
                "total_leads": c.total_leads,
                "emails_sent": c.emails_sent,
                "replies_received": c.replies_received,
                "bounces": c.bounces,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "started_at": c.started_at.isoformat() if c.started_at else None,
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
    db_campaign = Campaign(
        name=campaign.name,
        description=campaign.description,
        sequence_id=campaign.sequence_id,
        send_start_time=campaign.send_start_time,
        send_end_time=campaign.send_end_time,
        timezone=campaign.timezone,
        send_on_weekends=campaign.send_on_weekends,
        stop_on_reply=campaign.stop_on_reply,
        status=CampaignStatus.DRAFT,
    )
    db.add(db_campaign)
    db.commit()
    db.refresh(db_campaign)
    return {"id": db_campaign.id, "message": "Campaign created"}


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    """Get campaign details."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    return {
        "id": campaign.id,
        "name": campaign.name,
        "description": campaign.description,
        "status": campaign.status.value if campaign.status else None,
        "sequence_id": campaign.sequence_id,
        "send_start_time": campaign.send_start_time,
        "send_end_time": campaign.send_end_time,
        "timezone": campaign.timezone,
        "send_on_weekends": campaign.send_on_weekends,
        "stop_on_reply": campaign.stop_on_reply,
        "total_leads": campaign.total_leads,
        "emails_sent": campaign.emails_sent,
        "replies_received": campaign.replies_received,
        "bounces": campaign.bounces,
        "inbox_ids": [ci.inbox_id for ci in campaign.campaign_inboxes],
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        "started_at": campaign.started_at.isoformat() if campaign.started_at else None,
    }


@router.put("/{campaign_id}")
async def update_campaign(
    campaign_id: int,
    update: CampaignUpdate,
    db: Session = Depends(get_db)
):
    """Update campaign settings."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    update_data = update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(campaign, field, value)

    db.commit()
    return {"message": "Campaign updated"}


@router.delete("/{campaign_id}")
async def delete_campaign(campaign_id: int, db: Session = Depends(get_db)):
    """Delete a campaign."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    db.delete(campaign)
    db.commit()
    return {"message": "Campaign deleted"}


@router.post("/{campaign_id}/start")
async def start_campaign(campaign_id: int, db: Session = Depends(get_db)):
    """Start/activate a campaign."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign.status == CampaignStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Campaign is already active")

    if not campaign.sequence_id:
        raise HTTPException(status_code=400, detail="Campaign has no sequence assigned")

    if not campaign.campaign_inboxes:
        raise HTTPException(status_code=400, detail="Campaign has no inboxes assigned")

    if not campaign.campaign_leads:
        raise HTTPException(status_code=400, detail="Campaign has no leads assigned")

    campaign.status = CampaignStatus.ACTIVE
    campaign.started_at = datetime.utcnow()
    db.commit()

    # TODO: Populate send queue
    return {"message": "Campaign started"}


@router.post("/{campaign_id}/pause")
async def pause_campaign(campaign_id: int, db: Session = Depends(get_db)):
    """Pause a campaign."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    campaign.status = CampaignStatus.PAUSED
    db.commit()
    return {"message": "Campaign paused"}


@router.post("/{campaign_id}/resume")
async def resume_campaign(campaign_id: int, db: Session = Depends(get_db)):
    """Resume a paused campaign."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign.status != CampaignStatus.PAUSED:
        raise HTTPException(status_code=400, detail="Campaign is not paused")

    campaign.status = CampaignStatus.ACTIVE
    db.commit()
    return {"message": "Campaign resumed"}


@router.get("/{campaign_id}/leads")
async def get_campaign_leads(
    campaign_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Get leads assigned to a campaign."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    query = db.query(CampaignLead).filter(CampaignLead.campaign_id == campaign_id)
    total = query.count()
    leads = query.offset(skip).limit(limit).all()

    return {
        "leads": [
            {
                "id": cl.id,
                "person_id": cl.person_id,
                "email": cl.person.email if cl.person else None,
                "name": cl.person.full_name or f"{cl.person.first_name} {cl.person.last_name}" if cl.person else None,
                "current_step": cl.current_step,
                "status": cl.status.value if cl.status else None,
                "next_send_at": cl.next_send_at.isoformat() if cl.next_send_at else None,
            }
            for cl in leads
        ],
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.post("/{campaign_id}/leads")
async def add_leads_to_campaign(
    campaign_id: int,
    person_ids: list[int],
    db: Session = Depends(get_db)
):
    """Add leads to a campaign."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    added = 0
    for person_id in person_ids:
        existing = db.query(CampaignLead).filter(
            CampaignLead.campaign_id == campaign_id,
            CampaignLead.person_id == person_id
        ).first()
        if not existing:
            cl = CampaignLead(campaign_id=campaign_id, person_id=person_id)
            db.add(cl)
            added += 1

    campaign.total_leads = db.query(CampaignLead).filter(
        CampaignLead.campaign_id == campaign_id
    ).count() + added

    db.commit()
    return {"message": f"Added {added} leads to campaign"}


@router.post("/{campaign_id}/inboxes")
async def assign_inboxes(
    campaign_id: int,
    inbox_ids: list[int],
    db: Session = Depends(get_db)
):
    """Assign inboxes to a campaign."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Remove existing assignments
    db.query(CampaignInbox).filter(CampaignInbox.campaign_id == campaign_id).delete()

    # Add new assignments
    for inbox_id in inbox_ids:
        ci = CampaignInbox(campaign_id=campaign_id, inbox_id=inbox_id)
        db.add(ci)

    db.commit()
    return {"message": f"Assigned {len(inbox_ids)} inboxes to campaign"}
