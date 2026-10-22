"""SmtpImapService against local SMTP + IMAP servers (see mailserver.py)."""
import email
import time
from email import policy

import pytest

from app.integrations.mail.smtp_imap import MailConnectionError
from app.services.campaign_engine import _classify_thread
from app.services.placement import classify

ALICE = "alice@sender.test"     # our inbox
BOB = "bob@prospect.test"       # a prospect (also a mailbox on the test server)


def _parse(raw: bytes):
    return email.message_from_bytes(raw, policy=policy.default)


def _delivered_to(store, address):
    return [_parse(d["raw"]) for d in store.delivered if d["to"] == address]


@pytest.mark.parametrize("smtp,imap", [("ssl", "ssl"), ("starttls", "starttls")])
def test_send_delivers_and_saves_sent_copy(make_service, store, smtp, imap):
    alice = make_service(ALICE, smtp=smtp, imap=imap)
    store.add_account(BOB, "pw")

    result = alice.send_email(to=BOB, subject="Quick question", body="Hi Bob,\nAre you free?", from_name="Alice Smith")

    assert result["message_id"].startswith("<") and result["message_id"].endswith("@sender.test>")
    assert result["thread_id"] == result["message_id"]  # a new email starts its own thread
    assert result["label_ids"] == ["SENT"]

    [received] = _delivered_to(store, BOB)
    assert received["Message-ID"] == result["message_id"]
    assert received["From"] == "Alice Smith <alice@sender.test>"
    assert received["Subject"] == "Quick question"
    assert received.get_content().replace("\r\n", "\n").strip() == "Hi Bob,\nAre you free?"

    sent = store.accounts[ALICE].folders["Sent"].messages
    assert len(sent) == 1
    assert _parse(sent[0]["raw"])["Message-ID"] == result["message_id"]
    assert "\\Seen" in sent[0]["flags"]


def test_sent_copy_not_duplicated_when_server_files_it(make_service, store, monkeypatch):
    """Servers like Gmail/Microsoft 365 file SMTP-sent mail themselves - no second copy."""
    alice = make_service(ALICE)
    store.add_account(BOB, "pw")
    original_deliver = store.deliver

    def deliver_and_file(rcpt, raw, internaldate=None):
        store.accounts[ALICE].folders["Sent"].add(raw, {"\\Seen"})  # the server's own copy
        return original_deliver(rcpt, raw, internaldate)

    monkeypatch.setattr(store, "deliver", deliver_and_file)
    alice.send_email(to=BOB, subject="Hi", body="Hello")
    assert len(store.accounts[ALICE].folders["Sent"].messages) == 1


def test_sent_folder_found_by_name_without_special_use(make_service, store):
    """Servers without SPECIAL-USE: "Sent Items" is recognised by name."""
    alice = make_service(ALICE, special_use=False, names={"sent": "Sent Items", "junk": "Spam"})
    store.add_account(BOB, "pw")
    alice.send_email(to=BOB, subject="Hi", body="Hello")
    assert len(store.accounts[ALICE].folders["Sent Items"].messages) == 1


def test_follow_up_threads_with_in_reply_to_and_references(make_service, store):
    alice = make_service(ALICE)
    store.add_account(BOB, "pw")

    first = alice.send_email(to=BOB, subject="Quick question", body="Step 1")
    # How the campaign engine sends a follow-up: only the thread id it stored
    follow_up = alice.send_email(to=BOB, subject="Re: Quick question", body="Step 2", thread_id=first["thread_id"])

    assert follow_up["thread_id"] == first["message_id"]
    assert follow_up["message_id"] != first["message_id"]
    _, second = _delivered_to(store, BOB)
    assert second["In-Reply-To"] == first["message_id"]
    assert second["References"] == first["message_id"]


