from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from datetime import datetime

from app.models.base import Base


class User(Base):
    """An account. Every inbox, prospect, campaign... belongs to one (owner_id)."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)  # stored lower-case
    name = Column(String(255))
    avatar_url = Column(String(1024))

    # Either or both: an email+password login, and/or a linked Google account
    password_hash = Column(String(255))
    google_sub = Column(String(255), unique=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime)


class UserSession(Base):
    """A signed-in browser. Only a hash of the cookie token is stored, so a leaked DB can't be replayed."""
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    last_seen_at = Column(DateTime)
    user_agent = Column(String(255))
