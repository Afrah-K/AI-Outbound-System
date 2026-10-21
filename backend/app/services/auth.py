"""
Accounts: password hashing, login sessions and the "who is signed in"
dependency that scopes every API request to that user's workspace.

- Passwords: PBKDF2-SHA256 with a per-user salt (600k iterations), from the
  standard library, compared in constant time.
- Sessions: a random token in an HttpOnly cookie; only its SHA-256 is stored,
  so a copy of the database can't be used to sign in. Signing out deletes it.
"""
import base64
import hashlib
import hmac
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User, UserSession
from app.tenancy import current_owner_id

PBKDF2_ITERATIONS = 600_000
MIN_PASSWORD_LENGTH = 8
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TOUCH_EVERY = timedelta(minutes=10)  # how often a session's last_seen_at is refreshed

# Failed logins per email: at most 5 per 15 minutes
_failed_logins: dict = defaultdict(deque)
MAX_FAILED_LOGINS = 5
FAILED_LOGIN_WINDOW = 15 * 60


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email or ""))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS, base64.b64encode(salt).decode(), base64.b64encode(digest).decode()
    )


def verify_password(password: str, stored: Optional[str]) -> bool:
    if not stored:
        return False
    try:
        algorithm, iterations, salt, digest = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def check_password_strength(password: str) -> Optional[str]:
    if len(password or "") < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters"
    if len(password) > 256:
        return "That password is too long"
    return None


def too_many_failed_logins(email: str) -> bool:
    attempts = _failed_logins[email]
    cutoff = time.monotonic() - FAILED_LOGIN_WINDOW
    while attempts and attempts[0] < cutoff:
        attempts.popleft()
    return len(attempts) >= MAX_FAILED_LOGINS


def record_failed_login(email: str) -> None:
    _failed_logins[email].append(time.monotonic())


def clear_failed_logins(email: str) -> None:
    _failed_logins.pop(email, None)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(db: Session, user: User, response: Response, user_agent: str = "") -> None:
    """Sign `user` in: store a new session and set its cookie on `response`."""
    token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    db.add(UserSession(
        user_id=user.id,
        token_hash=_token_hash(token),
        expires_at=now + timedelta(days=settings.session_days),
        last_seen_at=now,
        user_agent=(user_agent or "")[:255],
    ))
    user.last_login_at = now
    db.commit()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_days * 24 * 3600,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def end_session(db: Session, request: Request, response: Response) -> None:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        db.query(UserSession).filter(UserSession.token_hash == _token_hash(token)).delete()
        db.commit()
    response.delete_cookie(settings.session_cookie_name, path="/")


def user_from_request(db: Session, request: Request) -> Optional[User]:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    session = db.query(UserSession).filter(UserSession.token_hash == _token_hash(token)).first()
    now = datetime.utcnow()
    if not session or session.expires_at < now:
        return None
    if not session.last_seen_at or now - session.last_seen_at > TOUCH_EVERY:
        session.last_seen_at = now
        db.commit()
    return db.get(User, session.user_id)


async def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    """
    The signed-in user, or 401. Also sets the workspace every query in this
    request is limited to - so it must guard every router with user data.
    (async on purpose: it runs in the request's own context, so the owner it
    sets stays in place for the endpoint and its background tasks.)
    """
    user = user_from_request(db, request)
    if user is None:
        raise HTTPException(status_code=401, detail="Please sign in")
    current_owner_id.set(user.id)
    request.state.user = user
    return user


def user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "avatar_url": user.avatar_url,
        "has_password": bool(user.password_hash),
        "has_google": bool(user.google_sub),
        "created_at": user.created_at.isoformat() + "Z" if user.created_at else None,
    }
