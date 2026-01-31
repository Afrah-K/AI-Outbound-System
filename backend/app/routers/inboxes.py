from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app.models import Inbox
from app.config import settings
from app.integrations.gmail import (
    generate_auth_url,
    validate_state_token,
    exchange_code_for_tokens,
    GmailService,
)

router = APIRouter()


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
    }


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
            existing_inbox.is_active = True
            db.commit()
            db.refresh(existing_inbox)

            # Redirect to frontend with success
            return RedirectResponse(
                url=f"http://localhost:5173/inboxes?connected={email}&updated=true"
            )
        else:
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
                url=f"http://localhost:5173/inboxes?connected={email}"
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

    if not inbox.access_token or not inbox.refresh_token:
        raise HTTPException(
            status_code=400,
            detail="Inbox is not connected to Gmail"
        )

    try:
        gmail = GmailService(
            access_token=inbox.access_token,
            refresh_token=inbox.refresh_token,
            token_expiry=inbox.token_expiry,
        )

        # Get profile to verify connection
        profile = gmail.get_profile()

        # Update tokens if they were refreshed
        updated = gmail.updated_tokens
        if updated["access_token"] != inbox.access_token:
            inbox.access_token = updated["access_token"]
            inbox.token_expiry = updated["token_expiry"]
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

    if not inbox.access_token or not inbox.refresh_token:
        raise HTTPException(
            status_code=400,
            detail="Inbox is not connected to Gmail"
        )

    try:
        gmail = GmailService(
            access_token=inbox.access_token,
            refresh_token=inbox.refresh_token,
            token_expiry=inbox.token_expiry,
        )

        result = gmail.send_email(
            to=to,
            subject="Test Email from AI Outbound System",
            body="This is a test email to verify your inbox is properly connected.\n\nIf you received this, your Gmail OAuth setup is working correctly!",
            from_name=inbox.display_name,
        )

        # Update tokens if refreshed
        updated = gmail.updated_tokens
        if updated["access_token"] != inbox.access_token:
            inbox.access_token = updated["access_token"]
            inbox.token_expiry = updated["token_expiry"]
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
