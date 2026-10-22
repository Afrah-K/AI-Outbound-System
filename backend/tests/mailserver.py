"""
A local mail server for tests: an in-memory mail store, a small IMAP4rev1
server (the commands SmtpImapService uses - LOGIN, STARTTLS, LIST with
special-use flags, SELECT/EXAMINE, CREATE, APPEND, UID SEARCH, UID FETCH) and
an aiosmtpd SMTP server that delivers into the store. Both speak implicit TLS
or STARTTLS with a throwaway self-signed certificate.
"""
import email
import ipaddress
import re
import socket
import socketserver
import ssl
import threading
import time
from datetime import datetime, timedelta, timezone
from email import policy
from pathlib import Path
from typing import Callable, Dict, List, Optional

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword

# ---------------------------------------------------------------------------
# TLS
# ---------------------------------------------------------------------------


def make_certificate(directory: Path) -> Path:
    """A self-signed certificate + key for localhost / 127.0.0.1 (PEM, one file)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    path = directory / "localhost.pem"
    path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        + cert.public_bytes(serialization.Encoding.PEM)
    )
    return path


def server_context(cert: Path) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert)
    return ctx


def client_context(cert: Path) -> ssl.SSLContext:
    """What a client uses to trust the test certificate (normal verification, test CA)."""
    return ssl.create_default_context(cafile=str(cert))


# ---------------------------------------------------------------------------
# Mail store
# ---------------------------------------------------------------------------


class Folder:
    def __init__(self, name: str, flags: List[str]):
        self.name, self.flags = name, flags
        self.messages: List[dict] = []
        self.uidnext = 1

    def add(self, raw: bytes, flags=(), internaldate: Optional[float] = None) -> int:
        uid = self.uidnext
        self.uidnext += 1
        self.messages.append({"uid": uid, "raw": raw, "flags": set(flags), "internaldate": internaldate or time.time()})
        return uid


class Mailbox:
    def __init__(self, password: str, special_use: bool = True, names: Optional[Dict[str, str]] = None):
        names = {"sent": "Sent", "junk": "Junk", "trash": "Trash", **(names or {})}
        self.password = password
        self.folders: Dict[str, Folder] = {"INBOX": Folder("INBOX", [])}
        for kind, flag in (("sent", "\\Sent"), ("junk", "\\Junk"), ("trash", "\\Trash")):
            if names.get(kind):
                self.folders[names[kind]] = Folder(names[kind], [flag] if special_use else [])
        self.folders["Archive"] = Folder("Archive", [])

    def folder(self, name: str) -> Optional[Folder]:
        if name.upper() == "INBOX":
            return self.folders["INBOX"]
        return self.folders.get(name)


class MailStore:
    """Every test account's folders. junk_rule(raw) decides whether delivered mail goes to Junk."""

    def __init__(self):
        self.lock = threading.RLock()
        self.accounts: Dict[str, Mailbox] = {}
        self.junk_rule: Callable[[bytes], bool] = lambda raw: False
        self.delivered: List[dict] = []

    def add_account(self, address: str, password: str, **kwargs) -> Mailbox:
        with self.lock:
            self.accounts[address.lower()] = Mailbox(password, **kwargs)
            return self.accounts[address.lower()]

    def deliver(self, rcpt: str, raw: bytes, internaldate: Optional[float] = None) -> Optional[str]:
        with self.lock:
            account = self.accounts.get(rcpt.lower())
            if account is None:
                return None
            folder = "INBOX"
            if self.junk_rule(raw):
                folder = next((f.name for f in account.folders.values() if "\\Junk" in f.flags or f.name.lower() in ("junk", "spam")), "INBOX")
            account.folders[folder].add(raw, internaldate=internaldate)
            self.delivered.append({"to": rcpt, "folder": folder, "raw": raw})
            return folder


# ---------------------------------------------------------------------------
# IMAP
# ---------------------------------------------------------------------------

