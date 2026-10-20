"""Reads new customer emails from the junkshop's mailbox (IMAP) and sends them to the API.

Run from the project root:
    python -m backend.email_poller --once      one pass, good for demos
    python -m backend.email_poller             keep checking every POLL_SECONDS

Settings come from the .env file (see .env.example). Only the mailbox you configure is
read, and only UNREAD messages; each one is marked as read after it is stored.
"""
from backend import config 

import argparse
import imaplib
import json
import os
import sys
import time
import urllib.error
import urllib.request

from backend.channel_parsers import parse_email_bytes


def post_to_api(item: dict) -> dict:
    api_url = os.environ.get("API_URL", "http://127.0.0.1:8000").rstrip("/")
    headers = {"Content-Type": "application/json"}
    if os.environ.get("INGEST_KEY"):
        headers["X-API-Key"] = os.environ["INGEST_KEY"]
    body = json.dumps({
        "channel": "email",
        "sender": item["sender"],
        "subject": item["subject"],
        "text": item["text"],
        "external_id": item["external_id"],
        "received_at": item["received_at"],
    }).encode()
    request = urllib.request.Request(f"{api_url}/inbox/ingest", data=body,
                                     headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def poll_once() -> int:
    host = os.environ.get("IMAP_HOST", "imap.gmail.com")
    user = os.environ.get("IMAP_USER")
    password = os.environ.get("IMAP_PASSWORD")
    folder = os.environ.get("IMAP_FOLDER", "INBOX")
    if not user or not password:
        sys.exit("Set IMAP_USER and IMAP_PASSWORD in your .env file first.")

    imap = imaplib.IMAP4_SSL(host)
    handled = 0
    try:
        imap.login(user, password)
        imap.select(folder)
        status, data = imap.uid("search", None, "UNSEEN")
        uids = data[0].split() if status == "OK" and data and data[0] else []

        for uid in uids:
            status, parts = imap.uid("fetch", uid, "(BODY.PEEK[])")
            if status != "OK" or not parts or not isinstance(parts[0], tuple):
                continue

            item = parse_email_bytes(parts[0][1])
            if not item["text"]:                      # empty message, nothing to classify
                imap.uid("store", uid, "+FLAGS", "\\Seen")
                continue
            item["external_id"] = item["external_id"] or f"{user}:{uid.decode()}"

            try:
                result = post_to_api(item)
            except (urllib.error.URLError, TimeoutError) as error:
                print(f"[email] API not reachable ({error}); will retry next round.")
                continue                              # stays unread, retried later

            imap.uid("store", uid, "+FLAGS", "\\Seen")
            handled += 1
            record = result["message"]
            print(f"[email] {item['sender']} -> {record['intent']} "
                  f"({record['intent_confidence']:.2f}) id={record['id']}"
                  f"{'  [needs review]' if record['needs_review'] else ''}")
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return handled


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--once", action="store_true", help="check once and exit")
    args = parser.parse_args()
    interval = int(os.environ.get("POLL_SECONDS", "30"))

    while True:
        try:
            count = poll_once()
            print(f"[email] checked mailbox: {count} new message(s)")
        except (imaplib.IMAP4.error, OSError) as error:
            print(f"[email] mailbox error: {error}")
            if args.once:
                sys.exit(1)
        if args.once:
            return
        time.sleep(interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")