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
        in_reply_to: Optional[str] = None,
        references: Optional[str] = None,
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
            in_reply_to: Message-ID header of the message being replied to
            references: References header chain, so the recipient's client threads the reply

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

        if in_reply_to:
            message["In-Reply-To"] = in_reply_to
            message["References"] = f"{references} {in_reply_to}".strip() if references else in_reply_to

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

    def get_rfc822_message_id(self, message_id: str) -> Optional[str]:
        """The Message-ID header of a message in this mailbox (e.g. one just sent)."""
        try:
            msg = (
                self._service.users().messages()
                .get(userId="me", id=message_id, format="metadata", metadataHeaders=["Message-ID"])
                .execute()
            )
        except HttpError as e:
            raise Exception(f"Failed to read message headers: {e}")
        for header in msg.get("payload", {}).get("headers", []):
            if header.get("name", "").lower() == "message-id":
                return header.get("value")
        return None

    def find_labels_by_rfc822_id(self, rfc822_message_id: str) -> Optional[List[str]]:
        """
        Labels of the message with this Message-ID in this mailbox - including
        Spam and Trash - or None if it hasn't arrived (yet).
        """
        query = f"rfc822msgid:{rfc822_message_id.strip().strip('<>')}"
        try:
            found = (
                self._service.users().messages()
                .list(userId="me", q=query, includeSpamTrash=True, maxResults=5)
                .execute()
            )
            messages = found.get("messages", [])
            if not messages:
                return None
            msg = self._service.users().messages().get(userId="me", id=messages[0]["id"], format="minimal").execute()
            return msg.get("labelIds", [])
        except HttpError as e:
            raise Exception(f"Failed to search mailbox: {e}")

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

    def list_message_metadata(
        self,
        query: str = "",
        max_results: int = 50,
        label_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Like list_messages, but fetches only headers + snippet (no bodies) -
        much cheaper when scanning an inbox for which messages matter.
        """
        try:
            results = self._service.users().messages().list(
                userId="me",
                q=query,
                maxResults=max_results,
                labelIds=label_ids,
            ).execute()

            ids = [m["id"] for m in results.get("messages", [])]
            fetched = {}
            errors = []

            def collect(request_id, response, exception):
                if exception is not None:
                    errors.append(exception)
                else:
                    fetched[request_id] = response

            # One HTTP round trip per 100 messages (Gmail's batch limit) instead of one request each.
            for start in range(0, len(ids), 100):
                batch = self._service.new_batch_http_request(callback=collect)
                for message_id in ids[start:start + 100]:
                    batch.add(
                        self._service.users().messages().get(
                            userId="me",
                            id=message_id,
                            format="metadata",
                            metadataHeaders=["From", "To", "Subject", "Date", "Message-ID"],
                        ),
                        request_id=message_id,
                    )
                batch.execute()
            if errors and not fetched:
                raise errors[0]

            return [self._parse_message(fetched[i]) for i in ids if i in fetched]
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

        body = self._extract_body(message.get("payload", {}))

        return {
            "id": message["id"],
            "thread_id": message["threadId"],
            "label_ids": message.get("labelIds", []),
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            # Epoch ms as a string - the only reliable way to sort messages by
            # time; the "date" header is an RFC 2822 string that doesn't sort
            # correctly as plain text.
            "internal_date": message.get("internalDate"),
            "body": body,
            "snippet": message.get("snippet", ""),
            # RFC Message-ID / References headers - needed to thread a reply in the recipient's client.
            "message_id_header": headers.get("message-id", ""),
            "references": headers.get("references", ""),
        }

    @staticmethod
    def _decode_part(part: Dict[str, Any]) -> str:
        data = part.get("body", {}).get("data")
        if not data:
            return ""
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    def _extract_body(self, payload: Dict[str, Any]) -> str:
        """
        Find the readable body anywhere in a (possibly nested) MIME tree:
        prefer text/plain, else text/html with the tags stripped. Real replies
        are usually multipart/alternative nested inside multipart/mixed.
        """
        plain, html = [], []

        def walk(part):
            mime = part.get("mimeType", "")
            if mime == "text/plain":
                plain.append(self._decode_part(part))
            elif mime == "text/html":
                html.append(self._decode_part(part))
            for child in part.get("parts", []) or []:
                walk(child)

        walk(payload)
        text = next((t for t in plain if t.strip()), "")
        if text:
            return text
        markup = next((h for h in html if h.strip()), "")
        if markup:
            from bs4 import BeautifulSoup
            return BeautifulSoup(markup, "html.parser").get_text("\n").strip()
        return self._decode_part(payload)
