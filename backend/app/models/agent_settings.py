from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey
from datetime import datetime

from app.models.base import Base


class AgentSettings(Base):
    """Single-row settings for the reply agent - kept server-side so the background run uses them too."""
    # Not "agent_settings": an earlier SMS-based version of this table may exist in local DBs with other columns.
    __tablename__ = "reply_agent_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True)  # the account this belongs to

    # What the agent should know when drafting: offer, quotable prices, next step, tone
    instructions = Column(Text, default="")

    # Draft incoming lead replies automatically in the background (never sends)
    auto_draft = Column(Boolean, default=True)

    # Human-in-the-loop email alert when new drafts are waiting for approval
    email_alerts_enabled = Column(Boolean, default=False)
    notify_email = Column(String(255))
    # Connected inbox the alert is sent from (defaults to the first connected one)
    alert_inbox_id = Column(Integer, ForeignKey("inboxes.id", ondelete="SET NULL"))

    last_auto_run_at = Column(DateTime)
    last_auto_result = Column(Text)  # JSON summary of the last background run

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
