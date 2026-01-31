from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime

from app.models.base import Base


class Sequence(Base):
    __tablename__ = "sequences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    steps = relationship(
        "SequenceStep",
        back_populates="sequence",
        order_by="SequenceStep.order",
        cascade="all, delete-orphan"
    )
    campaigns = relationship("Campaign", back_populates="sequence")

    def __repr__(self):
        return f"<Sequence {self.name}>"


class SequenceStep(Base):
    __tablename__ = "sequence_steps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sequence_id = Column(Integer, ForeignKey("sequences.id"), index=True)

    order = Column(Integer, nullable=False)  # Step number (0, 1, 2...)

    # Timing
    delay_days = Column(Integer, default=0)   # Days to wait after previous step
    delay_hours = Column(Integer, default=0)  # Additional hours

    # Email content
    subject = Column(String(500), nullable=False)
    body = Column(Text, nullable=False)

    # Content type
    use_gpt = Column(Boolean, default=False)          # Use GPT for personalization
    gpt_prompt = Column(Text)                         # Custom GPT prompt if use_gpt=True

    # Variables available: {{first_name}}, {{last_name}}, {{company_name}},
    # {{role}}, {{personalization}}
    # These get replaced at send time

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    sequence = relationship("Sequence", back_populates="steps")

    def __repr__(self):
        return f"<SequenceStep {self.sequence_id}:{self.order}>"
