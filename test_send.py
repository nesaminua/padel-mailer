import os
import smtplib

os.environ.update(GMAIL_USER="a@gmail.com", GMAIL_APP_PASSWORD="aaaa bbbb", SHEET_ID="s",
                  GMAIL_USER_2="b@gmail.com", GMAIL_APP_PASSWORD_2="cccc dddd", DAILY="450", DAILY_2="100")

import send  # noqa: E402

ROW = [""] * 5 + ["club@x.es"] + [""] * 5 + ["Subject\r\nBcc: evil@x.com", "Body"]


def test_extra_account_reads_its_own_cap_and_replies_go_to_main():
    assert [(u, d) for u, _, d in send.ACCOUNTS] == [("a@gmail.com", 450), ("b@gmail.com", 100)]
    msg = send.message(ROW, "b@gmail.com")
    assert msg["Reply-To"] == "a@gmail.com" and "b@gmail.com" in msg["From"]


def test_sheet_values_cannot_inject_headers_or_recipients():
    msg = send.message(ROW, "a@gmail.com")
    assert "\n" not in msg["Subject"] and msg["Bcc"] is None
    for bad in ["x,y@z.com", "<a>@b.com", "a b@c.com", "a@b.com\nbcc:c@d.com"]:
        assert not send.EMAIL.match(bad)
    assert send.EMAIL.match("info@club-padel.es")


def test_failed_login_skips_only_that_account(monkeypatch):
    def boom(*a, **k):
        raise smtplib.SMTPAuthenticationError(535, b"bad")
    monkeypatch.setattr(send.smtplib, "SMTP_SSL", boom)
    assert send.send_batch(2, "b@gmail.com", "x", [(5, ROW)]) == 0