def test_reply_with_explicit_headers_extends_references(make_service, store):
    """How Unibox replies: in_reply_to = the last message, references = its References chain."""
    alice = make_service(ALICE)
    store.add_account(BOB, "pw")
    first = alice.send_email(to=BOB, subject="Hi", body="1")
    second = alice.send_email(to=BOB, subject="Re: Hi", body="2", thread_id=first["thread_id"])

    third = alice.send_email(
        to=BOB, subject="Re: Hi", body="3", thread_id=first["thread_id"],
        in_reply_to=second["message_id"], references=first["message_id"],
    )
    sent = _delivered_to(store, BOB)[-1]
    assert sent["In-Reply-To"] == second["message_id"]
    assert sent["References"].split() == [first["message_id"], second["message_id"]]
    assert third["thread_id"] == first["message_id"]


def test_reply_detection_through_get_thread(make_service, store):
    alice = make_service(ALICE)
    bob = make_service(BOB)

    first = alice.send_email(to=BOB, subject="Quick question", body="Are you free?", from_name="Alice")
    follow_up = alice.send_email(to=BOB, subject="Re: Quick question", body="Bumping this", thread_id=first["thread_id"])
    thread_id = first["thread_id"]

    # Nothing back yet: just our two sent messages, no reply
    before = alice.get_thread(thread_id)
    assert [m["id"] for m in before] == [first["message_id"], follow_up["message_id"]]
    assert all("SENT" in m["label_ids"] for m in before)
    assert _classify_thread(before, ALICE) is None

    # Bob replies to the follow-up from his own mail client (References carries the chain)
    time.sleep(1.1)  # INTERNALDATE has one-second resolution
    bob.send_email(
        to=ALICE, subject="Re: Quick question", body="Yes - Tuesday works.",
        in_reply_to=follow_up["message_id"], references=first["message_id"],
    )

    messages = alice.get_thread(thread_id)
    assert len(messages) == 3
    reply = messages[-1]
    assert reply["from"] == BOB and "INBOX" in reply["label_ids"] and "UNREAD" in reply["label_ids"]
    assert reply["body"].strip() == "Yes - Tuesday works."
    assert reply["thread_id"] == thread_id
    assert reply["message_id_header"] == reply["id"]
    assert [int(m["internal_date"]) for m in messages] == sorted(int(m["internal_date"]) for m in messages)

    event, msg = _classify_thread(messages, ALICE)
    assert event == "replied" and msg["id"] == reply["id"]


def test_reply_found_when_client_only_sets_in_reply_to(make_service, store):
    """Some clients send In-Reply-To without References - followed hop by hop."""
    alice = make_service(ALICE)
    store.add_account(BOB, "pw")
    first = alice.send_email(to=BOB, subject="Hi", body="1")
    follow_up = alice.send_email(to=BOB, subject="Re: Hi", body="2", thread_id=first["thread_id"])
    store.deliver(ALICE, (
        f"From: {BOB}\r\nTo: {ALICE}\r\nSubject: Re: Hi\r\nMessage-ID: <reply-1@prospect.test>\r\n"
        f"In-Reply-To: {follow_up['message_id']}\r\n\r\nSounds good\r\n"
    ).encode(), internaldate=time.time() + 5)

    messages = alice.get_thread(first["thread_id"])
    assert [m["id"] for m in messages][-1] == "<reply-1@prospect.test>"
    assert _classify_thread(messages, ALICE)[0] == "replied"


def test_bounce_report_detected_through_get_thread(make_service, store):
    alice = make_service(ALICE)
    store.add_account(BOB, "pw")
    first = alice.send_email(to=BOB, subject="Hi", body="Hello")
    # A delivery status notification: no reply headers, but it quotes the bounced message's headers
    store.deliver(ALICE, (
        "From: Mail Delivery Subsystem <mailer-daemon@sender.test>\r\n"
        f"To: {ALICE}\r\nSubject: Undelivered Mail Returned to Sender\r\n"
        "Message-ID: <dsn-1@sender.test>\r\nMIME-Version: 1.0\r\n"
        'Content-Type: multipart/report; report-type=delivery-status; boundary="b"\r\n\r\n'
        "--b\r\nContent-Type: text/plain\r\n\r\nThe address bob@prospect.test does not exist.\r\n"
        f"--b\r\nContent-Type: text/rfc822-headers\r\n\r\nMessage-ID: {first['message_id']}\r\nSubject: Hi\r\n"
        "--b--\r\n"
    ).encode())

    event, msg = _classify_thread(alice.get_thread(first["thread_id"]), ALICE)
    assert event == "bounced" and msg["id"] == "<dsn-1@sender.test>"


