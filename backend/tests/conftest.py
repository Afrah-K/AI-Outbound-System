"""
Test setup: a throwaway SQLite database and mail-credentials key (set before
the app is imported), plus local SMTP + IMAP servers - implicit TLS and
STARTTLS variants - sharing one in-memory mail store.
"""
import os
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

_TMP = Path(tempfile.mkdtemp(prefix="outbound-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["MAIL_CREDENTIALS_KEY"] = Fernet.generate_key().decode()
os.environ["INITIAL_OWNER_EMAIL"] = ""
os.environ["BACKGROUND_WORKER"] = "external"

sys.path.insert(0, str(Path(__file__).parent))

import pytest  # noqa: E402

from mailserver import IMAPServer, MailStore, SMTPServer, client_context, make_certificate, server_context  # noqa: E402

PASSWORD = "correct horse battery staple"


@pytest.fixture(scope="session")
def cert():
    return make_certificate(_TMP)


@pytest.fixture(scope="session")
def mail_servers(cert):
    store = MailStore()
    tls = server_context(cert)
    servers = {
        "smtp_ssl": SMTPServer(store, tls, implicit_tls=True),
        "smtp_starttls": SMTPServer(store, tls, implicit_tls=False),
        "imap_ssl": IMAPServer(store, tls, implicit_tls=True),
        "imap_starttls": IMAPServer(store, tls, implicit_tls=False),
    }
    yield store, servers
    for server in servers.values():
        server.stop()


@pytest.fixture
def store(mail_servers):
    store, _ = mail_servers
    with store.lock:
        store.accounts.clear()
        store.delivered.clear()
        store.junk_rule = lambda raw: False
    return store


@pytest.fixture
def trust_test_cert(cert, monkeypatch):
    """Services created without an explicit ssl_context (e.g. from an Inbox row) trust the test certificate."""
    from app.integrations.mail import smtp_imap

    monkeypatch.setattr(smtp_imap, "_default_ssl_context", lambda: client_context(cert))


@pytest.fixture
def server_settings(mail_servers):
    """Connection settings for an inbox on the test servers: settings(smtp="ssl"|"starttls", imap=...)."""
    _, servers = mail_servers

    def settings(smtp: str = "ssl", imap: str = "ssl") -> dict:
        return {
            "smtp_host": "127.0.0.1",
            "smtp_port": servers[f"smtp_{smtp}"].port,
            "smtp_security": smtp,
            "imap_host": "127.0.0.1",
            "imap_port": servers[f"imap_{imap}"].port,
            "imap_security": imap,
        }

    return settings


@pytest.fixture
def make_service(store, server_settings, cert):
    """make_service("a@x.test") -> a SmtpImapService for a new test account (created in the store)."""
    from app.integrations.mail.smtp_imap import SmtpImapService

    created = []

    def make(address: str, password: str = PASSWORD, smtp: str = "ssl", imap: str = "ssl", login_password=None, **account):
        if address.lower() not in store.accounts:
            store.add_account(address, password, **account)
        service = SmtpImapService(
            email_address=address,
            username=address,
            password=login_password if login_password is not None else password,
            ssl_context=client_context(cert),
            timeout=10,
            **server_settings(smtp, imap),
        )
        created.append(service)
        return service

    yield make
    for service in created:
        service.close()
