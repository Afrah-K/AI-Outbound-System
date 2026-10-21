from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from datetime import datetime

from app.models.base import Base


class WarmupConfig(Base):
    """Global warmup configuration."""
    __tablename__ = "warmup_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True)  # the account this belongs to

    # Stage configurations
    stage_1_daily_limit = Column(Integer, default=5)
    stage_1_duration_days = Column(Integer, default=7)

    stage_2_daily_limit = Column(Integer, default=10)
    stage_2_duration_days = Column(Integer, default=7)

    stage_3_daily_limit = Column(Integer, default=20)
    stage_3_duration_days = Column(Integer, default=7)

    # Auto-pause thresholds
    bounce_rate_threshold = Column(Integer, default=5)   # Pause if >5% bounce
    pause_on_spam_report = Column(Boolean, default=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WarmupLog(Base):
    """Track warmup email interactions."""
    __tablename__ = "warmup_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True)  # the account this belongs to
    inbox_id = Column(Integer, ForeignKey("inboxes.id", ondelete="SET NULL"), index=True)

    # Warmup email details
    sent_to = Column(String(255))         # Target email
    received_from = Column(String(255))   # Warmup replies received

    action = Column(String(50))           # sent, received, opened, replied

    created_at = Column(DateTime, default=datetime.utcnow)