def test_unibox_listing(make_service, store):
    alice = make_service(ALICE)
    bob = make_service(BOB)
    first = alice.send_email(to=BOB, subject="Quick question", body="Are you free?")
    bob.send_email(
        to=ALICE, subject="Re: Quick question", body="Yes, Tuesday works for me. " * 20,
        in_reply_to=first["message_id"], references=first["message_id"], html=False,
    )
    # An HTML-only newsletter, and a message from two months ago
    store.deliver(ALICE, (
        "From: News <news@example.test>\r\nTo: alice@sender.test\r\nSubject: Weekly digest\r\n"
        "Message-ID: <news-1@example.test>\r\nMIME-Version: 1.0\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        "<html><body><p>Top <b>stories</b> this week</p></body></html>\r\n"
    ).encode())
    store.deliver(ALICE, b"From: old@example.test\r\nSubject: Old\r\nMessage-ID: <old-1@example.test>\r\n\r\nold\r\n",
                  internaldate=time.time() - 60 * 86400)

    # The queries Unibox actually makes
    metadata = alice.list_message_metadata(query="in:inbox newer_than:30d", max_results=50)
    assert [m["subject"] for m in metadata] == ["Weekly digest", "Re: Quick question"]  # newest first, old one excluded
    reply = metadata[1]
    assert reply["thread_id"] == first["thread_id"]  # groups with the campaign email's EmailLog row
    assert reply["from"] == BOB and "UNREAD" in reply["label_ids"] and "INBOX" in reply["label_ids"]
    assert reply["snippet"].startswith("Yes, Tuesday works for me.") and len(reply["snippet"]) <= 200
    assert reply["body"] == ""  # headers + snippet only
    assert metadata[0]["snippet"] == "Top stories this week"

    full = alice.list_messages(max_results=15, label_ids=["INBOX"])
    assert [m["subject"] for m in full] == ["Weekly digest", "Re: Quick question", "Old"]
    assert full[1]["body"].startswith("Yes, Tuesday works for me.")

    # Reading must not mark anything as read
    assert all("\\Seen" not in m["flags"] for m in store.accounts[ALICE].folders["INBOX"].messages)


def test_unsupported_query_is_rejected(make_service):
    alice = make_service(ALICE)
    with pytest.raises(ValueError, match="from:someone"):
        alice.list_messages(query="from:someone")


def test_placement_lookup_inbox_vs_junk(make_service, store):
    alice = make_service(ALICE)
    bob = make_service(BOB)

    to_inbox = alice.send_email(to=BOB, subject="Normal email", body="Hello")
    store.junk_rule = lambda raw: b"FREE MONEY" in raw
    to_junk = alice.send_email(to=BOB, subject="FREE MONEY", body="Click here")

    # The sender's id for a sent message already is its Message-ID
    assert alice.get_rfc822_message_id(to_inbox["message_id"]) == to_inbox["message_id"]

    assert bob.find_labels_by_rfc822_id(to_inbox["message_id"]) == ["INBOX"]
    assert classify(bob.find_labels_by_rfc822_id(to_inbox["message_id"])) == "inbox"
    assert bob.find_labels_by_rfc822_id(to_junk["message_id"]) == ["SPAM"]
    assert classify(bob.find_labels_by_rfc822_id(to_junk["message_id"])) == "spam"
    assert bob.find_labels_by_rfc822_id("<never-sent@sender.test>") is None


