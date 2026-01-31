from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Enum, Text
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from app.models.base import Base


class CampaignStatus(enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)

    # Sequence assignment
    sequence_id = Column(Integer, ForeignKey("sequences.id"))

    # Status
    status = Column(Enum(CampaignStatus), default=CampaignStatus.DRAFT, index=True)

    # Scheduling
    send_start_time = Column(String(5), default="09:00")  # HH:MM format
    send_end_time = Column(String(5), default="17:00")
    timezone = Column(String(50), default="America/New_York")
    send_on_weekends = Column(Boolean, default=False)

    # Settings
    stop_on_reply = Column(Boolean, default=True)
    track_opens = Column(Boolean, default=False)
    track_clicks = Column(Boolean, default=False)

    # Stats (denormalized for quick access)
    total_leads = Column(Integer, default=0)
    emails_sent = Column(Integer, default=0)
    replies_received = Column(Integer, default=0)
    bounces = Column(Integer, default=0)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)

    # Relationships
    sequence = relationship("Sequence", back_populates="campaigns")
    campaign_leads = relationship("CampaignLead", back_populates="campaign", cascade="all, delete-orphan")
    campaign_inboxes = relationship("CampaignInbox", back_populates="campaign", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Campaign {self.name}>"


class CampaignInbox(Base):
    """Junction table for campaign-inbox pool."""
    __tablename__ = "campaign_inboxes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), index=True)
    inbox_id = Column(Integer, ForeignKey("inboxes.id"), index=True)

    campaign = relationship("Campaign", back_populates="campaign_inboxes")
    inbox = relationship("Inbox", back_populates="campaign_inboxes")


class CampaignLeadStatus(enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    STOPPED = "stopped"  # Stopped due to reply or bounce


class CampaignLead(Base):
    """Junction table for campaign leads with status tracking."""
    __tablename__ = "campaign_leads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), index=True)
    person_id = Column(Integer, ForeignKey("people.id"), index=True)

    current_step = Column(Integer, default=0)  # Which sequence step they're on
    status = Column(Enum(CampaignLeadStatus), default=CampaignLeadStatus.PENDING, index=True)
    next_send_at = Column(DateTime, index=True)
    stop_reason = Column(String(255))  # "replied", "bounced", "unsubscribed"

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    campaign = relationship("Campaign", back_populates="campaign_leads")
    person = relationship("Person", back_populates="campaign_leads")
