"""Run from the project root:  python tests/test_accounts.py   (needs no server and no internet)."""
# Offline tests for the account / shop / channel logic (no server needed).
import imaplib, os, sqlite3, sys, tempfile, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp()
os.environ["INBOX_DB"] = os.path.join(tmp, "t.db")
os.environ["APP_SECRET"] = "a-very-long-random-test-secret-value-123456"

from backend import accounts_db, account_service as A, channel_service as C, db, email_service, inbox_db, pipeline, security
from backend.channel_parsers import parse_messenger_payload
from backend.errors import ApiError
from backend.inbox_service import ingest_message

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1; print(f"  ok   {name}")
    else: failed += 1; print(f"  FAIL {name}")
def raises(status, fn, *a, **k):
    try: fn(*a, **k)
    except ApiError as e: return e.status_code == status
    return False

print("[legacy database is kept as a backup]")
conn = sqlite3.connect(os.environ["INBOX_DB"]); conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, text TEXT)")
conn.execute("INSERT INTO messages (text) VALUES ('old demo')"); conn.commit(); conn.close()
db.init_db()
backups = [f for f in os.listdir(tmp) if "before_accounts" in f]
check("old file moved aside", len(backups) == 1)
check("new schema has shop_id", "shop_id" in [r[1] for r in sqlite3.connect(os.environ["INBOX_DB"]).execute("PRAGMA table_info(messages)")])
check("init_db is safe to run again", db.init_db() is None)
pipeline.load_models()

print("[passwords and tokens]")
h = security.hash_password("hunter2hunter2")
check("hash is not the password", "hunter2" not in h)
check("verify right/wrong", security.verify_password("hunter2hunter2", h) and not security.verify_password("nope", h))
check("same password -> different hashes (salted)", security.hash_password("x") != security.hash_password("x"))
check("token hash is deterministic", security.token_hash("abc") == security.token_hash("abc"))
enc = security.encrypt_secret("gmail-app-pass"); check("encrypt/decrypt round trip", security.decrypt_secret(enc) == "gmail-app-pass" and "gmail" not in enc)

print("[sign up and log in]")
s1 = A.register_shop("Aling Nena Junkshop", "Nena Reyes", "nena@example.com", "Password123", "Pixel 8")
check("register returns token + owner + shop", s1["user"]["role"] == "owner" and s1["shop"]["name"] == "Aling Nena Junkshop" and s1["token"])
check("duplicate email -> 409", raises(409, A.register_shop, "Other", "X", "NENA@example.com", "Password123"))
check("wrong password -> 401", raises(401, A.login, "nena@example.com", "wrongwrong"))
check("unknown email -> 401 (same as wrong password)", raises(401, A.login, "ghost@example.com", "whatever12"))
os.environ["ALLOW_SIGNUP"] = "0"; check("signup can be disabled -> 403", raises(403, A.register_shop, "S", "N", "z@example.com", "Password123")); os.environ["ALLOW_SIGNUP"] = "1"

print("[lockout after repeated failures]")
A.register_shop("Lockout Shop", "L", "lock@example.com", "Password123")
for _ in range(5): raises(401, A.login, "lock@example.com", "badbadbad")
check("6th attempt blocked even with correct password -> 429", raises(429, A.login, "lock@example.com", "Password123"))

print("[tokens and several devices]")
phone = s1["token"]; tablet = A.login("nena@example.com", "Password123", "Tablet")["token"]
check("both devices authenticate", A.authenticate_token(phone) and A.authenticate_token(tablet))
check("both are the same account", A.authenticate_token(phone)["id"] == A.authenticate_token(tablet)["id"])
check("garbage token -> None", A.authenticate_token("not-a-token") is None)
me = A.authenticate_token(phone); sessions = A.list_sessions(me)
check("two sessions listed, phone marked current", len(sessions) == 2 and [s["device_name"] for s in sessions if s["current"]] == ["Pixel 8"])
A.logout(phone)
check("logging out the phone leaves the tablet logged in", A.authenticate_token(phone) is None and A.authenticate_token(tablet) is not None)
t3 = A.login("nena@example.com", "Password123", "Laptop")["token"]; A.logout_all(A.authenticate_token(t3)["id"])
check("log out everywhere", A.authenticate_token(tablet) is None and A.authenticate_token(t3) is None)
tok = A.login("nena@example.com", "Password123", "Phone")["token"]
with db.connect() as c: c.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00+00:00'")
check("expired token rejected", A.authenticate_token(tok) is None)

