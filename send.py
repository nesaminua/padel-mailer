"""One scheduled run: send up to PER_RUN outreach emails from the Google Sheet through Gmail.

The sheet is the only state (this runs on a fresh machine every time): a row is sendable while its status is
'not sent'; a sent row gets status 'sent', today's date and a note. Today's count comes from those notes, so
DAILY holds across runs. Logs print counts only: this repository is public.

Env: GMAIL_USER, GMAIL_APP_PASSWORD, SHEET_ID, SHEETS_KEY_FILE; optional DAILY (400), PER_RUN (2),
GAP_MIN/GAP_MAX seconds between messages in one run (40/90), TZ_OFFSET hours for 'today' (1).
"""
import datetime
import email.message
import email.utils
import imaplib
import json
import os
import random
import re
import smtplib
import sys
import time
import urllib.parse
import urllib.request

from google.auth.transport.requests import Request
from google.oauth2 import service_account

USER = os.environ["GMAIL_USER"]
PASSWORD = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")
API = f"https://sheets.googleapis.com/v4/spreadsheets/{os.environ['SHEET_ID']}"
DAILY = int(os.environ.get("DAILY", "400"))
PER_RUN = int(os.environ.get("PER_RUN", "2"))
GAP = (float(os.environ.get("GAP_MIN", "40")), float(os.environ.get("GAP_MAX", "90")))
TODAY = (datetime.datetime.utcnow() + datetime.timedelta(hours=float(os.environ.get("TZ_OFFSET", "1")))).date()
SENT_NOTE = "email sent (auto, Gmail)"
BOUNCE_LIMIT = 0.03
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
_token = None


def call(path, body=None, method="GET"):
    global _token
    if _token is None:
        creds = service_account.Credentials.from_service_account_file(
            os.environ["SHEETS_KEY_FILE"], scopes=["https://www.googleapis.com/auth/spreadsheets"])
        creds.refresh(Request())
        _token = creds.token
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers={"Authorization": f"Bearer {_token}",
                                                         "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def write(cells):
    call("/values:batchUpdate", {"valueInputOption": "RAW", "data": [
        {"range": f"'Sheet1'!{a1}", "values": [[v]]} for a1, v in cells.items()]}, "POST")


def load():
    values = call(f"/values/{urllib.parse.quote(chr(39) + 'Sheet1' + chr(39) + '!A2:M')}").get("values", [])
    return [(i, v + [""] * (13 - len(v))) for i, v in enumerate(values, start=2)]


def sendable(v):
    return v[6] == "email" and v[7] == "not sent" and not v[9].startswith(("check site", "bad email")) \
        and EMAIL.match(v[5].strip())


def bounced_addresses(sent):
    box = imaplib.IMAP4_SSL("imap.gmail.com")
    box.login(USER, PASSWORD)
    box.select("INBOX", readonly=True)
    since = (TODAY - datetime.timedelta(days=2)).strftime("%d-%b-%Y")
    _, ids = box.search(None, f'(FROM "mailer-daemon" SINCE {since})')
    text = "".join(box.fetch(i, "(RFC822)")[1][0][1].decode("utf-8", "ignore").lower() for i in ids[0].split())
    box.logout()
    return {a for a in sent if a in text}


def check_bounces(rows):
    """Marks bounced rows; returns False (no sending this run) when bounces exceed 3% of everything sent."""
    sent = {v[5].strip().lower(): i for i, v in rows if v[7] in ("sent", "bounced") and v[9].startswith(("email sent", "email bounced"))}
    if not sent:
        return True
    hits = bounced_addresses(set(sent))
    for a in hits:
        i = sent[a]
        if rows[i - 2][1][7] != "bounced":
            write({f"H{i}": "bounced", f"J{i}": "email bounced: address does not exist"})
    rate = len(hits) / len(sent)
    print(f"sent total {len(sent)} | bounced {len(hits)} ({rate:.1%})", flush=True)
    return not (len(sent) >= 30 and rate > BOUNCE_LIMIT)


def message(v):
    msg = email.message.EmailMessage()
    msg["From"] = email.utils.formataddr(("Denys Zaichenko", USER))
    msg["To"] = v[5].strip()
    msg["Subject"] = v[11]
    msg["Message-ID"] = email.utils.make_msgid(domain="gmail.com")
    msg.set_content(v[12])
    return msg


def main():
    rows = load()
    today = sum(1 for _, v in rows if v[8] == TODAY.isoformat() and v[9].startswith("email sent"))
    todo = [(i, v) for i, v in rows if sendable(v)]
    print(f"today {TODAY} | sent today {today}/{DAILY} | left in sheet {len(todo)}", flush=True)
    if today >= DAILY or not todo:
        return
    if not check_bounces(rows):
        print("STOP: bounce rate above 3%, nothing sent", flush=True)
        sys.exit(1)
    smtp = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60)
    smtp.login(USER, PASSWORD)
    done = 0
    for i, v in todo[: min(PER_RUN, DAILY - today)]:
        if done:
            time.sleep(random.uniform(*GAP))
        try:
            smtp.send_message(message(v))
        except smtplib.SMTPRecipientsRefused:
            write({f"J{i}": "email address refused by Gmail: send by hand or find another contact"})
            continue
        except smtplib.SMTPException as e:
            print("STOP: Gmail refused the send:", str(e)[:200], flush=True)
            sys.exit(1)
        write({f"H{i}": "sent", f"I{i}": TODAY.isoformat(), f"J{i}": SENT_NOTE})
        done += 1
    smtp.quit()
    print(f"sent this run {done} | sent today {today + done}/{DAILY}", flush=True)


if __name__ == "__main__":
    main()
