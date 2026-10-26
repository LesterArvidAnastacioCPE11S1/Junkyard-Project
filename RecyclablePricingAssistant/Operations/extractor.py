# extractor.py - reads the "who, where and how" out of a customer's message so a pickup draft
# can be filled in automatically.
#
# Everything here is plain pattern matching, so it is predictable and easy to adjust. Anything it
# cannot find is simply left empty and listed in the draft's "check this" notes.
import re
from typing import Optional

CITIES = {
    "quezon city": "QC", "qc": "QC", "manila": "Manila", "makati": "Makati", "pasig": "Pasig",
    "caloocan": "Caloocan", "marikina": "Marikina", "mandaluyong": "Mandaluyong",
    "san juan": "San Juan", "taguig": "Taguig", "pasay": "Pasay", "parañaque": "Parañaque",
    "paranaque": "Parañaque", "las piñas": "Las Piñas", "las pinas": "Las Piñas",
    "muntinlupa": "Muntinlupa", "valenzuela": "Valenzuela", "malabon": "Malabon",
    "navotas": "Navotas", "pateros": "Pateros", "antipolo": "Antipolo", "cainta": "Cainta",
    "taytay": "Taytay", "san mateo": "San Mateo",
}
_CITY_RE = re.compile(r"\b(" + "|".join(sorted((re.escape(c) for c in CITIES), key=len, reverse=True)) + r")\b",
                      re.I)

_PHONE = re.compile(r"(?<![\d.])(?:\+?63|0)9\d{2}[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")
_LANDLINE = re.compile(r"(?<![\d.])\(?0?2\)?[\s.-]?8?\d{3}[\s.-]?\d{4}(?!\d)")

_SUFFIX = (r"(?:st|street|ave|avenue|rd|road|blvd|boulevard|dr|drive|ln|lane|hwy|highway|ext|extension|"
           r"alley|compound|subd|subdivision|village|loop|circle|court|plaza|market)")
_NOT_A_NUMBER_OF_THINGS = (r"(?!(?:kg|kgs|kilo|kilos|kilogram|kilograms|peso|pesos|php|ton|tons|tonne|pcs|"
                           r"pieces|bags|sacks|boxes|bottles|cans|pm|am)\b)")
_ADDRESS = re.compile(
    r"(?<![\w₱/:.-])(?P<addr>"
    r"(?:(?:(?:blk|block|lot|unit|bldg)\.?\s*\d+[A-Za-z]?[\s,]*)+|\d{1,5}[A-Za-z]?(?:-\d+)?\s+" + _NOT_A_NUMBER_OF_THINGS + r")"
    r"(?:[A-Za-z0-9ñÑ'\-]+\s+){0,4}?" + _SUFFIX + r"\b\.?)", re.I)
# What may follow the street: ", Brgy. Something, Quezon City"
_TAIL = re.compile(
    r"(?P<tail>(?:\s*,?\s*(?i:brgy\.?|barangay|bgy\.?)\s*[A-Za-zñÑ0-9\-]+(?:\s+[A-Z][A-Za-zñÑ0-9\-]+){0,2})?"
    r"(?:\s*,\s*[A-ZÑ][A-Za-zñÑ\-]+(?:\s+[A-ZÑ][A-Za-zñÑ\-]+){0,2}){0,2})")
_LABELLED_ADDRESS = re.compile(
    r"(?:address|location|pick\s?-?up\s+(?:at|location|address)|located\s+(?:at|in)|"
    r"our\s+address\s+is)\s*(?:is|:|-)?\s*(?P<addr>[^\n.]{6,120})", re.I)
_BRGY = re.compile(r"\b(?i:brgy\.?|barangay|bgy\.?)\s*(?P<name>[A-Za-zñÑ0-9\-]+(?:\s+[A-Z][A-Za-zñÑ0-9\-]+){0,2})")

