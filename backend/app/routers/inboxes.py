import asyncio
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app.models import Inbox
from app.config import settings
from app.integrations.gmail import (
    generate_auth_url,
    validate_state_token,
    exchange_code_for_tokens,
)
from app.integrations.mail import (
    PROVIDER_GMAIL,
    PROVIDER_SMTP,
    MailConnectionError,
    MailCredentialsError,
    SmtpImapService,
    provider_for,
    sync_tokens,
)
from app.integrations.mail.credentials import encrypt_password, ensure_configured
from app.integrations.mail.smtp_imap import SECURITY_OPTIONS

router = APIRouter()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _connection_payload(inbox: Inbox) -> dict:
    """How the inbox connects - SMTP/IMAP server settings, never the password."""
    payload = {"provider": inbox.provider or PROVIDER_GMAIL, "connected": inbox.has_credentials}
    if inbox.is_smtp:
        payload["smtp"] = {
            "smtp_host": inbox.smtp_host,
            "smtp_port": inbox.smtp_port,
            "smtp_security": inbox.smtp_security,
            "imap_host": inbox.imap_host,
            "imap_port": inbox.imap_port,
            "imap_security": inbox.imap_security,
            "username": inbox.username,
        }
    return payload


@router.get("")
async def list_inboxes(db: Session = Depends(get_db)):
    """List all inboxes with health scores."""
    inboxes = db.query(Inbox).all()
    return {
        "inboxes": [
            {
                "id": inbox.id,
                "email_address": inbox.email_address,
                "domain": inbox.domain,
                "display_name": inbox.display_name,
                "daily_limit": inbox.daily_limit,
                "emails_sent_today": inbox.emails_sent_today,
                "warmup_stage": inbox.warmup_stage.value if inbox.warmup_stage else None,
                "health_score": inbox.health_score,
                "is_active": inbox.is_active,
                "created_at": inbox.created_at.isoformat() if inbox.created_at else None,
                **_connection_payload(inbox),
            }
            for inbox in inboxes
        ],
        "total": len(inboxes)
    }


@router.get("/{inbox_id}")
async def get_inbox(inbox_id: int, db: Session = Depends(get_db)):
    """Get inbox details."""
    inbox = db.query(Inbox).filter(Inbox.id == inbox_id).first()
    if not inbox:
        raise HTTPException(status_code=404, detail="Inbox not found")
    return {
        "id": inbox.id,
        "email_address": inbox.email_address,
        "domain": inbox.domain,
        "display_name": inbox.display_name,
        "daily_limit": inbox.daily_limit,
        "emails_sent_today": inbox.emails_sent_today,
        "warmup_stage": inbox.warmup_stage.value if inbox.warmup_stage else None,
        "health_score": inbox.health_score,
        "is_active": inbox.is_active,
        "bounce_count_7d": inbox.bounce_count_7d,
        "reply_count_7d": inbox.reply_count_7d,
        "emails_sent_7d": inbox.emails_sent_7d,
        "created_at": inbox.created_at.isoformat() if inbox.created_at else None,
        "updated_at": inbox.updated_at.isoformat() if inbox.updated_at else None,
        **_connection_payload(inbox),
    }


class SmtpSettings(BaseModel):
    smtp_host: str = Field(..., max_length=255)
    smtp_port: int = Field(..., ge=1, le=65535)
    smtp_security: str
    imap_host: str = Field(..., max_length=255)
    imap_port: int = Field(..., ge=1, le=65535)
    imap_security: str
    username: str = Field("", max_length=255)


class SmtpInboxCreate(SmtpSettings):
    email_address: str = Field(..., max_length=255)
    display_name: str = Field("", max_length=255)
    password: str = Field(..., min_length=1, max_length=1024)


class SmtpInboxUpdate(SmtpSettings):
    display_name: Optional[str] = Field(None, max_length=255)
    # Blank keeps the saved password (e.g. only the port changed)
    password: str = Field("", max_length=1024)


def _clean_settings(payload: SmtpSettings, email_address: str) -> dict:
    values = {
        "smtp_host": payload.smtp_host.strip(),
        "smtp_port": payload.smtp_port,
        "smtp_security": payload.smtp_security.strip().lower(),
        "imap_host": payload.imap_host.strip(),
        "imap_port": payload.imap_port,
        "imap_security": payload.imap_security.strip().lower(),
        "username": payload.username.strip() or email_address,
    }
    for host in ("smtp_host", "imap_host"):
        if not values[host] or any(c.isspace() for c in values[host]):
            raise HTTPException(status_code=400, detail=f"Enter a valid {host.split('_')[0].upper()} server host name")
    for security in ("smtp_security", "imap_security"):
        if values[security] not in SECURITY_OPTIONS:
            raise HTTPException(
                status_code=400, detail=f"{security.split('_')[0].upper()} security must be 'ssl' or 'starttls'"
            )
    return values


