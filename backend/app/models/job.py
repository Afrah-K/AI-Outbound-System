from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON
from datetime import datetime

from app.models.base import Base


class BackgroundJob(Base):
    """
    A long-running piece of work (a scrape, an enrichment run, list
    verification...) queued by the API and run by the worker. Lives in the
    database rather than in memory so any API instance can report its
    progress - required when the API runs as serverless functions.
    """
    __tablename__ = "background_jobs"

    id = Column(String(36), primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True)  # the account this belongs to
    kind = Column(String(40), index=True, nullable=False)
    status = Column(String(20), index=True, default="queued")  # queued | running | completed | failed

    payload = Column(JSON)             # what to do - everything the worker needs
    processed = Column(Integer, default=0)
    total = Column(Integer, default=0)
    message = Column(String(500), default="")
    extra = Column(JSON)               # kind-specific live counters, e.g. {"emails_found": 12}
    result = Column(JSON)              # set when completed
    error = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    started_at = Column(DateTime)
    heartbeat_at = Column(DateTime)    # refreshed while running; a stale one means the worker died
    finished_at = Column(DateTime)