_ORG = re.compile(
    r"(?i:\bfrom|\bwith|\bat|\bwe are|\bwe're|\bwork (?:at|for)|\bowner of|\bmanager of|\brepresent)\s+"
    r"(?P<org>(?:[A-Z][\w&'’.-]*\s+){1,4}"
    r"(?:Inc\.?|Corp\.?|Corporation|Co\.|Company|Trading|Enterprises?|Hardware|Mart|Eatery|Printing|"
    r"Grocery|Warehouse|Packaging|Store|Shop|Restaurant|Bakery|Factory|Industries|Marketing|Construction|"
    r"School|Hospital|Hotel|Cafe|Café|Foundation|Services|Supermarket|Mall|Church|Pharmacy|Salon|Laundry|"
    r"Publishing|Logistics|Manufacturing))\b")

_NAME_INTRO = re.compile(
    r"(?i:\b(?:my name is|this is|i am|i'm|ako si|ako po si|si)\s+)(?P<name>[A-ZÑ][a-zñ]+(?:\s+[A-ZÑ][a-zñ]+){0,2})\b"
    r"(?!\s+(?i:from|here|and)\s+[a-z])")
_SIGN_WORDS = re.compile(r"^(?:thanks|thank you|regards|best regards|kind regards|sincerely|salamat|"
                         r"maraming salamat|best|cheers|respectfully)[\s,!.:-]*(?P<rest>.*)$", re.I)
_NAME_LINE = re.compile(r"^[-–—~\s]*(?P<name>[A-ZÑ][A-Za-zñÑ.'-]+(?:\s+[A-ZÑ][A-Za-zñÑ.'-]+){0,3})\s*$")

_ACCESS_SENTENCE = re.compile(
    r"\b(gate|access|alley|narrow|eskinita|guard|security|loading|parking|floor|elevator|stairs|gated|"
    r"landmark|beside|katabi|malapit|across|tapat|doorbell|"
    r"call\b[^.]{0,30}\b(?:arrival|arrive|upon|before|when)|text\b[^.]{0,30}\b(?:arrival|arrive|upon|before|when)|"
    r"(?:small|big|large|light|tricycle|multicab|maliit|malaking)\s+(?:na\s+)?(?:truck|vehicle|van|sasakyan)|"
    r"truck\s+access)\b", re.I)

# Vehicle limits the customer mentions -> biggest vehicle rank that can get in (see vehicles.py).
_VEHICLE_LIMITS = [
    (re.compile(r"\b(?:tricycle|trike|motorcycle)\s*(?:only|access|lang|size)\b|"
                r"\bonly\s+(?:a\s+|an\s+)?(?:tricycle|trike|motorcycle)\b", re.I), 1, "tricycle-size vehicle only"),
    (re.compile(r"\b(?:multicab|van|l300)\s*(?:only|access|lang)\b|\bonly\s+(?:a\s+)?(?:multicab|van|l300)\b|"
                r"\bnarrow\s+(?:alley|street|road|lane|entrance)\b|\b(?:eskinita|masikip)\b", re.I),
     2, "narrow access - multicab-size vehicle at most"),
    (re.compile(r"\b(?:pickup|pick-up)\s*(?:only|access|lang)\b|\bonly\s+(?:a\s+)?(?:pickup|pick-up)\b", re.I),
     3, "pickup-size vehicle at most"),
    (re.compile(r"\bsmall\s+(?:truck|vehicle|van)\b|\blight\s+truck\b|\bmaliit\s+na\s+(?:truck|sasakyan)\b|"
                r"\bno\s+(?:big|large|heavy)\s+truck|\bwalang\s+(?:malaking|big|large)\s+truck|"
                r"\b(?:big|large)\s+trucks?\s+(?:can'?t|cannot|won'?t|not|is not|aren'?t)\b|"
                r"\bhindi\s+(?:kasya|pwede)\s+ang\s+(?:malaking\s+)?truck", re.I),
     4, "small vehicle access only"),
]


def _clean(text: Optional[str], limit: int = 300) -> Optional[str]:
    text = re.sub(r"\s+", " ", (text or "")).strip(" ,.;:-")
    return text[:limit] or None


