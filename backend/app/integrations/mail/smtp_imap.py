"""
SMTP/IMAP inbox provider: send over SMTP, read over IMAP - so any mail
account (Outlook, Zoho, cold-email inbox providers, a self-hosted server)
works everywhere a Gmail inbox does. Standard library only.

How Gmail concepts map onto plain IMAP:
- message id  = the RFC 5322 Message-ID header (what send_email returns too)
- thread id   = the Message-ID of the thread's first message, i.e. the first
  entry of a reply's References header (else In-Reply-To)
- labels      = the folder a message is in: INBOX, SENT, SPAM (the Junk
  folder), TRASH; plus UNREAD when it doesn't have the \\Seen flag
- a thread    = messages whose Message-ID, In-Reply-To or References point at
  it, in INBOX and Sent - plus bounce reports quoting one of its Message-IDs

Folders are found by their RFC 6154 special-use flag (\\Sent, \\Junk, \\Trash),
falling back to common names ("Sent Items", "Spam"...) for servers without it.
"""
import email
import imaplib
import re
import smtplib
import socket
import ssl
import threading
import time
from datetime import datetime, timedelta
from email import policy
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parsedate_to_datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

import structlog

logger = structlog.get_logger()

SECURITY_SSL = "ssl"            # implicit TLS - usually SMTP 465, IMAP 993
SECURITY_STARTTLS = "starttls"  # plain connect, then upgrade - usually SMTP 587, IMAP 143
SECURITY_OPTIONS = (SECURITY_SSL, SECURITY_STARTTLS)

DEFAULT_TIMEOUT = 30            # seconds, per network operation
THREAD_ROUNDS = 3               # how many hops of replies-to-replies get_thread follows
BOUNCE_LOOKBACK_DAYS = 60       # bounce reports are searched for this far back
MAX_IDS_PER_SEARCH = 20
MAX_OTHER_FOLDERS = 30          # folders searched (besides INBOX/Junk/Trash) when locating a message
SNIPPET_LENGTH = 200
SNIPPET_BYTES = 4096            # body bytes fetched to build a snippet without downloading the whole message

FOLDER_NAMES = {
    "sent": ("sent", "sent items", "sent messages", "sent mail", "sent-mail", "[gmail]/sent mail", "inbox.sent"),
    "junk": ("junk", "spam", "junk email", "junk e-mail", "junk mail", "bulk mail", "[gmail]/spam", "inbox.junk", "inbox.spam"),
    "trash": ("trash", "deleted items", "deleted messages", "bin", "[gmail]/trash", "inbox.trash"),
}
SPECIAL_USE_FLAGS = {"sent": "\\sent", "junk": "\\junk", "trash": "\\trash"}
FOLDER_LABELS = {"inbox": "INBOX", "sent": "SENT", "junk": "SPAM", "trash": "TRASH"}
LABEL_FOLDERS = {label: kind for kind, label in FOLDER_LABELS.items()}
SKIP_WHEN_LOCATING = ("\\sent", "\\drafts", "\\all", "\\noselect", "\\nonexistent")

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_MSGID_RE = re.compile(r"<[^<>\s]+>")
_LIST_RE = re.compile(rb'\((?P<flags>[^)]*)\)\s+(?P<delim>"(?:[^"\\]|\\.)*"|NIL)\s+(?P<name>.*)$', re.IGNORECASE)
_FETCH_START_RE = re.compile(rb"^\d+ \(")
_SECTION_RE = re.compile(rb"BODY\[([^\]]*)\](?:<\d+>)?\s*\{\d+\}\s*$", re.IGNORECASE)


class MailConnectionError(Exception):
    """
    Couldn't connect or log in to the SMTP or IMAP server. `server` is "SMTP" or
    "IMAP"; `reason` is one of auth, host, connect, timeout, tls.
    """

    def __init__(self, server: str, reason: str, message: str):
        super().__init__(message)
        self.server = server
        self.reason = reason