MONTHS = {m: i + 1 for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"))}


class _Literal(bytes):
    """A {n} literal argument."""


def _tokenize(data: bytes) -> list:
    """IMAP arguments: atoms, "quoted strings", (nested lists), {n} literals already inlined as _Literal."""
    tokens, stack, i = [], [], 0
    current = tokens
    while i < len(data):
        c = data[i:i + 1]
        if c == b" ":
            i += 1
        elif c == b"(":
            stack.append(current)
            current.append([])
            current = current[-1]
            i += 1
        elif c == b")":
            current = stack.pop()
            i += 1
        elif c == b'"':
            j, out = i + 1, bytearray()
            while data[j:j + 1] != b'"':
                if data[j:j + 1] == b"\\":
                    j += 1
                out += data[j:j + 1]
                j += 1
            current.append(bytes(out).decode())
            i = j + 1
        elif c == b"\x00":  # placeholder for a literal: \x00<index>\x00
            j = data.index(b"\x00", i + 1)
            current.append(("literal", int(data[i + 1:j])))
            i = j + 1
        else:
            m = re.match(rb"[^ ()\"\[]+(?:\[[^\]]*\](?:<[\d.]+>)?)?", data[i:])
            current.append(m.group(0).decode())
            i += len(m.group(0))
    return tokens


def _quote(value: str) -> bytes:
    return b'"' + value.replace("\\", "\\\\").replace('"', '\\"').encode() + b'"'


def _internaldate(ts: float) -> bytes:
    return time.strftime('"%d-%b-%Y %H:%M:%S +0000"', time.gmtime(ts)).encode()


def _header_block(raw: bytes) -> bytes:
    end = raw.find(b"\r\n\r\n")
    return raw[: end + 4] if end >= 0 else raw


def _body_block(raw: bytes) -> bytes:
    end = raw.find(b"\r\n\r\n")
    return raw[end + 4:] if end >= 0 else b""


def _header_values(raw: bytes, field: str) -> List[str]:
    msg = email.message_from_bytes(_header_block(raw), policy=policy.compat32)
    return [str(v) for v in msg.get_all(field, [])]


class IMAPHandler(socketserver.StreamRequestHandler):
    def setup(self):
        if self.server.implicit_tls:
            self.request = self.server.tls.wrap_socket(self.request, server_side=True)
        super().setup()
        self.account: Optional[Mailbox] = None
        self.selected: Optional[Folder] = None

    def send(self, line: bytes) -> None:
        self.wfile.write(line + b"\r\n")
        self.wfile.flush()

    def read_command(self) -> Optional[tuple]:
        line = self.rfile.readline()
        if not line:
            return None
        literals, data = [], bytearray()
        while True:
            line = line.rstrip(b"\r\n")
            m = re.search(rb"\{(\d+)\+?\}$", line)
            if not m:
                data += line
                break
            data += line[: m.start()] + b"\x00%d\x00" % len(literals)
            self.send(b"+ Ready for literal data")
            literals.append(self.rfile.read(int(m.group(1))))
            line = self.rfile.readline()
        tag, _, rest = bytes(data).partition(b" ")
        command, _, args = rest.partition(b" ")
        return tag, command.upper().decode(), _tokenize(args), literals

    def handle(self):
        self.send(b"* OK [CAPABILITY IMAP4rev1 SPECIAL-USE STARTTLS] test server ready")
        while True:
            try:
                parsed = self.read_command()
            except (ConnectionError, OSError, ssl.SSLError):
                return
            if parsed is None:
                return
            tag, command, args, literals = parsed
            if command == "UID" and args:
                command, args = "UID " + args[0].upper(), args[1:]
            handler = getattr(self, "do_" + command.replace(" ", "_"), None)
            if handler is None:
                self.send(tag + b" BAD unknown command")
                continue
            try:
                if handler(tag, args, literals) == "logout":
                    return
            except Exception as exc:  # noqa: BLE001 - report like a server would
                self.send(tag + b" BAD " + str(exc).encode()[:200])

    # -- connection state ------------------------------------------------
    def do_CAPABILITY(self, tag, args, literals):
        self.send(b"* CAPABILITY IMAP4rev1 SPECIAL-USE STARTTLS")
        self.send(tag + b" OK CAPABILITY completed")

    def do_NOOP(self, tag, args, literals):
        self.send(tag + b" OK NOOP completed")

    def do_LOGOUT(self, tag, args, literals):
        self.send(b"* BYE logging out")
        self.send(tag + b" OK LOGOUT completed")
        return "logout"

    def do_STARTTLS(self, tag, args, literals):
        self.send(tag + b" OK Begin TLS negotiation now")
        self.request = self.server.tls.wrap_socket(self.request, server_side=True)
        self.rfile = self.request.makefile("rb")
        self.wfile = self.request.makefile("wb")

    def do_LOGIN(self, tag, args, literals):
        user, password = [literals[a[1]].decode() if isinstance(a, tuple) else a for a in args[:2]]
        account = self.server.store.accounts.get(user.lower())
        if account is None or account.password != password:
            self.send(tag + b" NO [AUTHENTICATIONFAILED] Invalid credentials")
            return
        self.account = account
        self.send(tag + b" OK LOGIN completed")

    # -- folders -----------------------------------------------------------
    def do_LIST(self, tag, args, literals):
        for folder in self.account.folders.values():
            flags = " ".join(["\\HasNoChildren"] + folder.flags)
            self.send(b"* LIST (" + flags.encode() + b') "/" ' + _quote(folder.name))
        self.send(tag + b" OK LIST completed")

    def do_SELECT(self, tag, args, literals, readonly=False):
        folder = self.account.folder(args[0])
        if folder is None:
            self.selected = None
            self.send(tag + b" NO [NONEXISTENT] No such mailbox")
            return
        self.selected = folder
        self.send(b"* %d EXISTS" % len(folder.messages))
        self.send(b"* 0 RECENT")
        self.send(b"* OK [UIDVALIDITY 1] UIDs valid")
        self.send(b"* OK [UIDNEXT %d] Predicted next UID" % folder.uidnext)
        self.send(tag + (b" OK [READ-ONLY] EXAMINE completed" if readonly else b" OK [READ-WRITE] SELECT completed"))

    def do_EXAMINE(self, tag, args, literals):
        self.do_SELECT(tag, args, literals, readonly=True)

    def do_CREATE(self, tag, args, literals):
        name = args[0]
        if self.account.folder(name) is None:
            self.account.folders[name] = Folder(name, [])
        self.send(tag + b" OK CREATE completed")

    def do_APPEND(self, tag, args, literals):
        folder = self.account.folder(args[0])
        if folder is None:
            self.send(tag + b" NO [TRYCREATE] No such mailbox")
            return
        flags = next((a for a in args[1:] if isinstance(a, list)), [])
        raw = literals[args[-1][1]]
        with self.server.store.lock:
            uid = folder.add(raw, flags)
        self.send(tag + b" OK [APPENDUID 1 %d] APPEND completed" % uid)

    # -- search ------------------------------------------------------------
    def _matches(self, msg: dict, keys: list) -> bool:
        def parse(i):
            key = keys[i].upper() if isinstance(keys[i], str) else keys[i]
            if isinstance(key, list):
                return self._matches(msg, key), i + 1
            if key == "ALL":
                return True, i + 1
            if key == "UNSEEN":
                return "\\Seen" not in msg["flags"], i + 1
            if key == "SEEN":
                return "\\Seen" in msg["flags"], i + 1
            if key == "SINCE":
                d = datetime.strptime(keys[i + 1], "%d-%b-%Y").date()
                return datetime.utcfromtimestamp(msg["internaldate"]).date() >= d, i + 2
            if key == "HEADER":
                field, needle = keys[i + 1], keys[i + 2].lower()
                return any(needle in v.lower() for v in _header_values(msg["raw"], field)), i + 3
            if key == "BODY":
                return keys[i + 1].lower().encode() in _body_block(msg["raw"]).lower(), i + 2
            if key == "OR":
                a, j = parse(i + 1)
                b, k = parse(j)
                return a or b, k
            raise ValueError(f"unsupported search key {key}")

        i, result = 0, True
        while i < len(keys):
            ok, i = parse(i)
            result = result and ok
        return result

    def do_UID_SEARCH(self, tag, args, literals):
        if self.selected is None:
            self.send(tag + b" BAD no mailbox selected")
            return
        with self.server.store.lock:
            uids = [str(m["uid"]) for m in self.selected.messages if self._matches(m, args)]
        self.send(b"* SEARCH" + (b" " + " ".join(uids).encode() if uids else b""))
        self.send(tag + b" OK SEARCH completed")

    # -- fetch -------------------------------------------------------------
    def do_UID_FETCH(self, tag, args, literals):
        wanted = set()
        for part in args[0].split(","):
            if ":" in part:
                lo, hi = part.split(":")
                wanted.update(range(int(lo), 10 ** 9 if hi == "*" else int(hi) + 1))
            else:
                wanted.add(int(part))
        items = args[1] if isinstance(args[1], list) else [args[1]]
        for seq, msg in enumerate(self.selected.messages, start=1):
            if msg["uid"] not in wanted:
                continue
            parts, literal_parts = [b"UID %d" % msg["uid"]], []
            for item in items:
                upper = item.upper()
                if upper == "FLAGS":
                    parts.append(b"FLAGS (" + " ".join(sorted(msg["flags"])).encode() + b")")
                elif upper == "INTERNALDATE":
                    parts.append(b"INTERNALDATE " + _internaldate(msg["internaldate"]))
                elif upper.startswith("BODY"):
                    section = re.match(r"BODY(?:\.PEEK)?\[([^\]]*)\](?:<(\d+)\.(\d+)>)?", item, re.I)
                    spec, start, length = section.group(1), section.group(2), section.group(3)
                    raw = msg["raw"]
                    if spec == "":
                        data = raw
                    elif spec.upper() == "TEXT":
                        data = _body_block(raw)
                    elif spec.upper().startswith("HEADER.FIELDS"):
                        fields = spec[spec.index("(") + 1: spec.index(")")].split()
                        msg_obj = email.message_from_bytes(_header_block(raw), policy=policy.compat32)
                        lines = b""
                        for k, v in msg_obj.items():
                            if k.upper() in [f.upper() for f in fields]:
                                lines += f"{k}: {v}\r\n".encode()
                        data = lines + b"\r\n"
                    else:
                        data = _header_block(raw)
                    label = f"BODY[{spec}]" + (f"<{start}>" if start is not None else "")
                    if start is not None:
                        data = data[int(start): int(start) + int(length)]
                    literal_parts.append((label.encode(), data))
            self._send_fetch(seq, parts, literal_parts)
        self.send(tag + b" OK FETCH completed")

    def _send_fetch(self, seq: int, parts: List[bytes], literal_parts: List[tuple]) -> None:
        line = b"* %d FETCH (" % seq + b" ".join(parts)
        for label, data in literal_parts:
            line += b" " + label + b" {%d}\r\n" % len(data) + data
        self.wfile.write(line + b")\r\n")
        self.wfile.flush()


class IMAPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, store: MailStore, tls: ssl.SSLContext, implicit_tls: bool):
        self.store, self.tls, self.implicit_tls = store, tls, implicit_tls
        super().__init__(("127.0.0.1", 0), IMAPHandler)
        self.port = self.server_address[1]
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.shutdown()
        self.server_close()


