"""
Sign up / sign in with email + password, or with a Google account.

Google sign-in reuses the app's Google OAuth client (GOOGLE_CLIENT_ID/SECRET)
with only the basic "openid email profile" scopes; GOOGLE_LOGIN_REDIRECT_URI
must be listed in that client's Authorized redirect URIs.
"""
import secrets
from typing import Optional
from urllib.parse import quote, urlencode

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User, UserSession
from app.services.auth import (
    check_password_strength,
    clear_failed_logins,
    end_session,
    hash_password,
    normalize_email,
    record_failed_login,
    start_session,
    too_many_failed_logins,
    user_from_request,
    user_payload,
    valid_email,
    verify_password,
)

logger = structlog.get_logger()
router = APIRouter()

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
STATE_COOKIE = "outbound_oauth_state"
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))  # keeps unknown-email logins as slow as real ones


class SignupRequest(BaseModel):
    name: str = ""
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/signup")
async def signup(payload: SignupRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    email = normalize_email(payload.email)
    if not valid_email(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    problem = check_password_strength(payload.password)
    if problem:
        raise HTTPException(status_code=400, detail=problem)

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        hint = "sign in with Google" if existing.google_sub and not existing.password_hash else "sign in instead"
        raise HTTPException(status_code=409, detail=f"An account with this email already exists - {hint}")

    user = User(
        email=email,
        name=payload.name.strip()[:255] or email.split("@")[0],
        password_hash=await run_in_threadpool(hash_password, payload.password),
    )
    db.add(user)
    db.commit()
    start_session(db, user, response, request.headers.get("user-agent", ""))
    logger.info("auth.signup", user_id=user.id)
    return {"user": user_payload(user)}


@router.post("/login")
async def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    email = normalize_email(payload.email)
    if too_many_failed_logins(email):
        raise HTTPException(status_code=429, detail="Too many attempts - wait 15 minutes and try again")

    user = db.query(User).filter(User.email == email).first()
    if user and not user.password_hash:
        raise HTTPException(status_code=400, detail="This account signs in with Google - use \"Continue with Google\"")

    ok = await run_in_threadpool(verify_password, payload.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok:
        record_failed_login(email)
        raise HTTPException(status_code=401, detail="Wrong email or password")

    clear_failed_logins(email)
    start_session(db, user, response, request.headers.get("user-agent", ""))
    return {"user": user_payload(user)}


@router.post("/logout")
async def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    end_session(db, request, response)
    return {"success": True}


@router.get("/me")
async def me(request: Request, db: Session = Depends(get_db)):
    user = user_from_request(db, request)
    if user is None:
        raise HTTPException(status_code=401, detail="Please sign in")
    return {"user": user_payload(user)}


@router.get("/config")
async def auth_config():
    """What the sign-in page can offer."""
    return {"google_enabled": bool(settings.google_client_id and settings.google_client_secret)}


# ---------------------------------------------------------------------------
# Google sign-in
# ---------------------------------------------------------------------------

def _safe_next(next_path: Optional[str]) -> str:
    """Only same-app paths, so the login can't be used to bounce people to another site."""
    if not next_path or not next_path.startswith("/") or next_path.startswith("//"):
        return "/"
    return next_path


def _frontend(path: str) -> str:
    return settings.app_base_url.rstrip("/") + path


def _login_error(message: str) -> RedirectResponse:
    return RedirectResponse(_frontend(f"/login?error={quote(message)}"), status_code=302)


@router.get("/google/start")
async def google_start(next: Optional[str] = Query(None)):
    if not (settings.google_client_id and settings.google_client_secret):
        return _login_error("Google sign-in isn't set up (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)")

    state = secrets.token_urlsafe(24)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_login_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    response = RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}", status_code=302)
    # The state (and where to go afterwards) rides in a short-lived cookie, checked on the way back
    response.set_cookie(
        STATE_COOKIE, f"{state}|{_safe_next(next)}", max_age=600, httponly=True,
        secure=settings.session_cookie_secure, samesite="lax", path="/",
    )
    return response


def _verify_google_id_token(token: str) -> dict:
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(token, google_requests.Request(), settings.google_client_id)


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    if error:
        return _login_error("Google sign-in was cancelled" if error == "access_denied" else f"Google sign-in failed: {error}")

    cookie = request.cookies.get(STATE_COOKIE, "")
    expected_state, _, next_path = cookie.partition("|")
    if not code or not state or not expected_state or not secrets.compare_digest(state, expected_state):
        return _login_error("Sign-in expired - please try again")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            token_response = await client.post(GOOGLE_TOKEN_URL, data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_login_redirect_uri,
                "grant_type": "authorization_code",
            })
        token_response.raise_for_status()
        claims = await run_in_threadpool(_verify_google_id_token, token_response.json()["id_token"])
    except Exception as exc:  # noqa: BLE001 - shown to the user as a generic failure
        logger.warning("auth.google_failed", error=str(exc))
        return _login_error("Couldn't sign in with Google - please try again")

    email = normalize_email(claims.get("email"))
    if not email or not claims.get("email_verified"):
        return _login_error("Your Google account's email isn't verified")

    user = db.query(User).filter(User.google_sub == claims["sub"]).first()
    if user is None:
        user = db.query(User).filter(User.email == email).first()
        if user is not None and not user.google_sub:
            # First Google sign-in for an existing email+password account. Google
            # has just proven who owns this address, so it takes over - and any
            # password set before is removed, in case someone else signed up
            # with this address first. (They can set a new one later.)
            if user.password_hash:
                user.password_hash = None
                db.query(UserSession).filter(UserSession.user_id == user.id).delete()
                logger.info("auth.google_claimed_password_account", user_id=user.id)
            user.google_sub = claims["sub"]
    if user is None:
        user = User(email=email, google_sub=claims["sub"])
        db.add(user)

    user.name = user.name or claims.get("name") or email.split("@")[0]
    user.avatar_url = claims.get("picture") or user.avatar_url
    db.commit()

    response = RedirectResponse(_frontend(_safe_next(next_path)), status_code=302)
    response.delete_cookie(STATE_COOKIE, path="/")
    start_session(db, user, response, request.headers.get("user-agent", ""))
    return response
