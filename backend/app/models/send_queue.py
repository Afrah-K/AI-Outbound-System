from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Enum
from datetime import datetime
import enum

from app.models.base import Base


class QueueStatus(enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class SendQueue(Base):
    """Queue for scheduled emails - ensures restart safety."""
    __tablename__ = "send_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Associations
    inbox_id = Column(Integer, ForeignKey("inboxes.id"), index=True)
    person_id = Column(Integer, ForeignKey("people.id"), index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), index=True)
    campaign_lead_id = Column(Integer, ForeignKey("campaign_leads.id"))
    sequence_step_id = Column(Integer, ForeignKey("sequence_steps.id"))

    # Scheduling
    scheduled_for = Column(DateTime, nullable=False, index=True)
    priority = Column(Integer, default=0)  # Higher = more urgent

    # Email content (pre-rendered)
    to_email = Column(String(255), nullable=False)
    from_email = Column(String(255), nullable=False)
    subject = Column(String(500), nullable=False)
    body = Column(Text, nullable=False)

    # Status
    status = Column(Enum(QueueStatus), default=QueueStatus.PENDING, index=True)

    # Processing info
    picked_up_at = Column(DateTime)
    completed_at = Column(DateTime)
    error_message = Column(Text)
    retry_count = Column(Integer, default=0)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<SendQueue {self.id} to={self.to_email}>"
