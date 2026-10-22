"""
Encryption for SMTP/IMAP inbox passwords at rest (Fernet), keyed by the
MAIL_CREDENTIALS_KEY setting. Passwords are decrypted only to log in to the
mail server - never logged or returned by the API.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

GENERATE_HINT = (
    'Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
)


class MailCredentialsError(RuntimeError):
    """The server can't encrypt or decrypt mail passwords - the message says why and what to do."""


def _fernet() -> Fernet:
    key = (settings.mail_credentials_key or "").strip()
    if not key:
        raise MailCredentialsError(
            "MAIL_CREDENTIALS_KEY is not set, so SMTP/IMAP inbox passwords can't be stored securely. "
            f"Add it to the backend's environment. {GENERATE_HINT}"
        )
    try:
        return Fernet(key)
    except (ValueError, TypeError):
        pass
    # Not a Fernet key - accept any long random secret (e.g. one a host generated)
    # and derive a Fernet key from it
    if len(key) < 32:
        raise MailCredentialsError(
            f"MAIL_CREDENTIALS_KEY must be a Fernet key or a random string of at least 32 characters. {GENERATE_HINT}"
        )
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))


def ensure_configured() -> None:
    """Raise MailCredentialsError now (e.g. before testing a login) if passwords couldn't be stored."""
    _fernet()


def encrypt_password(password: str) -> str:
    return _fernet().encrypt(password.encode()).decode()


def decrypt_password(token: str) -> str:
    if not token:
        raise MailCredentialsError("No password is saved for this inbox - update its credentials")
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise MailCredentialsError(
            "This inbox's saved password can't be decrypted - MAIL_CREDENTIALS_KEY has changed since it was saved. "
            "Re-enter the inbox's password to reconnect it."
        ) from None