def normalize_phone(raw: Optional[str]) -> Optional[str]:
    digits = re.sub(r"[^\d+]", "", raw or "")
    if not digits:
        return None
    if digits.startswith("+63"):
        digits = "0" + digits[3:]
    elif digits.startswith("63") and len(digits) == 12:
        digits = "0" + digits[2:]
    return digits


def looks_like_phone(value: Optional[str]) -> bool:
    return bool(value) and bool(re.fullmatch(r"\+?[\d\s().-]{7,20}", value.strip()))


def find_phone(text: str) -> Optional[str]:
    m = _PHONE.search(text or "") or _LANDLINE.search(text or "")
    return normalize_phone(m.group(0)) if m else None


def _usable_sender_name(sender: Optional[str]) -> Optional[str]:
    name = (sender or "").strip()
    if not name or looks_like_phone(name):
        return None
    if name.lower() in {"unknown", "email customer", "messenger customer", "customer", "walk-in"}:
        return None
    if re.fullmatch(r"(?:psid[-_ ]?)?[\w-]*\d{4,}[\w-]*", name, re.I):     # Messenger ids, numbers
        return None
    return name


def find_name(text: str, sender: Optional[str], channel: str) -> str:
    named = _usable_sender_name(sender)
    if named:
        return named
    m = _NAME_INTRO.search(text or "")
    if m:
        return m.group("name")
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for n, line in enumerate(lines[-4:], start=max(0, len(lines) - 4)):
        sign = _SIGN_WORDS.match(line)
        if not sign:
            continue
        rest = sign.group("rest").strip()
        candidate = rest if rest else (lines[n + 1] if n + 1 < len(lines) else "")
        nm = _NAME_LINE.match(candidate or "")
        if nm and len(nm.group("name")) <= 40:
            return nm.group("name")
    if channel == "sms" and looks_like_phone(sender):
        return sender.strip()
    return {"email": "Email customer", "messenger": "Messenger customer"}.get(channel, "Customer")


def find_organization(text: str) -> Optional[str]:
    m = _ORG.search(text or "")
    return _clean(m.group("org"), 200) if m else None


def find_address(text: str) -> Optional[str]:
    text = text or ""
    m = _ADDRESS.search(text)
    if m:
        tail = _TAIL.match(text, m.end())
        addr = m.group("addr") + (tail.group("tail") if tail else "")
        return _clean(addr)
    m = _LABELLED_ADDRESS.search(text)
    if m:
        return _clean(m.group("addr"))
    return None


def find_area(text: str, address: Optional[str] = None) -> Optional[str]:
    haystack = f"{address or ''} {text or ''}"
    brgy = _BRGY.search(haystack)
    city = _CITY_RE.search(haystack)
    city_name = CITIES[city.group(1).lower()] if city else None
    if brgy and city_name:
        return f"{brgy.group('name').strip()}, {city_name}"
    if brgy:
        return brgy.group("name").strip()
    return city_name


def find_access_note(text: str) -> Optional[str]:
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    picked = [s.strip() for s in sentences if s.strip() and _ACCESS_SENTENCE.search(s)
              and "pick" not in s.lower()[:6]]
    return _clean(" ".join(dict.fromkeys(picked)), 300)


def find_vehicle_limit(text: str):
    """(biggest vehicle rank that fits, plain-language reason) or (None, None)."""
    for pattern, rank, reason in _VEHICLE_LIMITS:
        if pattern.search(text or ""):
            return rank, reason
    return None, None


def extract_details(text: str, sender: Optional[str] = None, channel: str = "manual",
                    subject: Optional[str] = None) -> dict:
    body = text or ""
    address = find_address(body)
    phone = find_phone(body)
    if not phone and channel == "sms" and looks_like_phone(sender):
        phone = normalize_phone(sender)
    rank, reason = find_vehicle_limit(body)
    return {
        "customer_name": find_name(body, sender, channel),
        "organization": find_organization(body),
        "phone": phone,
        "address": address,
        "area": find_area(body, address),
        "access_note": find_access_note(body),
        "max_vehicle_rank": rank,
        "vehicle_note": reason,
    }