"""Gmail OAuth service for handling authentication flow."""
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from datetime import datetime, timedelta
from typing import Optional, Tuple
import secrets

from app.config import settings

# OAuth scopes required for sending emails and reading inbox
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
]

# Store state tokens temporarily (in production, use Redis or database)
_state_tokens: dict[str, datetime] = {}


def create_oauth_flow() -> Flow:
    """Create a Google OAuth flow instance."""
    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }

    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=settings.google_redirect_uri,
    )

    return flow


def generate_auth_url() -> Tuple[str, str]:
    """
    Generate the OAuth authorization URL.

    Returns:
        Tuple of (auth_url, state_token)
    """
    flow = create_oauth_flow()

    # Generate a secure state token
    state = secrets.token_urlsafe(32)
    _state_tokens[state] = datetime.utcnow()

    # Clean up old state tokens (older than 10 minutes)
    _cleanup_state_tokens()

    auth_url, _ = flow.authorization_url(
        access_type="offline",  # Get refresh token
        prompt="consent",  # Force consent to always get refresh token
        state=state,
    )

    return auth_url, state


def validate_state_token(state: str) -> bool:
    """Validate that the state token is valid and not expired."""
    if state not in _state_tokens:
        return False

    created_at = _state_tokens[state]
    # State tokens are valid for 10 minutes
    if datetime.utcnow() - created_at > timedelta(minutes=10):
        del _state_tokens[state]
        return False

    # Remove used state token
    del _state_tokens[state]
    return True


def exchange_code_for_tokens(code: str) -> dict:
    """
    Exchange authorization code for access and refresh tokens.

    Args:
        code: The authorization code from Google

    Returns:
        Dict containing access_token, refresh_token, token_expiry, and email
    """
    flow = create_oauth_flow()
    flow.fetch_token(code=code)

    credentials = flow.credentials

    # Get user's email address
    from googleapiclient.discovery import build
    service = build("oauth2", "v2", credentials=credentials)
    user_info = service.userinfo().get().execute()
    email = user_info.get("email")

    return {
        "access_token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_expiry": credentials.expiry,
        "email": email,
    }


def refresh_access_token(refresh_token: str) -> Optional[dict]:
    """
    Refresh an expired access token.

    Args:
        refresh_token: The refresh token stored for the user

    Returns:
        Dict with new access_token and token_expiry, or None if refresh failed
    """
    try:
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
        )

        credentials.refresh(Request())

        return {
            "access_token": credentials.token,
            "token_expiry": credentials.expiry,
        }
    except Exception as e:
        print(f"Failed to refresh token: {e}")
        return None


def get_valid_credentials(
    access_token: str,
    refresh_token: str,
    token_expiry: Optional[datetime],
) -> Optional[Credentials]:
    """
    Get valid credentials, refreshing if necessary.

    Args:
        access_token: Current access token
        refresh_token: Refresh token for getting new access tokens
        token_expiry: When the access token expires

    Returns:
        Valid Credentials object or None if unable to get valid credentials
    """
    credentials = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        expiry=token_expiry,
    )

    # Check if token needs refresh
    if credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except Exception as e:
            print(f"Failed to refresh credentials: {e}")
            return None

    return credentials


def _cleanup_state_tokens():
    """Remove expired state tokens."""
    now = datetime.utcnow()
    expired = [
        state for state, created_at in _state_tokens.items()
        if now - created_at > timedelta(minutes=10)
    ]
    for state in expired:
        del _state_tokens[state]
