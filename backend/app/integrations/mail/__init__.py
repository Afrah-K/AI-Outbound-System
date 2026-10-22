"""Inbox providers: Gmail (OAuth + Gmail API) and SMTP/IMAP, behind one interface."""
from app.integrations.mail.base import MailProvider
from app.integrations.mail.credentials import MailCredentialsError
from app.integrations.mail.smtp_imap import MailConnectionError, SmtpImapService

PROVIDER_GMAIL = "gmail"
PROVIDER_SMTP = "smtp"


def provider_for(inbox) -> MailProvider:
    """The mail provider for an inbox - raises if its credentials can't be used."""
    if (inbox.provider or PROVIDER_GMAIL) == PROVIDER_SMTP:
        return SmtpImapService.from_inbox(inbox)

    from app.integrations.gmail.service import GmailService

    return GmailService(inbox.access_token, inbox.refresh_token, inbox.token_expiry)


def sync_tokens(inbox, provider: MailProvider) -> bool:
    """
    Copy refreshed OAuth tokens from the provider onto the inbox (the caller
    commits). Returns True if anything changed. A no-op for SMTP inboxes.
    """
    updated = provider.updated_tokens
    if not updated or updated.get("access_token") == inbox.access_token:
        return False
    inbox.access_token = updated["access_token"]
    inbox.token_expiry = updated["token_expiry"]
    return True


__all__ = [
    "MailProvider",
    "MailConnectionError",
    "MailCredentialsError",
    "SmtpImapService",
    "PROVIDER_GMAIL",
    "PROVIDER_SMTP",
    "provider_for",
    "sync_tokens",
]
