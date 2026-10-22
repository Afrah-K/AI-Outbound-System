"""
Email notifications, sent through one of the user's own connected
inboxes - no extra service or credentials. Used by the reply agent to pull
a human in when drafts are waiting for approval.
"""
import asyncio
import re
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.models import Inbox
from app.services.unibox import mail_for, sync_tokens

logger = structlog.get_logger()


def valid_email(address: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", (address or "").strip()))


def alert_inbox(db: Session, inbox_id: Optional[int] = None) -> Optional[Inbox]:
    """The connected inbox alerts go out from: the chosen one if still connected, else the first connected inbox."""
    connected = [
        i for i in db.query(Inbox).filter(Inbox.is_active == True).order_by(Inbox.id).all()  # noqa: E712
        if i.has_credentials
    ]
    chosen = next((i for i in connected if i.id == inbox_id), None)
    return chosen or (connected[0] if connected else None)


async def send_notification_email(db: Session, to: str, subject: str, body: str, inbox_id: Optional[int] = None) -> dict:
    """
    Send an alert email from a connected inbox. Raises ValueError when it
    can't (no connected inbox, bad address) and RuntimeError if sending fails.
    Alerts don't count against the inbox's daily campaign quota.
    """
    if not valid_email(to):
        raise ValueError(f"'{to}' is not a valid email address")
    inbox = alert_inbox(db, inbox_id)
    if not inbox:
        raise ValueError("Connect an inbox first - alerts are sent from one of your connected inboxes")

    try:
        mail = mail_for(inbox)
        result = await asyncio.to_thread(
            mail.send_email, to=to.strip(), subject=subject, body=body, from_name="Outbound agent"
        )
        sync_tokens(inbox, mail, db)
    except Exception as exc:
        logger.warning("notification.failed", to=to, inbox=inbox.email_address, error=str(exc))
        raise RuntimeError(f"Couldn't send the alert from {inbox.email_address}: {exc}")

    logger.info("notification.sent", to=to, inbox=inbox.email_address)
    return {"sent_from": inbox.email_address, "message_id": result["message_id"]}
