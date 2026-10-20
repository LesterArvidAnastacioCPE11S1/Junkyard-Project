"""Demo: creates a demo shop, connects SMS + Messenger, sends sample customer messages
through every channel, then shows the inbox and what each role is allowed to see.

Start the API first (uvicorn backend.api:app --reload), then from the project root:
    python -m backend.simulate_messages
Safe to run again: it logs in to the same demo shop instead of creating a new one.
"""
from backend import config  # noqa: F401  (loads .env first)

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request

API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000").rstrip("/")
APP_SECRET = os.environ.get("FB_APP_SECRET")
RUN = int(time.time())
PAGE_ID = "SIM-PAGE-1"

OWNER = {"email": "demo.owner@example.com", "password": "DemoPass123"}
STAFF = [
    {"full_name": "Demo Dispatcher", "email": "demo.dispatcher@example.com", "password": "DemoPass123", "role": "dispatcher"},
    {"full_name": "Demo Driver", "email": "demo.driver@example.com", "password": "DemoPass123", "role": "driver"},
]

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


def call(method, path, body=None, token=None, headers=None, raw=None):
    """Return (status_code, parsed_json_or_text). Never raises on HTTP errors."""
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    all_headers = {"Content-Type": "application/json", **(headers or {})}
    if token:
        all_headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(API_URL + path, data=data, headers=all_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status, text = response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        status, text = error.code, error.read().decode()
    try:
        return status, json.loads(text)
    except ValueError:
        return status, text


def messenger_headers(raw):
    if not APP_SECRET:
        return {}
    return {"X-Hub-Signature-256": "sha256=" + hmac.new(APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()}


def send(index, channel, sender, text, token, sms_key, shop_id):
    if channel == "sms":
        status, data = call("POST", f"/webhooks/sms/{shop_id}", {"sender": sender, "text": text},
                            headers={"X-API-Key": sms_key})
    elif channel == "email":    # in real use the email checker does this; here we add it by hand
        status, data = call("POST", "/inbox/ingest", {"channel": "email", "sender": sender, "text": text,
                                                       "subject": "Customer inquiry",
                                                       "external_id": f"sim-{RUN}-{index}"}, token=token)
    else:                       # messenger: exactly what Meta would send, signed if a secret is set
        raw = json.dumps({"object": "page", "entry": [{"id": PAGE_ID, "messaging": [{
            "sender": {"id": sender}, "timestamp": int(time.time() * 1000),
            "message": {"mid": f"sim-{RUN}-{index}", "text": text}}]}]}).encode()
        status, data = call("POST", "/webhooks/messenger", raw=raw, headers=messenger_headers(raw))
    return status


def main():
    # 1. Sign in (the first run creates the demo shop)
    status, data = call("POST", "/auth/register-shop", {
        "shop_name": "Demo Junkshop", "full_name": "Demo Owner", "device_name": "Simulator", **OWNER})
    if status == 409:
        status, data = call("POST", "/auth/login", {**OWNER, "device_name": "Simulator"})
    if status not in (200, 201):
        raise SystemExit(f"Could not sign in ({status}): {data}")
    token, shop_id = data["token"], data["shop"]["id"]
    print(f"Signed in as {data['user']['email']} ({data['user']['role']}) - shop: {data['shop']['name']}")

    # 2. Connect channels
    status, data = call("POST", "/channels/sms/key", token=token)
    sms_key = data["sms_key"]
    call("PUT", "/channels/messenger", {"page_id": PAGE_ID}, token=token)
    print(f"SMS webhook: POST {data['webhook_path']}   Messenger page: {PAGE_ID}\n")

    # 3. Send customer messages through each channel
    for index, (channel, sender, text) in enumerate(SAMPLES):
        status = send(index, channel, sender, text, token, sms_key, shop_id)
        print(f"sent [{channel:<9}] -> HTTP {status}   {text[:60]}")

    # 4. Show the inbox
    status, inbox = call("GET", f"/inbox?limit={len(SAMPLES)}", token=token)
    print("\nInbox (newest first):")
    for m in inbox["messages"]:
        materials = ", ".join(m["materials"]["labels"]) if m["materials"] else "-"
        flag = "  [needs review]" if m["needs_review"] else ""
        print(f"  #{m['id']:<3} {m['channel']:<9} {m['intent']:<17} {m['intent_confidence']:.2f}  "
              f"materials: {materials}{flag}")
    print("\nStats:", call("GET", "/inbox/stats", token=token)[1])

    # 5. Staff roles
    print("\nStaff roles:")
    for person in STAFF:
        call("POST", "/staff", person, token=token)            # 409 on re-runs is fine
        status, login = call("POST", "/auth/login", {"email": person["email"], "password": person["password"],
                                                     "device_name": "Simulator"})
        if status != 200:
            print(f"  {person['role']:<11} could not log in ({status})")
            continue
        inbox_status, _ = call("GET", "/inbox", token=login["token"])
        channels_status, _ = call("GET", "/channels", token=login["token"])
        print(f"  {person['role']:<11} read inbox: {'allowed' if inbox_status == 200 else 'blocked'} ({inbox_status})"
              f"   manage channels: {'allowed' if channels_status == 200 else 'blocked'} ({channels_status})")


if __name__ == "__main__":
    main()