print("[change password]")
a = A.login("nena@example.com", "Password123", "A"); b = A.login("nena@example.com", "Password123", "B")
ua = A.authenticate_token(a["token"])
check("wrong current password -> 400", raises(400, A.change_password, ua, "nope-nope", "NewPassword456"))
A.change_password(ua, "Password123", "NewPassword456")
check("old password no longer works", raises(401, A.login, "nena@example.com", "Password123"))
check("new password works", A.login("nena@example.com", "NewPassword456", "C")["token"])
check("other devices signed out, this one kept", A.authenticate_token(b["token"]) is None and A.authenticate_token(a["token"]) is not None)

print("[staff and roles]")
owner = A.authenticate_token(a["token"])
disp = A.create_staff(owner, "Dina Dispatcher", "dina@example.com", "Password123", "dispatcher")
drv = A.create_staff(owner, "Dodong Driver", "dodong@example.com", "Password123", "driver")
check("staff created in the owner's shop", disp["shop_id"] == owner["shop_id"] and drv["role"] == "driver")
check("cannot create another owner -> 400", raises(400, A.create_staff, owner, "X", "x2@example.com", "Password123", "owner"))
check("duplicate staff email -> 409", raises(409, A.create_staff, owner, "X", "dina@example.com", "Password123", "driver"))
check("staff can log in", A.login("dina@example.com", "Password123", "Dina phone")["user"]["role"] == "dispatcher")
check("list shows 3 people", len(A.list_staff(owner)) == 3)
A.update_staff(owner, drv["id"], role="dispatcher"); check("role changed", accounts_db.get_user(drv["id"])["role"] == "dispatcher")
dt = A.login("dodong@example.com", "Password123", "x")["token"]
A.update_staff(owner, drv["id"], is_active=False)
check("deactivated user is signed out and cannot log in", A.authenticate_token(dt) is None and raises(403, A.login, "dodong@example.com", "Password123"))
check("owner account cannot be edited via staff API", raises(400, A.update_staff, owner, owner["id"], role="driver"))
other = A.authenticate_token(A.register_shop("Other Shop", "Omar", "omar@example.com", "Password123")["token"])
check("another shop's owner cannot touch my staff -> 404", raises(404, A.update_staff, other, disp["id"], is_active=False))
check("another shop's owner sees only their own staff", len(A.list_staff(other)) == 1)

print("[inbox is separated per shop]")
m1, c1 = ingest_message(owner["shop_id"], "sms", "+63917", "Magkano po ang karton ngayon?", external_id="X1")
m2, c2 = ingest_message(other["shop_id"], "sms", "+63918", "Pa-pickup po ng diyaryo bukas", external_id="X1")
check("same external id in two shops -> both stored", c1 and c2 and m1["id"] != m2["id"])
_, again = ingest_message(owner["shop_id"], "sms", "+63917", "Magkano po ang karton ngayon?", external_id="X1")
check("duplicate within a shop is skipped", again is False)
check("shop A lists only its own", [m["id"] for m in inbox_db.list_messages(owner["shop_id"])] == [m1["id"]])
check("shop A cannot open shop B's message", inbox_db.get_message(owner["shop_id"], m2["id"]) is None)
check("shop A cannot review shop B's message", inbox_db.review_message(owner["shop_id"], m2["id"], intent="Other") is None)
r = inbox_db.review_message(owner["shop_id"], m1["id"], intent="Pickup_Request", reviewer_id=owner["id"])
check("review records who did it", r["status"] == "corrected" and r["reviewed_by"] == owner["id"])
check("stats are per shop", inbox_db.stats(owner["shop_id"])["total"] == 1 and inbox_db.stats(other["shop_id"])["total"] == 1)

