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


def test_run_with_nothing_sent_reports_idle_not_success(monkeypatch):
    row = [""] * 5 + ["club@x.es", "email", "not sent", "", "", "", "S", "B"]
    monkeypatch.setattr(send, "load", lambda: [(2, row)])
    monkeypatch.setattr(send, "check_bounces", lambda rows: True)
    monkeypatch.setattr(send, "send_batch", lambda *a: 0)
    try:
        send.main()
    except SystemExit as e:
        assert e.code == send.IDLE
    else:
        raise AssertionError("a run that sent nothing must exit IDLE, or the loop retries Gmail every 30 s")


def test_bounce_stop_needs_100_sends_and_more_than_5_percent(monkeypatch):
    def rows(n_sent):
        return [(i + 2, [""] * 5 + [f"c{i}@x.es", "email", "sent", "", "email sent (auto, Gmail)"] + [""] * 3)
                for i in range(n_sent)]
    two_bounces = lambda sent: {"c0@x.es", "c1@x.es"}
    monkeypatch.setattr(send, "bounced_addresses", two_bounces)
    monkeypatch.setattr(send, "write", lambda cells: None)
    assert send.check_bounces(rows(62))           # 3.2% of 62: too few sends to judge
    assert send.check_bounces(rows(100))          # 2%: fine
    monkeypatch.setattr(send, "bounced_addresses", lambda sent: {f"c{i}@x.es" for i in range(6)})
    assert not send.check_bounces(rows(100))      # 6%: stop


def test_failed_login_skips_only_that_account(monkeypatch):
    def boom(*a, **k):
        raise smtplib.SMTPAuthenticationError(535, b"bad")
    monkeypatch.setattr(send.smtplib, "SMTP_SSL", boom)
    assert send.send_batch(2, "b@gmail.com", "x", [(5, ROW)]) == 0
