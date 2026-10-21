from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime

from app.models.base import Base


class AgentDraft(Base):
    """
    The reply agent's read of one lead reply: how it classified it, and the
    response it drafted. Nothing is sent until a person approves it in the
    Unibox. One row per lead message, so re-running the agent never
    re-drafts a reply it has already handled.
    """
    __tablename__ = "agent_drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True)  # the account this belongs to
    inbox_id = Column(Integer, ForeignKey("inboxes.id", ondelete="CASCADE"), index=True, nullable=False)
    thread_id = Column(String(255), index=True, nullable=False)
    lead_message_id = Column(String(255), unique=True, nullable=False)  # Gmail id of the reply this answers
    person_id = Column(Integer, ForeignKey("people.id"), index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="SET NULL"), index=True)

    # Triage
    category = Column(String(50))          # interested, question, not_interested, out_of_office, unsubscribe, wrong_person, other
    summary = Column(Text)                 # one line: what the lead said / wants
    suggested_status = Column(String(50))  # a LeadStatus value to apply, or null

    # Draft (empty when the reply doesn't need an answer, e.g. out of office)
    draft_subject = Column(String(500))
    draft_body = Column(Text)

    status = Column(String(20), default="pending", index=True)  # pending, sent, dismissed, superseded, failed
    error = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    sent_at = Column(DateTime)

    person = relationship("Person")
    inbox = relationship("Inbox")

    def __repr__(self):
        return f"<AgentDraft {self.id} {self.category} {self.status}>"