print("[channel settings]")
email_service.test_imap_login = lambda *a, **k: None          # skip the real network test
C.set_email(owner["shop_id"], "imap.gmail.com", "Shop@Gmail.com", "app-pass-1234", "INBOX")
st = C.get_status(owner["shop_id"])["email"]
check("email connected, password never shown", st["connected"] and "app-pass" not in str(C.get_status(owner["shop_id"])))
with db.connect() as c: raw = c.execute("SELECT secret_enc FROM channel_connections WHERE channel='email'").fetchone()[0]
check("stored password is encrypted", "app-pass-1234" not in raw)
check("same mailbox on another shop -> 409", raises(409, C.set_email, other["shop_id"], "imap.gmail.com", "shop@gmail.com", "x", "INBOX"))
key = C.regenerate_sms_key(owner["shop_id"])
check("sms key verifies for its shop only", C.verify_sms_key(owner["shop_id"], key) and not C.verify_sms_key(other["shop_id"], key))
check("wrong / missing sms key rejected", not C.verify_sms_key(owner["shop_id"], "jsk_wrong") and not C.verify_sms_key(owner["shop_id"], None))
key2 = C.regenerate_sms_key(owner["shop_id"]); check("regenerating invalidates the old key", not C.verify_sms_key(owner["shop_id"], key) and C.verify_sms_key(owner["shop_id"], key2))
check("sms key never stored in plain text", key2 not in str(accounts_db.get_connection(owner["shop_id"], "sms")))
C.set_messenger(owner["shop_id"], "PAGE-111")
check("page maps to the right shop", C.shop_for_page("PAGE-111") == owner["shop_id"] and C.shop_for_page("PAGE-999") is None)
check("page already used elsewhere -> 409", raises(409, C.set_messenger, other["shop_id"], "PAGE-111"))
payload = {"object": "page", "entry": [{"id": "PAGE-111", "messaging": [{"sender": {"id": "U1"}, "message": {"mid": "m1", "text": "hi"}}]}]}
check("messenger payload carries the page id", parse_messenger_payload(payload)[0]["page_id"] == "PAGE-111")
C.remove(owner["shop_id"], "messenger"); check("removing a channel works, twice -> 404", C.shop_for_page("PAGE-111") is None and raises(404, C.remove, owner["shop_id"], "messenger"))

print("[email checking with a fake mailbox]")
RAW = (b"From: Ana <ana@example.com>\r\nSubject: Pickup\r\nMessage-ID: <m1@x>\r\nContent-Type: text/plain\r\n\r\n"
       b"Pwede po ba ipakuha ang mga karton bukas? Nasa 5 Rizal St.\r\n")
class FakeIMAP:
    seen = []; fail = False
    def __init__(self, host, timeout=None): pass
    def login(self, u, p):
        if FakeIMAP.fail: raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")
    def select(self, f, readonly=False): return ("OK", [b"1"])
    def uid(self, cmd, *a):
        if cmd == "search": return ("OK", [b"7"])
        if cmd == "fetch": return ("OK", [(b"7 (BODY[] {99}", RAW), b")"])
        if cmd == "store": FakeIMAP.seen.append(a[0]); return ("OK", [])
    def logout(self): pass
email_service.imaplib.IMAP4_SSL = FakeIMAP
res = email_service.poll_shop(owner["shop_id"])
check("email filed into the right shop and marked read", res["new"] == 1 and res["error"] is None and FakeIMAP.seen == [b"7"])
check("it appears only in that shop's inbox", any(m["channel"] == "email" for m in inbox_db.list_messages(owner["shop_id"])) and not any(m["channel"] == "email" for m in inbox_db.list_messages(other["shop_id"])))
check("polling again does not duplicate it", email_service.poll_shop(owner["shop_id"])["new"] == 0)
FakeIMAP.fail = True; res = email_service.poll_shop(owner["shop_id"])
check("login failure is reported, not raised", res["error"] and accounts_db.get_connection(owner["shop_id"], "email")["last_error"])
FakeIMAP.fail = False; os.environ["APP_SECRET"] = "a-completely-different-secret-value-999999"
check("changed APP_SECRET gives a clear message", "Reconnect" in email_service.poll_shop(owner["shop_id"])["error"])
check("shop without email is handled", email_service.poll_shop(other["shop_id"])["connected"] is False)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