def _default_ssl_context() -> ssl.SSLContext:
    """Normal certificate and host name verification (tests swap in their own CA here)."""
    return ssl.create_default_context()


def _imap_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _imap_date(when: datetime) -> str:
    return f"{when.day:02d}-{_MONTHS[when.month - 1]}-{when.year}"


def _message_ids(value: Optional[str]) -> List[str]:
    return _MSGID_RE.findall(value or "")


def _normalize_id(message_id: str) -> str:
    message_id = (message_id or "").strip()
    if message_id and not message_id.startswith("<"):
        message_id = f"<{message_id.strip('<>')}>"
    return message_id


def _or(criteria: List[List[str]]) -> List[str]:
    """IMAP's OR takes two keys - nest it for more: OR a OR b c."""
    if len(criteria) == 1:
        return list(criteria[0])
    return ["OR", *criteria[0], *_or(criteria[1:])]


def _html_to_text(markup: str) -> str:
    from bs4 import BeautifulSoup

    return BeautifulSoup(markup, "html.parser").get_text("\n").strip()


def _explain(server: str, host: str, port: int, stage: str, exc: Exception) -> MailConnectionError:
    """A clear, password-free explanation of why connecting or logging in failed."""
    where = f"{host}:{port}"
    security_hint = "Use SSL on ports 465 (SMTP) / 993 (IMAP) and STARTTLS on 587 (SMTP) / 143 (IMAP)."
    imap_rejected = stage == "login" and isinstance(exc, imaplib.IMAP4.error) and not isinstance(exc, imaplib.IMAP4.abort)
    if isinstance(exc, smtplib.SMTPAuthenticationError) or imap_rejected:
        detail = exc.smtp_error.decode(errors="replace") if isinstance(exc, smtplib.SMTPAuthenticationError) else str(exc)
        detail = re.sub(r"^b'(.*)'$", r"\1", detail.strip())  # imaplib shows the server's reply as b'...'
        return MailConnectionError(
            server, "auth",
            f"{server} login failed - the server rejected the username or password ({detail.strip()}). "
            "Some providers need an app password instead of your normal password, or have SMTP/IMAP turned off by default.",
        )
    if isinstance(exc, socket.gaierror):
        return MailConnectionError(server, "host", f"{server} server '{host}' wasn't found - check the host name.")
    if isinstance(exc, ConnectionRefusedError):
        return MailConnectionError(server, "connect", f"{server} server {where} refused the connection - check the port.")
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return MailConnectionError(
            server, "timeout",
            f"{server} server {where} didn't respond - check the host, the port and the security setting. {security_hint}",
        )
    if isinstance(exc, ssl.SSLCertVerificationError):
        return MailConnectionError(server, "tls", f"{server} server {where} has a TLS certificate that couldn't be verified ({exc.verify_message}).")
    if isinstance(exc, ssl.SSLError):
        return MailConnectionError(
            server, "tls", f"TLS failed with the {server} server {where} ({exc.reason or exc}). {security_hint}"
        )
    if isinstance(exc, smtplib.SMTPNotSupportedError) or "STARTTLS" in str(exc).upper():
        return MailConnectionError(server, "tls", f"{server} server {where} doesn't offer STARTTLS on this port - try SSL. {security_hint}")
    if isinstance(exc, (smtplib.SMTPServerDisconnected, imaplib.IMAP4.abort, ConnectionResetError, EOFError)):
        return MailConnectionError(
            server, "connect", f"{server} server {where} closed the connection - check the port and the security setting. {security_hint}"
        )
    return MailConnectionError(server, "connect", f"Couldn't connect to the {server} server {where}: {exc}")


