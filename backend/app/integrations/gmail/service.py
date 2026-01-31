"""Gmail service for sending and reading emails."""
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, List, Dict, Any
from datetime import datetime

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.integrations.gmail.oauth import get_valid_credentials


class GmailService:
    """Service for interacting with Gmail API."""

    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        token_expiry: Optional[datetime] = None,
    ):
        """
        Initialize Gmail service with credentials.

        Args:
            access_token: OAuth access token
            refresh_token: OAuth refresh token
            token_expiry: When the access token expires
        """
        self.credentials = get_valid_credentials(
            access_token, refresh_token, token_expiry
        )
        if not self.credentials:
            raise ValueError("Unable to get valid credentials")

        self._service = build("gmail", "v1", credentials=self.credentials)

    @property
    def updated_tokens(self) -> Dict[str, Any]:
        """Get updated tokens if they were refreshed."""
        return {
            "access_token": self.credentials.token,
            "token_expiry": self.credentials.expiry,
        }

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        from_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        thread_id: Optional[str] = None,
        html: bool = False,
    ) -> Dict[str, Any]:
        """
        Send an email via Gmail API.

        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body (plain text or HTML)
            from_name: Display name for the sender
            reply_to: Reply-to email address
            thread_id: Gmail thread ID for replies
            html: Whether the body is HTML

        Returns:
            Dict with message_id, thread_id, and label_ids
        """
        # Create message
        if html:
            message = MIMEMultipart("alternative")
            message.attach(MIMEText(body, "html"))
        else:
            message = MIMEText(body)

        message["to"] = to
        message["subject"] = subject

        if from_name:
            # Get sender's email from profile
            profile = self._service.users().getProfile(userId="me").execute()
            sender_email = profile["emailAddress"]
            message["from"] = f"{from_name} <{sender_email}>"

        if reply_to:
            message["reply-to"] = reply_to

        # Encode message
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        try:
            send_request = {"raw": raw}
            if thread_id:
                send_request["threadId"] = thread_id

            result = (
                self._service.users()
                .messages()
                .send(userId="me", body=send_request)
                .execute()
            )

            return {
                "message_id": result["id"],
                "thread_id": result["threadId"],
                "label_ids": result.get("labelIds", []),
            }
        except HttpError as e:
            raise Exception(f"Failed to send email: {e}")

    def get_message(self, message_id: str) -> Dict[str, Any]:
        """
        Get a specific email message.

        Args:
            message_id: Gmail message ID

        Returns:
            Dict with message details
        """
        try:
            message = (
                self._service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
            return self._parse_message(message)
        except HttpError as e:
            raise Exception(f"Failed to get message: {e}")

    def get_thread(self, thread_id: str) -> List[Dict[str, Any]]:
        """
        Get all messages in a thread.

        Args:
            thread_id: Gmail thread ID

        Returns:
            List of message dicts
        """
        try:
            thread = (
                self._service.users()
                .threads()
                .get(userId="me", id=thread_id, format="full")
                .execute()
            )
            return [self._parse_message(msg) for msg in thread.get("messages", [])]
        except HttpError as e:
            raise Exception(f"Failed to get thread: {e}")

    def check_for_replies(self, thread_id: str, sent_message_id: str) -> List[Dict[str, Any]]:
        """
        Check if there are any replies to a sent message.

        Args:
            thread_id: Gmail thread ID
            sent_message_id: The ID of the message we sent

        Returns:
            List of reply messages (excluding the original sent message)
        """
        messages = self.get_thread(thread_id)
        return [msg for msg in messages if msg["id"] != sent_message_id]

    def list_messages(
        self,
        query: str = "",
        max_results: int = 10,
        label_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        List messages matching a query.

        Args:
            query: Gmail search query (e.g., "is:unread", "from:user@example.com")
            max_results: Maximum number of messages to return
            label_ids: Filter by label IDs (e.g., ["INBOX", "UNREAD"])

        Returns:
            List of message dicts
        """
        try:
            request = self._service.users().messages().list(
                userId="me",
                q=query,
                maxResults=max_results,
                labelIds=label_ids,
            )
            results = request.execute()

            messages = []
            for msg in results.get("messages", []):
                full_msg = self.get_message(msg["id"])
                messages.append(full_msg)

            return messages
        except HttpError as e:
            raise Exception(f"Failed to list messages: {e}")

    def get_profile(self) -> Dict[str, Any]:
        """
        Get the authenticated user's Gmail profile.

        Returns:
            Dict with emailAddress, messagesTotal, threadsTotal, historyId
        """
        try:
            return self._service.users().getProfile(userId="me").execute()
        except HttpError as e:
            raise Exception(f"Failed to get profile: {e}")

    def _parse_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Parse a Gmail message into a cleaner format."""
        headers = {
            h["name"].lower(): h["value"]
            for h in message.get("payload", {}).get("headers", [])
        }

        # Get body
        body = ""
        payload = message.get("payload", {})
        if "body" in payload and payload["body"].get("data"):
            body = base64.urlsafe_b64decode(payload["body"]["data"]).decode()
        elif "parts" in payload:
            for part in payload["parts"]:
                if part["mimeType"] == "text/plain" and part["body"].get("data"):
                    body = base64.urlsafe_b64decode(part["body"]["data"]).decode()
                    break

        return {
            "id": message["id"],
            "thread_id": message["threadId"],
            "label_ids": message.get("labelIds", []),
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            "body": body,
            "snippet": message.get("snippet", ""),
        }