async def _verify_login(email_address: str, values: dict, password: str) -> None:
    """Log in to the SMTP and the IMAP server before saving - 400 saying which failed and why."""
    service = SmtpImapService(email_address=email_address, password=password, **values)
    try:
        await asyncio.to_thread(service.get_profile)
    except MailConnectionError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc), "server": exc.server, "reason": exc.reason})
    finally:
        await asyncio.to_thread(service.close)


def _require_credentials_key() -> None:
    try:
        ensure_configured()
    except MailCredentialsError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/smtp")
async def connect_smtp_inbox(payload: SmtpInboxCreate, db: Session = Depends(get_db)):
    """
    Connect any mail account over SMTP (sending) + IMAP (reading). Both logins
    are tested before anything is saved; the password is stored encrypted.
    """
    _require_credentials_key()
    email_address = payload.email_address.strip().lower()
    if not EMAIL_RE.match(email_address):
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    values = _clean_settings(payload, email_address)

    if db.query(Inbox.id).filter(Inbox.email_address == email_address).first():
        raise HTTPException(
            status_code=409, detail=f"{email_address} is already connected - update its settings instead"
        )
    # A mailbox can only belong to one account's workspace
    from app.tenancy import system_context

    with system_context():
        taken = db.query(Inbox.id).filter(Inbox.email_address == email_address).first()
    if taken:
        raise HTTPException(status_code=409, detail=f"{email_address} is already connected to a different account")

    await _verify_login(email_address, values, payload.password)

    inbox = Inbox(
        email_address=email_address,
        domain=email_address.split("@", 1)[1],
        display_name=payload.display_name.strip() or email_address.split("@", 1)[0],
        provider=PROVIDER_SMTP,
        password_encrypted=encrypt_password(payload.password),
        daily_limit=settings.default_daily_limit,
        **values,
    )
    db.add(inbox)
    db.commit()
    db.refresh(inbox)
    return {"id": inbox.id, "email_address": inbox.email_address, "display_name": inbox.display_name, **_connection_payload(inbox)}


@router.put("/{inbox_id}/smtp")
async def update_smtp_inbox(inbox_id: int, payload: SmtpInboxUpdate, db: Session = Depends(get_db)):
    """Change an SMTP/IMAP inbox's server settings or password - tested before saving."""
    inbox = db.query(Inbox).filter(Inbox.id == inbox_id).first()
    if not inbox:
        raise HTTPException(status_code=404, detail="Inbox not found")
    if not inbox.is_smtp:
        raise HTTPException(status_code=400, detail="This is a Gmail inbox - reconnect it with Google instead")
    _require_credentials_key()
    values = _clean_settings(payload, inbox.email_address)

    if payload.password:
        password = payload.password
    else:
        try:
            password = SmtpImapService.from_inbox(inbox)._password
        except MailCredentialsError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    await _verify_login(inbox.email_address, values, password)

    for key, value in values.items():
        setattr(inbox, key, value)
    if payload.password:
        inbox.password_encrypted = encrypt_password(payload.password)
    if payload.display_name is not None and payload.display_name.strip():
        inbox.display_name = payload.display_name.strip()
    inbox.is_active = True
    db.commit()
    return {"id": inbox.id, "email_address": inbox.email_address, "display_name": inbox.display_name, **_connection_payload(inbox)}


@router.get("/oauth/initiate")
async def initiate_oauth():
    """
    Initiate Gmail OAuth flow.

    Returns a URL that the frontend should redirect the user to.
    After the user authorizes, Google will redirect back to /oauth/callback.
    """
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=500,
            detail="Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET."
        )

    auth_url, state = generate_auth_url()

    return {
        "auth_url": auth_url,
        "state": state,
        "message": "Redirect user to auth_url to begin OAuth flow"
    }


