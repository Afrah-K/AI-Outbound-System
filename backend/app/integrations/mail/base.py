"""
The interface every inbox provider implements (Gmail API, SMTP/IMAP), so
campaigns, warm-up, Unibox, the reply agent and placement checks work the
same whichever kind of inbox they use.

Message ids and thread ids are opaque strings owned by the provider: Gmail's
API ids for Gmail, RFC 5322 Message-IDs for SMTP/IMAP. They're stored as-is
in EmailLog.gmail_message_id / gmail_thread_id and handed back to the same
inbox's provider later.
"""
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class MailProvider(Protocol):
    @property
    def updated_tokens(self) -> Dict[str, Any]:
        """
        OAuth tokens to save back to the inbox if they were refreshed while in
        use ({"access_token", "token_expiry"}); empty for providers without tokens.
        """

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
        """Send an email; returns {"message_id", "thread_id", "label_ids"}."""

    def get_thread(self, thread_id: str) -> List[Dict[str, Any]]:
        """Every message in a thread (sent and received), oldest first, as parsed message dicts."""

    def list_messages(self, query: str = "", max_results: int = 10, label_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Newest messages matching a Gmail-style query / labels, with bodies."""

    def list_message_metadata(self, query: str = "", max_results: int = 50, label_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Like list_messages, headers and snippet only (cheaper)."""

    def get_rfc822_message_id(self, message_id: str) -> Optional[str]:
        """The Message-ID header of a message in this mailbox, by the provider's message id."""

    def find_labels_by_rfc822_id(self, rfc822_message_id: str) -> Optional[List[str]]:
        """
        Where a message landed in this mailbox, as Gmail-style labels ("INBOX",
        "SPAM", "CATEGORY_PROMOTIONS"...), or None if it hasn't arrived.
        """

    def get_profile(self) -> Dict[str, Any]:
        """Verify the connection; returns at least {"emailAddress"}."""


# The parsed message dict every provider returns (see GmailService._parse_message):
#   id, thread_id, label_ids, from, to, subject, date, internal_date (epoch ms
#   as a string), body, snippet, message_id_header, references