# ---------------------------------------------------------------------------
# SMTP
# ---------------------------------------------------------------------------


class DeliveryHandler:
    def __init__(self, store: MailStore):
        self.store = store

    async def handle_DATA(self, server, session, envelope):
        raw = envelope.original_content or envelope.content
        if isinstance(raw, str):
            raw = raw.encode()
        raw = raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        for rcpt in envelope.rcpt_tos:
            self.store.deliver(rcpt, raw)
        return "250 Message accepted for delivery"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class SMTPServer:
    """aiosmtpd with LOGIN/PLAIN auth checked against the store; implicit TLS or STARTTLS."""

    def __init__(self, store: MailStore, tls: ssl.SSLContext, implicit_tls: bool):
        def authenticator(server, session, envelope, mechanism, auth_data):
            if isinstance(auth_data, LoginPassword):
                account = store.accounts.get(auth_data.login.decode().lower())
                ok = bool(account and account.password == auth_data.password.decode())
                # handled=False: aiosmtpd then sends the standard 535 reply itself
                return AuthResult(success=ok, handled=False)
            return AuthResult(success=False, handled=False)

        self.port = free_port()
        kwargs = dict(authenticator=authenticator, auth_required=True)
        if implicit_tls:
            kwargs.update(ssl_context=tls, auth_require_tls=False)
        else:
            kwargs.update(tls_context=tls, require_starttls=True)
        self.controller = Controller(
            DeliveryHandler(store), hostname="127.0.0.1", port=self.port, server_hostname="localhost", **kwargs
        )
        self.controller.start()

    def stop(self) -> None:
        self.controller.stop()
