"""Sends sample customer messages through every channel so you can demo the system
without any real SMS, email or Facebook accounts.

Start the API first (uvicorn backend.api:app --reload), then from the project root:
    python -m backend.simulate_messages
"""
from backend import config  # noqa: F401  (loads .env first)

import hashlib
import hmac
import json
import os
import time
import urllib.request

API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000").rstrip("/")
KEY = os.environ.get("INGEST_KEY")
APP_SECRET = os.environ.get("FB_APP_SECRET")
RUN = int(time.time())

SAMPLES = [
    ("sms", "+639171234567", "Magkano po ang bili ninyo sa lata at karton ngayon?"),
    ("sms", "+639181112222", "Pa-pickup po ng diyaryo at plastik na timba bukas ng umaga, 14 Sampaguita St."),
    ("sms", "+639190000000", "Your OTP is 482915. Do not share this code with anyone."),
    ("sms", "+639175550101", "We have 500 kilos of aluminum cans every week. Can you give us a better rate?"),
    ("email", "juan@example.com", "Hello, we run a packaging company with about 3 tons of cardboard every month. "
                                  "We would like to discuss a long-term price with you."),
    ("email", "maria@example.com", "Good morning! We're clearing our garage this weekend. Can your driver collect "
                                   "old newspapers, glass bottles and a broken electric fan on Saturday?"),
    ("messenger", "PSID-1001", "Hello po, meron po ako ditong ibebenta na mga bote at mga naipon po na newspaper, "
                               "ask ko lang po kung bumibili po kayo ng mga materials neto?"),
    ("messenger", "PSID-1002", "Salamat po sa tulong kahapon, ingat po kayo!"),
]


def post(path, payload, raw=None, extra_headers=None):
    body = raw if raw is not None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", **(extra_headers or {})}
    if KEY:
        headers["X-API-Key"] = KEY
    request = urllib.request.Request(API_URL + path, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode()


def send(index, channel, sender, text):
    if channel == "sms":
        post("/webhooks/sms", {"sender": sender, "text": text})
    elif channel == "email":
        post("/inbox/ingest", {"channel": "email", "sender": sender, "text": text,
                               "subject": "Customer inquiry", "external_id": f"sim-{RUN}-{index}"})
    else:   # messenger: send what Meta would send, signed if an app secret is configured
        payload = {"object": "page", "entry": [{"id": "PAGE", "messaging": [{
            "sender": {"id": sender}, "timestamp": int(time.time() * 1000),
            "message": {"mid": f"sim-{RUN}-{index}", "text": text}}]}]}
        raw = json.dumps(payload).encode()
        headers = {}
        if APP_SECRET:
            headers["X-Hub-Signature-256"] = "sha256=" + hmac.new(
                APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
        post("/webhooks/messenger", None, raw=raw, extra_headers=headers)


def get(path):
    headers = {"X-API-Key": KEY} if KEY else {}
    request = urllib.request.Request(API_URL + path, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main():
    for index, (channel, sender, text) in enumerate(SAMPLES):
        send(index, channel, sender, text)
        print(f"sent [{channel:<9}] {text[:70]}")

    print("\nInbox (newest first):")
    for m in get(f"/inbox?limit={len(SAMPLES)}")["messages"]:
        materials = ", ".join(m["materials"]["labels"]) if m["materials"] else "-"
        flag = "  [needs review]" if m["needs_review"] else ""
        print(f"  #{m['id']:<3} {m['channel']:<9} {m['intent']:<17} {m['intent_confidence']:.2f}  "
              f"materials: {materials}{flag}")
    print("\nStats:", get("/inbox/stats"))


if __name__ == "__main__":
    main()