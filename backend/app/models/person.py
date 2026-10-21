from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from app.models.base import Base


class LeadStatus(enum.Enum):
    NEW = "new"
    CONTACTED = "contacted"
    REPLIED = "replied"
    BOUNCED = "bounced"
    UNSUBSCRIBED = "unsubscribed"
    CONVERTED = "converted"
    DO_NOT_CONTACT = "do_not_contact"


class Person(Base):
    __tablename__ = "people"
    # Unique per account - two workspaces can both have the same prospect
    __table_args__ = (UniqueConstraint("owner_id", "email", name="uq_people_owner_email"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True)  # the account this belongs to
    email = Column(String(255), nullable=False, index=True)
    first_name = Column(String(100))
    last_name = Column(String(100))
    full_name = Column(String(255))

    # Professional info
    role = Column(String(255))           # Job title
    seniority = Column(String(50))       # e.g., "Director", "VP", "C-Level"
    department = Column(String(100))
    linkedin_url = Column(String(512))
    phone = Column(String(50))

    # Company relationship
    company_id = Column(Integer, ForeignKey("companies.id"), index=True)

    # Lead management
    status = Column(Enum(LeadStatus), default=LeadStatus.NEW, index=True)

    # Personalization
    personalization_sentence = Column(Text)  # GPT-generated for this person

    # Deduplication
    apollo_id = Column(String(100), index=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    company = relationship("Company", back_populates="people")
    email_logs = relationship("EmailLog", back_populates="person")
    campaign_leads = relationship("CampaignLead", back_populates="person")

    def __repr__(self):
        return f"<Person {self.email}>"