@router.get("/oauth/callback")
async def oauth_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Handle Gmail OAuth callback.

    Google redirects here after user authorizes (or denies) access.
    This endpoint exchanges the code for tokens and creates/updates the inbox.
    """
    # Handle user denial
    if error:
        raise HTTPException(
            status_code=400,
            detail=f"OAuth authorization failed: {error}"
        )

    if not code:
        raise HTTPException(
            status_code=400,
            detail="No authorization code provided"
        )

    if not state:
        raise HTTPException(
            status_code=400,
            detail="No state token provided"
        )

    # Validate state token to prevent CSRF
    if not validate_state_token(state):
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired state token"
        )

    try:
        # Exchange code for tokens
        token_data = exchange_code_for_tokens(code)

        email = token_data["email"]
        domain = email.split("@")[1] if "@" in email else ""

        # Check if inbox already exists
        existing_inbox = db.query(Inbox).filter(
            Inbox.email_address == email
        ).first()

        if existing_inbox:
            # Update existing inbox with new tokens
            existing_inbox.access_token = token_data["access_token"]
            existing_inbox.refresh_token = token_data["refresh_token"]
            existing_inbox.token_expiry = token_data["token_expiry"]
            existing_inbox.provider = PROVIDER_GMAIL  # e.g. was connected over SMTP/IMAP before
            existing_inbox.is_active = True
            db.commit()
            db.refresh(existing_inbox)

            # Redirect to frontend with success
            return RedirectResponse(
                url=f"{settings.app_base_url.rstrip('/')}/inboxes?connected={email}&updated=true"
            )
        else:
            # A mailbox can only belong to one account's workspace
            from app.tenancy import system_context

            with system_context():
                taken = db.query(Inbox.id).filter(Inbox.email_address == email).first()
            if taken:
                return RedirectResponse(
                    url=f"{settings.app_base_url.rstrip('/')}/inboxes?error="
                    + quote(f"{email} is already connected to a different account")
                )

            # Create new inbox
            inbox = Inbox(
                email_address=email,
                domain=domain,
                display_name=email.split("@")[0],
                access_token=token_data["access_token"],
                refresh_token=token_data["refresh_token"],
                token_expiry=token_data["token_expiry"],
                daily_limit=settings.default_daily_limit,
            )
            db.add(inbox)
            db.commit()
            db.refresh(inbox)

            # Redirect to frontend with success
            return RedirectResponse(
                url=f"{settings.app_base_url.rstrip('/')}/inboxes?connected={email}"
            )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to complete OAuth flow: {str(e)}"
        )


@router.post("/{inbox_id}/test")
async def test_inbox(inbox_id: int, db: Session = Depends(get_db)):
    """
    Test an inbox by verifying credentials and fetching profile.
    """
    inbox = db.query(Inbox).filter(Inbox.id == inbox_id).first()
    if not inbox:
        raise HTTPException(status_code=404, detail="Inbox not found")

    if not inbox.has_credentials:
        raise HTTPException(
            status_code=400,
            detail="Inbox is not connected"
        )

    try:
        mail = provider_for(inbox)

        # Get profile to verify connection (SMTP inboxes: logs in to both servers)
        profile = await asyncio.to_thread(mail.get_profile)

        # Update tokens if they were refreshed
        if sync_tokens(inbox, mail):
            db.commit()

        return {
            "success": True,
            "email": profile["emailAddress"],
            "messages_total": profile.get("messagesTotal"),
            "threads_total": profile.get("threadsTotal"),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@router.post("/{inbox_id}/send-test")
async def send_test_email(
    inbox_id: int,
    to: str = Query(..., description="Recipient email address"),
    db: Session = Depends(get_db),
):
    """
    Send a test email from an inbox.
    """
    inbox = db.query(Inbox).filter(Inbox.id == inbox_id).first()
    if not inbox:
        raise HTTPException(status_code=404, detail="Inbox not found")

    if not inbox.has_credentials:
        raise HTTPException(
            status_code=400,
            detail="Inbox is not connected"
        )

    how = "SMTP/IMAP" if inbox.is_smtp else "Gmail OAuth"
    try:
        mail = provider_for(inbox)

        result = await asyncio.to_thread(
            mail.send_email,
            to=to,
            subject="Test Email from AI Outbound System",
            body=f"This is a test email to verify your inbox is properly connected.\n\nIf you received this, your {how} setup is working correctly!",
            from_name=inbox.display_name,
        )

        # Update tokens if refreshed
        if sync_tokens(inbox, mail):
            db.commit()

        return {
            "success": True,
            "message_id": result["message_id"],
            "thread_id": result["thread_id"],
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to send test email: {str(e)}"
        )


@router.delete("/{inbox_id}")
async def delete_inbox(inbox_id: int, db: Session = Depends(get_db)):
    """Remove an inbox."""
    inbox = db.query(Inbox).filter(Inbox.id == inbox_id).first()
    if not inbox:
        raise HTTPException(status_code=404, detail="Inbox not found")
    db.delete(inbox)
    db.commit()
    return {"message": "Inbox deleted successfully"}
