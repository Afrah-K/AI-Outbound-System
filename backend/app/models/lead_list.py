from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime

from app.models.base import Base


class LeadList(Base):
    """A named group of prospects - one per CSV upload - so a campaign can target exactly that upload."""
    __tablename__ = "lead_lists"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True)  # the account this belongs to
    name = Column(String(255), nullable=False)
    source_filename = Column(String(255))

    created_at = Column(DateTime, default=datetime.utcnow)
    # Set when the list is deleted. Soft delete: the memberships are kept so its
    # prospects still count as "listed" and aren't swept back into an auto-made
    # "Added <date>" list by group_unlisted_prospects.
    deleted_at = Column(DateTime)

    members = relationship("LeadListMember", back_populates="lead_list", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<LeadList {self.name}>"


class LeadListMember(Base):
    __tablename__ = "lead_list_members"
    __table_args__ = (UniqueConstraint("lead_list_id", "person_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True)  # the account this belongs to
    lead_list_id = Column(Integer, ForeignKey("lead_lists.id"), index=True, nullable=False)
    person_id = Column(Integer, ForeignKey("people.id"), index=True, nullable=False)

    lead_list = relationship("LeadList", back_populates="members")
    person = relationship("Person")
