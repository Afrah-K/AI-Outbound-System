from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from datetime import datetime

from app.models.base import Base


class IntegrationSettings(Base):
    """Single-row settings for third-party integrations (Calendly, Google Maps)."""
    __tablename__ = "integration_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True)  # the account this belongs to

    # Public booking page, e.g. https://calendly.com/you/30min - embedded on the Book a Call
    # page and given to the reply agent so drafts can propose a call with the real link.
    calendly_url = Column(String(512))
    # Personal access token (calendly.com/integrations/api_webhooks) - only needed to read
    # booked events for the Calendar page. Stored locally, like the Gmail OAuth tokens.
    calendly_token = Column(Text)
    # Google Places API (New) key for the Google Maps scraper - used when
    # GOOGLE_MAPS_API_KEY isn't set in .env. Stored locally, never sent to the browser.
    google_maps_api_key = Column(Text)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
