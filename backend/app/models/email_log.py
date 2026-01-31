from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from app.models.base import Base


class EmailStatus(enum.Enum):
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    CLICKED = "clicked"
    REPLIED = "replied"
    BOUNCED = "bounced"
    FAILED = "failed"
    SPAM_REPORTED = "spam_reported"


class EmailType(enum.Enum):
    CAMPAIGN = "campaign"
    WARMUP = "warmup"
    MANUAL = "manual"
    TEST = "test"


class EmailLog(Base):
    __tablename__ = "email_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Associations
    inbox_id = Column(Integer, ForeignKey("inboxes.id"), index=True)
    person_id = Column(Integer, ForeignKey("people.id"), index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), index=True)
    sequence_step_id = Column(Integer, ForeignKey("sequence_steps.id"))

    # Email details
    email_type = Column(Enum(EmailType), default=EmailType.CAMPAIGN)
    to_email = Column(String(255), nullable=False, index=True)
    from_email = Column(String(255), nullable=False)
    subject = Column(String(500))
    body = Column(Text)

    # Gmail tracking
    gmail_message_id = Column(String(255), index=True)  # Gmail's message ID
    gmail_thread_id = Column(String(255), index=True)   # For reply threading

    # Status tracking
    status = Column(Enum(EmailStatus), default=EmailStatus.QUEUED, index=True)

    # Timestamps
    queued_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime)
    delivered_at = Column(DateTime)
    opened_at = Column(DateTime)
    replied_at = Column(DateTime)
    bounced_at = Column(DateTime)

    # Error tracking
    error_message = Column(Text)
    retry_count = Column(Integer, default=0)

    # Relationships
    inbox = relationship("Inbox", back_populates="email_logs")
    person = relationship("Person", back_populates="email_logs")

    def __repr__(self):
        return f"<EmailLog {self.id} to={self.to_email}>"
