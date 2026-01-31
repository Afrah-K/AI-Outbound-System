from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.orm import relationship
from datetime import datetime

from app.models.base import Base


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, index=True)
    domain = Column(String(255), unique=True, index=True)
    website = Column(String(512))

    # Company details (from Apollo CSV)
    industry = Column(String(255))
    size = Column(String(50))           # e.g., "11-50", "51-200"
    employee_count = Column(Integer)
    funding_stage = Column(String(100))  # e.g., "Series A", "Seed"
    total_funding = Column(String(50))
    linkedin_url = Column(String(512))
    location = Column(String(255))

    # Enrichment data
    homepage_text = Column(Text)         # Scraped homepage content
    enrichment_summary = Column(Text)    # GPT-generated company summary
    personalization_hook = Column(Text)  # GPT-generated personalization sentence
    last_enriched_at = Column(DateTime)
    enrichment_status = Column(String(50), default="pending")  # pending, completed, failed
    enrichment_error = Column(Text)

    # Deduplication
    apollo_id = Column(String(100), index=True)  # Original Apollo ID if available

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    people = relationship("Person", back_populates="company", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Company {self.name}>"
