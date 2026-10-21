from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, Enum, Text, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from app.models.base import Base


class WarmupStage(enum.Enum):
    NOT_STARTED = "not_started"
    STAGE_1 = "stage_1"      # 5 emails/day
    STAGE_2 = "stage_2"      # 10 emails/day
    STAGE_3 = "stage_3"      # 20 emails/day
    COMPLETED = "completed"   # Ready for full volume


class Inbox(Base):
    __tablename__ = "inboxes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True)  # the account this belongs to
    email_address = Column(String(255), unique=True, nullable=False, index=True)
    domain = Column(String(255), nullable=False, index=True)
    display_name = Column(String(255))

    # OAuth credentials (encrypted in production)
    access_token = Column(Text)
    refresh_token = Column(String(512))
    token_expiry = Column(DateTime)

    # Sending limits
    daily_limit = Column(Integer, default=20)
    emails_sent_today = Column(Integer, default=0)
    last_reset_date = Column(DateTime, default=datetime.utcnow)

    # Warmup tracking
    warmup_stage = Column(Enum(WarmupStage), default=WarmupStage.NOT_STARTED)
    warmup_started_at = Column(DateTime)
    warmup_emails_sent = Column(Integer, default=0)

    # Health metrics
    health_score = Column(Float, default=100.0)  # 0-100 scale
    bounce_count_7d = Column(Integer, default=0)
    reply_count_7d = Column(Integer, default=0)
    emails_sent_7d = Column(Integer, default=0)
    spam_report_count = Column(Integer, default=0)

    # Status
    is_active = Column(Boolean, default=True)
    is_warmup_paused = Column(Boolean, default=False)
    pause_reason = Column(String(255))

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    # Deleting an inbox keeps its sent-email history (inbox_id becomes empty) and
    # removes it from campaigns' sending pools
    email_logs = relationship("EmailLog", back_populates="inbox")
    campaign_inboxes = relationship("CampaignInbox", back_populates="inbox", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Inbox {self.email_address}>"