def test_placement_junk_folder_by_name_and_other_folders(make_service, store):
    alice = make_service(ALICE)
    bob = make_service(BOB, special_use=False, names={"junk": "Spam"})
    store.junk_rule = lambda raw: b"FREE MONEY" in raw
    to_junk = alice.send_email(to=BOB, subject="FREE MONEY", body="x")
    assert bob.find_labels_by_rfc822_id(to_junk["message_id"]) == ["SPAM"]

    # Filed into another folder by a rule -> placement "other"
    filed = alice.send_email(to=BOB, subject="Invoice", body="x")
    inbox = store.accounts[BOB].folders["INBOX"]
    message = inbox.messages.pop()
    store.accounts[BOB].folders["Archive"].messages.append(message)
    labels = bob.find_labels_by_rfc822_id(filed["message_id"])
    assert labels == ["Archive"] and classify(labels) == "other"


def test_get_profile_logs_in_to_both(make_service, store):
    alice = make_service(ALICE)
    store.deliver(ALICE, b"From: x@y.test\r\nSubject: s\r\n\r\nb\r\n")
    profile = alice.get_profile()
    assert profile["emailAddress"] == ALICE
    assert profile["messagesTotal"] == 1
    assert alice.updated_tokens == {}


def test_wrong_password_says_which_server(make_service, store):
    smtp_fails = make_service(ALICE, login_password="wrong")
    with pytest.raises(MailConnectionError) as err:
        smtp_fails.get_profile()
    assert err.value.server == "SMTP" and err.value.reason == "auth"
    assert "username or password" in str(err.value) and "wrong" not in str(err.value)

    # SMTP accepts it but IMAP doesn't (e.g. a separate IMAP password)
    imap_fails = make_service(ALICE)
    imap_fails._password = "wrong-for-imap"
    imap_fails._open_smtp = lambda: type("Ok", (), {"quit": lambda self: None})()
    with pytest.raises(MailConnectionError) as err:
        imap_fails.get_profile()
    assert err.value.server == "IMAP" and err.value.reason == "auth"
    assert "(AUTHENTICATIONFAILED" not in str(err.value) and "([AUTHENTICATIONFAILED] Invalid credentials)" in str(err.value)


def test_wrong_port_and_wrong_security_are_explained(make_service, server_settings, cert, store):
    from mailserver import client_context, free_port

    from app.integrations.mail.smtp_imap import SmtpImapService

    store.add_account(ALICE, "pw")
    base = dict(email_address=ALICE, username=ALICE, password="pw", ssl_context=client_context(cert), timeout=3)

    closed = SmtpImapService(**{**base, **server_settings(), "smtp_port": free_port()})
    with pytest.raises(MailConnectionError) as err:
        closed.get_profile()
    assert err.value.server == "SMTP" and err.value.reason == "connect" and "refused" in str(err.value)

    # SSL selected for a STARTTLS port: the TLS handshake fails, and the message says what to change
    mismatched = SmtpImapService(**{**base, **server_settings(smtp="starttls"), "smtp_security": "ssl"})
    with pytest.raises(MailConnectionError) as err:
        mismatched.get_profile()
    assert err.value.server == "SMTP" and err.value.reason in ("tls", "connect", "timeout")
    assert "STARTTLS on 587" in str(err.value)

    unknown_host = SmtpImapService(**{**base, **server_settings(), "imap_host": "no-such-host.invalid"})
    with pytest.raises(MailConnectionError) as err:
        unknown_host.get_profile()
    assert err.value.server == "IMAP" and err.value.reason == "host"


def test_untrusted_certificate_is_rejected(server_settings, store):
    """Real servers get normal certificate verification - a self-signed one fails clearly."""
    from app.integrations.mail.smtp_imap import SmtpImapService

    store.add_account(ALICE, "pw")
    service = SmtpImapService(email_address=ALICE, username=ALICE, password="pw", timeout=5, **server_settings())
    with pytest.raises(MailConnectionError) as err:
        service.get_profile()
    assert err.value.reason == "tls" and "certificate" in str(err.value)


def test_password_never_in_repr(make_service):
    service = make_service(ALICE)
    assert "correct horse" not in repr(service)