class SmtpImapService:
    """Implements the MailProvider interface (see base.py) over SMTP + IMAP."""

    def __init__(
        self,
        email_address: str,
        smtp_host: str,
        smtp_port: int,
        smtp_security: str,
        imap_host: str,
        imap_port: int,
        imap_security: str,
        username: str,
        password: str,
        ssl_context: Optional[ssl.SSLContext] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        for name, value in (("smtp_security", smtp_security), ("imap_security", imap_security)):
            if value not in SECURITY_OPTIONS:
                raise ValueError(f"{name} must be one of {', '.join(SECURITY_OPTIONS)}")
        self.email_address = email_address
        self.domain = email_address.rsplit("@", 1)[-1]
        self.smtp_host, self.smtp_port, self.smtp_security = smtp_host, int(smtp_port), smtp_security
        self.imap_host, self.imap_port, self.imap_security = imap_host, int(imap_port), imap_security
        self.username = username or email_address
        self._password = password
        self._ssl_context = ssl_context or _default_ssl_context()
        self._timeout = timeout
        self._imap: Optional[imaplib.IMAP4] = None
        self._folders: Optional[Dict[str, Optional[str]]] = None
        self._all_folders: List[Tuple[str, List[str]]] = []
        self._lock = threading.RLock()

    @classmethod
    def from_inbox(cls, inbox) -> "SmtpImapService":
        from app.integrations.mail.credentials import decrypt_password

        return cls(
            email_address=inbox.email_address,
            smtp_host=inbox.smtp_host,
            smtp_port=inbox.smtp_port,
            smtp_security=inbox.smtp_security,
            imap_host=inbox.imap_host,
            imap_port=inbox.imap_port,
            imap_security=inbox.imap_security,
            username=inbox.username or inbox.email_address,
            password=decrypt_password(inbox.password_encrypted),
        )

    def __repr__(self) -> str:  # never shows the password
        return f"<SmtpImapService {self.email_address} smtp={self.smtp_host}:{self.smtp_port} imap={self.imap_host}:{self.imap_port}>"

    @property
    def updated_tokens(self) -> Dict[str, Any]:
        return {}  # no OAuth tokens to refresh

    # ------------------------------------------------------------------
    # Connections
    # ------------------------------------------------------------------

    def _open_smtp(self) -> smtplib.SMTP:
        try:
            if self.smtp_security == SECURITY_SSL:
                conn = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=self._timeout, context=self._ssl_context)
            else:
                conn = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=self._timeout)
                conn.ehlo()
                conn.starttls(context=self._ssl_context)
                conn.ehlo()
        except Exception as exc:  # noqa: BLE001 - translated into a clear message
            raise _explain("SMTP", self.smtp_host, self.smtp_port, "connect", exc) from None
        try:
            conn.login(self.username, self._password)
        except Exception as exc:  # noqa: BLE001
            self._quietly(conn.quit)
            raise _explain("SMTP", self.smtp_host, self.smtp_port, "login", exc) from None
        return conn

    def _open_imap(self) -> imaplib.IMAP4:
        try:
            if self.imap_security == SECURITY_SSL:
                conn = imaplib.IMAP4_SSL(self.imap_host, self.imap_port, ssl_context=self._ssl_context, timeout=self._timeout)
            else:
                conn = imaplib.IMAP4(self.imap_host, self.imap_port, timeout=self._timeout)
                conn.starttls(ssl_context=self._ssl_context)
        except Exception as exc:  # noqa: BLE001
            raise _explain("IMAP", self.imap_host, self.imap_port, "connect", exc) from None
        try:
            conn.login(self.username, self._password)
        except Exception as exc:  # noqa: BLE001
            self._quietly(conn.logout)
            raise _explain("IMAP", self.imap_host, self.imap_port, "login", exc) from None
        return conn

    @staticmethod
    def _quietly(fn) -> None:
        try:
            fn()
        except Exception:  # noqa: BLE001 - closing a connection that's already gone
            pass

    def _with_imap(self, fn):
        """Run fn(conn) on a logged-in IMAP connection (reused across calls), reconnecting once if it dropped."""
        with self._lock:
            for attempt in (1, 2):
                if self._imap is None:
                    self._imap = self._open_imap()
                try:
                    return fn(self._imap)
                except (imaplib.IMAP4.abort, OSError):
                    self._quietly(self._imap.shutdown)
                    self._imap = None
                    if attempt == 2:
                        raise

    def close(self) -> None:
        with self._lock:
            if self._imap is not None:
                self._quietly(self._imap.logout)
                self._imap = None

    def __del__(self):
        # No LOGOUT round trip here: this can run on the event loop thread, so
        # just drop the socket (local only, never blocks)
        imap = getattr(self, "_imap", None)
        if imap is not None:
            self._quietly(imap.shutdown)

    # ------------------------------------------------------------------
    # Folders
    # ------------------------------------------------------------------

    def _folder(self, kind: str) -> Optional[str]:
        """The server's name for INBOX / the Sent, Junk or Trash folder (None if it has none)."""
        if kind == "inbox":
            return "INBOX"
        if self._folders is None:
            self._with_imap(self._discover_folders)
        return self._folders.get(kind)

    def _discover_folders(self, conn: imaplib.IMAP4) -> None:
        typ, data = conn.list()
        folders = []  # (name, lowercased flags)
        for item in data if typ == "OK" else []:
            if isinstance(item, tuple):  # name sent as a literal: (b'(\\Flags) "/" {10}', b'Sent Items')
                match = _LIST_RE.match(item[0].rstrip())
                name = item[1].decode("utf-8", errors="replace")
            elif isinstance(item, bytes):
                match = _LIST_RE.match(item.rstrip())
                if not match:
                    continue
                raw = match.group("name").decode("utf-8", errors="replace").strip()
                name = raw[1:-1].replace('\\"', '"').replace("\\\\", "\\") if raw.startswith('"') else raw
            else:
                continue
            if not match:
                continue
            delim = match.group("delim").decode(errors="replace").strip('"')
            flags = [f.lower() for f in match.group("flags").decode(errors="replace").split()]
            folders.append((name, flags, delim))

        found: Dict[str, Optional[str]] = {}
        for kind, flag in SPECIAL_USE_FLAGS.items():
            by_flag = next((name for name, flags, _ in folders if flag in flags and "\\noselect" not in flags), None)
            by_name = None
            if not by_flag:
                names = FOLDER_NAMES[kind]
                for name, flags, delim in folders:
                    if "\\noselect" in flags:
                        continue
                    lowered = name.lower()
                    leaf = lowered.rsplit(delim, 1)[-1] if delim else lowered
                    if lowered in names or leaf in names:
                        by_name = name
                        break
            found[kind] = by_flag or by_name
        self._folders = found
        self._all_folders = [(name, flags) for name, flags, _ in folders]

    def _select(self, conn: imaplib.IMAP4, folder: str) -> bool:
        typ, _ = conn.select(_imap_quote(folder), readonly=True)
        return typ == "OK"

    # ------------------------------------------------------------------
    # Searching and fetching
    # ------------------------------------------------------------------

    def _search(self, conn: imaplib.IMAP4, criteria: List[str]) -> List[bytes]:
        typ, data = conn.uid("SEARCH", *criteria)
        if typ != "OK" or not data or not data[0]:
            return []
        return data[0].split()

    def _fetch(self, conn: imaplib.IMAP4, uids: List[bytes], items: str) -> Dict[bytes, dict]:
        """UID FETCH; returns {uid: {"flags": [...], "internaldate": epoch|None, "sections": {kind: bytes}}}."""
        if not uids:
            return {}
        typ, data = conn.uid("FETCH", b",".join(uids).decode(), items)
        if typ != "OK":
            return {}
        records, current = [], None

        def scan(meta: bytes, record: dict) -> None:
            uid = re.search(rb"\bUID (\d+)", meta)
            if uid:
                record["uid"] = uid.group(1)
            flags = re.search(rb"\bFLAGS \(([^)]*)\)", meta)
            if flags:
                record["flags"] = flags.group(1).decode(errors="replace").split()
            internal = re.search(rb'INTERNALDATE "[^"]+"', meta)
            if internal:
                parsed = imaplib.Internaldate2tuple(internal.group(0))
                record["internaldate"] = time.mktime(parsed) if parsed else None

        for item in data or []:
            if isinstance(item, tuple):
                meta, literal = item[0], item[1]
                if _FETCH_START_RE.match(meta):
                    current = {"uid": None, "flags": [], "internaldate": None, "sections": {}}
                    records.append(current)
                if current is None:
                    continue
                scan(meta, current)
                section = _SECTION_RE.search(meta)
                if section is not None:
                    name = section.group(1).upper()
                    kind = "full" if not name else ("header" if name.startswith(b"HEADER") else "text")
                    current["sections"][kind] = literal
            elif isinstance(item, bytes) and item.strip():
                if _FETCH_START_RE.match(item):  # a response without any literal
                    current = {"uid": None, "flags": [], "internaldate": None, "sections": {}}
                    records.append(current)
                if current is not None:
                    scan(item, current)
        wanted = set(uids)
        return {r["uid"]: r for r in records if r["uid"] in wanted}

    def _parse(self, folder_kind: str, uid: bytes, record: dict, thread_id: Optional[str] = None, meta: Optional[dict] = None) -> Dict[str, Any]:
        """
        A fetched message as the same dict GmailService._parse_message returns.
        meta, if given, gets "depth": how many messages this one replies under.
        """
        sections = record["sections"]
        full = sections.get("full")
        raw = full if full is not None else sections.get("header", b"") + sections.get("text", b"")
        msg = email.message_from_bytes(raw, policy=policy.default)

        def header(name: str) -> str:
            try:
                return str(msg.get(name, "") or "").strip()
            except Exception:  # noqa: BLE001 - a malformed header shouldn't hide the message
                return ""

        message_id = _normalize_id(header("Message-ID")) or f"<uid-{uid.decode()}.{folder_kind}@imap.invalid>"
        references = header("References")
        refs, in_reply_to = _message_ids(references), _message_ids(header("In-Reply-To"))
        if meta is not None:
            meta["depth"] = len(set(refs) | set(in_reply_to))
        body = self._body_text(msg) if full is not None or "text" in sections else ""

        received = record.get("internaldate")
        if received is None:
            try:
                received = parsedate_to_datetime(header("Date")).timestamp()
            except (TypeError, ValueError, IndexError):
                received = None

        labels = [FOLDER_LABELS.get(folder_kind, folder_kind)]
        if "\\seen" not in {f.lower() for f in record.get("flags", [])}:
            labels.append("UNREAD")

        return {
            "id": message_id,
            "thread_id": thread_id or (refs[0] if refs else (in_reply_to[0] if in_reply_to else message_id)),
            "label_ids": labels,
            "from": header("From"),
            "to": header("To"),
            "subject": header("Subject"),
            "date": header("Date"),
            "internal_date": str(int(received * 1000)) if received is not None else None,
            "body": body if full is not None else "",
            "snippet": re.sub(r"\s+", " ", body).strip()[:SNIPPET_LENGTH],
            "message_id_header": message_id,
            "references": references,
        }

    @staticmethod
    def _body_text(msg: EmailMessage) -> str:
        """Prefer text/plain, else text/html with the tags stripped - like GmailService._extract_body."""
        try:
            part = msg.get_body(preferencelist=("plain", "html"))
            if part is None:
                return ""
            content = part.get_content().replace("\r\n", "\n")
            return _html_to_text(content) if part.get_content_subtype() == "html" else content
        except Exception:  # noqa: BLE001 - truncated (snippet-only) or malformed MIME
            try:
                payload = msg.get_payload(decode=True) or b""
                return payload.decode("utf-8", errors="replace").replace("\r\n", "\n")
            except Exception:  # noqa: BLE001
                return ""

    def _uids_for_ids(self, conn, folder: str, ids: Iterable[str], fields=("Message-ID", "In-Reply-To", "References")) -> List[bytes]:
        if not self._select(conn, folder):
            return []
        ids = list(ids)
        uids: List[bytes] = []
        for start in range(0, len(ids), MAX_IDS_PER_SEARCH):
            chunk = ids[start:start + MAX_IDS_PER_SEARCH]
            criteria = [["HEADER", field, _imap_quote(i)] for i in chunk for field in fields]
            for uid in self._search(conn, _or(criteria)):
                if uid not in uids:
                    uids.append(uid)
        return uids

    # ------------------------------------------------------------------
    # MailProvider
    # ------------------------------------------------------------------

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
        Send over SMTP, then save a copy to the Sent folder over IMAP. A
        follow-up in a thread (thread_id = the first message's Message-ID, or an
        explicit in_reply_to) gets In-Reply-To/References so it threads in the
        recipient's mail client.
        """
        msg = EmailMessage(policy=policy.SMTP)
        msg["From"] = Address(display_name=(from_name or "").strip(), addr_spec=self.email_address)
        msg["To"] = to
        msg["Subject"] = re.sub(r"[\r\n]+", " ", subject or "")
        msg["Date"] = formatdate(localtime=True)
        message_id = make_msgid(domain=self.domain)
        msg["Message-ID"] = message_id
        if reply_to:
            msg["Reply-To"] = reply_to

        parent = _normalize_id(in_reply_to) if in_reply_to else (_normalize_id(thread_id) if thread_id else "")
        if parent:
            chain = _message_ids(references) if in_reply_to else []
            if thread_id and _normalize_id(thread_id) not in chain:
                chain.insert(0, _normalize_id(thread_id))
            if parent not in chain:
                chain.append(parent)
            msg["In-Reply-To"] = parent
            msg["References"] = " ".join(chain)
            thread = chain[0]
        else:
            thread = message_id

        if html:
            msg.set_content(body, subtype="html")
        else:
            msg.set_content(body)

        conn = self._open_smtp()
        try:
            conn.send_message(msg, from_addr=self.email_address, to_addrs=[to])
        except smtplib.SMTPRecipientsRefused as exc:
            raise Exception(f"Failed to send email: the server refused the recipient {to} ({exc.recipients})") from None
        except smtplib.SMTPException as exc:
            raise Exception(f"Failed to send email: {exc}") from None
        finally:
            self._quietly(conn.quit)

        # The email is out - failing to file the Sent copy mustn't make it look unsent (that would resend it)
        try:
            self._with_imap(lambda imap: self._save_sent_copy(imap, msg, message_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("smtp.sent_copy_failed", inbox=self.email_address, error=str(exc))

        return {"message_id": message_id, "thread_id": thread, "label_ids": ["SENT"]}

    def _save_sent_copy(self, conn: imaplib.IMAP4, msg: EmailMessage, message_id: str) -> None:
        if self._folders is None:
            self._discover_folders(conn)
        folder = self._folders.get("sent")
        if not folder:
            typ, _ = conn.create(_imap_quote("Sent"))
            if typ != "OK":
                logger.warning("smtp.no_sent_folder", inbox=self.email_address)
                return
            folder = self._folders["sent"] = "Sent"
        # Some servers (Gmail, Microsoft 365...) already file mail sent over SMTP - don't add a duplicate
        if self._select(conn, folder) and self._search(conn, ["HEADER", "Message-ID", _imap_quote(message_id)]):
            return
        typ, data = conn.append(_imap_quote(folder), "(\\Seen)", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
        if typ != "OK":
            logger.warning("smtp.sent_copy_rejected", inbox=self.email_address, response=str(data)[:200])

    def get_thread(self, thread_id: str) -> List[Dict[str, Any]]:
        thread_id = _normalize_id(thread_id)

        def run(conn):
            sent = self._folder("sent")
            folders = [("inbox", "INBOX")] + ([("sent", sent)] if sent else [])
            known_ids, frontier = {thread_id}, {thread_id}
            hits: Dict[Tuple[str, bytes], str] = {}  # (folder kind, uid) -> folder name

            # Follow replies to replies: find messages pointing at known ids, then at theirs
            for _ in range(THREAD_ROUNDS):
                new_hits = []
                for kind, folder in folders:
                    for uid in self._uids_for_ids(conn, folder, frontier):
                        if (kind, uid) not in hits:
                            hits[(kind, uid)] = folder
                            new_hits.append((kind, folder, uid))
                frontier = set()
                for kind, folder in folders:
                    uids = [uid for k, _, uid in new_hits if k == kind]
                    if uids and self._select(conn, folder):
                        for record in self._fetch(conn, uids, "(UID BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])").values():
                            mid = _normalize_id(str(email.message_from_bytes(record["sections"].get("header", b""), policy=policy.default).get("Message-ID", "") or ""))
                            if mid and mid not in known_ids:
                                known_ids.add(mid)
                                frontier.add(mid)
                if not frontier:
                    break

            # Bounce reports quote the bounced message's Message-ID in their body, not in reply headers
            since = _imap_date(datetime.utcnow() - timedelta(days=BOUNCE_LOOKBACK_DAYS))
            if self._select(conn, "INBOX"):
                ids = sorted(known_ids)
                for start in range(0, len(ids), MAX_IDS_PER_SEARCH):
                    chunk = ids[start:start + MAX_IDS_PER_SEARCH]
                    criteria = ["SINCE", since, *_or([["BODY", _imap_quote(i)] for i in chunk])]
                    for uid in self._search(conn, criteria):
                        hits.setdefault(("inbox", uid), "INBOX")

            messages: Dict[str, Dict[str, Any]] = {}
            depth: Dict[str, int] = {}
            for kind, folder in folders:
                uids = [uid for (k, uid) in hits if k == kind]
                if not uids or not self._select(conn, folder):
                    continue
                for uid, record in self._fetch(conn, uids, "(UID FLAGS INTERNALDATE BODY.PEEK[])").items():
                    meta: dict = {}
                    parsed = self._parse(kind, uid, record, thread_id=thread_id, meta=meta)
                    existing = messages.get(parsed["id"])
                    if existing:  # e.g. mail to yourself: in both INBOX and Sent
                        existing["label_ids"] = list(dict.fromkeys(existing["label_ids"] + parsed["label_ids"]))
                    else:
                        messages[parsed["id"]] = parsed
                        depth[parsed["id"]] = meta["depth"]
            # Oldest first. IMAP times are to the second, so within one second a
            # reply goes after what it replies to (it references more of the thread)
            return sorted(messages.values(), key=lambda m: (int(m["internal_date"] or 0) // 1000, depth[m["id"]]))

        return self._with_imap(run)

    def _translate_query(self, query: str, label_ids: Optional[List[str]]) -> Tuple[str, List[str], Optional[float]]:
        """
        The Gmail-style searches the app uses ("in:inbox newer_than:30d",
        label_ids=["INBOX"]) as (folder kind, IMAP SEARCH criteria, cutoff epoch).
        """
        folder_kind, criteria, cutoff = "inbox", [], None
        for label in label_ids or []:
            if label == "UNREAD":
                criteria.append("UNSEEN")
            elif label in LABEL_FOLDERS:
                folder_kind = LABEL_FOLDERS[label]
            else:
                raise ValueError(f"Label {label} isn't supported for SMTP/IMAP inboxes")
        for token in (query or "").split():
            lowered = token.lower()
            age = re.fullmatch(r"newer_than:(\d+)([dmy])", lowered)
            if lowered.startswith("in:") and lowered[3:].upper() in LABEL_FOLDERS:
                folder_kind = LABEL_FOLDERS[lowered[3:].upper()]
            elif lowered in ("in:junk",):
                folder_kind = "junk"
            elif lowered == "is:unread":
                criteria.append("UNSEEN")
            elif lowered == "is:read":
                criteria.append("SEEN")
            elif age:
                days = int(age.group(1)) * {"d": 1, "m": 30, "y": 365}[age.group(2)]
                since = datetime.utcnow() - timedelta(days=days)
                criteria += ["SINCE", _imap_date(since)]
                cutoff = since.timestamp() if cutoff is None else max(cutoff, since.timestamp())
            else:
                raise ValueError(f"Search '{token}' isn't supported for SMTP/IMAP inboxes")
        return folder_kind, criteria or ["ALL"], cutoff

    def _list(self, query: str, max_results: int, label_ids: Optional[List[str]], items: str) -> List[Dict[str, Any]]:
        folder_kind, criteria, cutoff = self._translate_query(query, label_ids)

        def run(conn):
            folder = self._folder(folder_kind)
            if not folder or not self._select(conn, folder):
                return []
            uids = sorted(self._search(conn, criteria), key=int)[-max_results:]  # highest UIDs = newest
            fetched = self._fetch(conn, uids, items)
            messages = [self._parse(folder_kind, uid, fetched[uid]) for uid in uids if uid in fetched]
            if cutoff is not None:  # SINCE is per-day; newer_than is to the hour, as in Gmail
                messages = [m for m in messages if m["internal_date"] is None or int(m["internal_date"]) >= cutoff * 1000]
            # Newest first; within the same second, the later arrival (higher UID) first
            order = {id(m): i for i, m in enumerate(messages)}
            messages.sort(key=lambda m: (int(m["internal_date"] or 0), order[id(m)]), reverse=True)
            return messages

        return self._with_imap(run)

    def list_messages(self, query: str = "", max_results: int = 10, label_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        return self._list(query, max_results, label_ids, "(UID FLAGS INTERNALDATE BODY.PEEK[])")

    def list_message_metadata(self, query: str = "", max_results: int = 50, label_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        # Headers plus the first few KB of the body for the snippet - no full downloads
        fields = "FROM TO SUBJECT DATE MESSAGE-ID REFERENCES IN-REPLY-TO CONTENT-TYPE CONTENT-TRANSFER-ENCODING MIME-VERSION"
        return self._list(
            query, max_results, label_ids,
            f"(UID FLAGS INTERNALDATE BODY.PEEK[HEADER.FIELDS ({fields})] BODY.PEEK[TEXT]<0.{SNIPPET_BYTES}>)",
        )

    def get_rfc822_message_id(self, message_id: str) -> Optional[str]:
        # This provider's message ids already are the Message-ID header
        return _normalize_id(message_id) or None

    def find_labels_by_rfc822_id(self, rfc822_message_id: str) -> Optional[List[str]]:
        """
        ["INBOX"] / ["SPAM"] / ["TRASH"] - or another folder's name (placement
        "other") - for the message with this Message-ID; None if it hasn't arrived.
        """
        message_id = _normalize_id(rfc822_message_id)

        def run(conn):
            for kind in ("inbox", "junk", "trash"):
                folder = self._folder(kind)
                if folder and self._uids_for_ids(conn, folder, [message_id], fields=("Message-ID",)):
                    return [FOLDER_LABELS[kind]]
            known = {self._folder(k) for k in ("inbox", "junk", "trash", "sent")}
            others = [
                name for name, flags in self._all_folders
                if name not in known and name.upper() != "INBOX" and not any(f in flags for f in SKIP_WHEN_LOCATING)
            ]
            for folder in others[:MAX_OTHER_FOLDERS]:
                if self._uids_for_ids(conn, folder, [message_id], fields=("Message-ID",)):
                    return [folder]  # filed away by a rule - placement "other"
            return None

        return self._with_imap(run)

    def get_profile(self) -> Dict[str, Any]:
        """Log in to both servers (raises MailConnectionError saying which failed and why)."""
        smtp = self._open_smtp()
        self._quietly(smtp.quit)

        def run(conn):
            typ, data = conn.select("INBOX", readonly=True)
            total = int(data[0]) if typ == "OK" and data and data[0] and data[0].isdigit() else None
            return {"emailAddress": self.email_address, "messagesTotal": total, "threadsTotal": None}

        return self._with_imap(run)
