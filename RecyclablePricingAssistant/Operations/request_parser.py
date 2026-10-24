# request_parser.py - pulls weights, requested rates and a pickup time out of a customer message
# so an inquiry can become a draft pickup.
import re
from datetime import date, timedelta
from typing import Optional

from Prices import material_map, price_catalog

_STOP = r"(?:and|at|pati|plus|saka|tsaka|but|for|ready|na|ang|ay|po|is|are|will|can|to|by|from|in|on)"
_WORD = r"[A-Za-z][A-Za-z/\-]*"
_MATERIAL = rf"(?!{_STOP}\b){_WORD}(?:\s+(?!{_STOP}\b){_WORD}){{0,2}}"

WEIGHT = re.compile(
    rf"(?P<kg>\d[\d,]*(?:\.\d+)?)\s*(?:kgs?|kilos?|kilograms?)\b\.?\s*(?:(?:of|ng|na)\s+)?(?P<mat>{_MATERIAL})?",
    re.I)
RATE = re.compile(
    rf"(?:₱|php\s?|\bp(?=\d))?\s?(?P<rate>\d+(?:\.\d+)?)\s*(?:pesos?\s*)?(?:/|per|kada|bawat)\s*"
    rf"(?:kg|kilo|kilos)\b(?:\s*(?:for|sa|ng|on)\s+(?:the\s+)?(?P<mat>{_MATERIAL}))?", re.I)
TIME_RANGE = re.compile(
    r"(?P<h1>\d{1,2})(?::(?P<m1>\d{2}))?\s*(?P<ap1>am|pm)?\s*(?:-|–|—|to|hanggang)\s*"
    r"(?P<h2>\d{1,2})(?::(?P<m2>\d{2}))?\s*(?P<ap2>am|pm)", re.I)
SINGLE_TIME = re.compile(r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)\b", re.I)
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
MONTH_DAY = re.compile(r"\b(" + "|".join(MONTHS) + r")[a-z]*\.?\s+(\d{1,2})\b", re.I)


def _material(text: Optional[str]):
    """Turn the words after '400 kg' into (display name, catalog key). Longest known word wins."""
    text = (text or "").strip(" .,?!-")
    if not text:
        return None, None
    lowered = text.lower()
    for word in material_map.all_alias_words():
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            return price_catalog.display_name(word), price_catalog.resolve(word)
    first = " ".join(text.split()[:2])
    return first.title(), None


def _to_24h(hour, minute, meridiem):
    hour = int(hour) % 12 + (12 if meridiem.lower() == "pm" else 0)
    return f"{hour:02d}:{int(minute or 0):02d}"


def _parse_time(text):
    m = TIME_RANGE.search(text)
    if m:
        ap2 = m["ap2"]
        if int(m["h2"]) == 12 and ap2.lower() == "am" and not m["ap1"]:
            ap2 = "pm"                                  # "10-12 am" means 10 AM to noon
        end = _to_24h(m["h2"], m["m2"], ap2)
        start = _to_24h(m["h1"], m["m1"], m["ap1"] or ap2)
        if start >= end and not m["ap1"]:             # "11-1 PM" means 11 AM to 1 PM
            start = _to_24h(m["h1"], m["m1"], "am")
        return start, end
    m = SINGLE_TIME.search(text)
    return (_to_24h(m["h"], m["m"], m["ap"]), None) if m else (None, None)


def _parse_date(text, today: date):
    low = text.lower()
    if re.search(r"\b(tomorrow|bukas)\b", low):
        return (today + timedelta(days=1)).isoformat()
    if re.search(r"\b(today|ngayon|mamaya)\b", low):
        return today.isoformat()
    m = MONTH_DAY.search(low)
    if m:
        try:
            return date(today.year, MONTHS.index(m[1][:3].lower()) + 1, int(m[2])).isoformat()
        except ValueError:
            return None
    return None


def parse_request(text: str, today: Optional[date] = None) -> dict:
    today = today or date.today()
    notes, items = [], []

    for m in WEIGHT.finditer(text):
        kg = float(m["kg"].replace(",", ""))
        name, key = _material(m["mat"])
        if name is None:
            notes.append(f"Found {kg:g} kg but no material name.")
            name = "Unspecified"
        items.append({"material": name, "catalog_key": key, "expected_kg": kg, "requested_rate": None})

    rates = []
    for m in RATE.finditer(text):
        name, _ = _material(m["mat"])
        rates.append((float(m["rate"]), name))

    unmatched = []
    for rate, name in rates:
        target = next((i for i in items if name and i["material"] == name
                       and i["requested_rate"] is None), None)
        if target:
            target["requested_rate"] = rate
        else:
            unmatched.append(rate)
    open_items = [i for i in items if i["requested_rate"] is None]
    if unmatched and len(unmatched) == len(open_items):        # no names given: go in order
        for item, rate in zip(open_items, unmatched):
            item["requested_rate"] = rate
    elif unmatched:
        notes.append("A requested rate could not be matched to a material.")

    start, end = _parse_time(text)
    pickup_date = _parse_date(text, today)
    if not items:
        notes.append("No weights found in the message.")
    if start is None:
        notes.append("No pickup time found.")
    if pickup_date is None:
        notes.append("No pickup date found.")
    return {"items": items, "pickup_date": pickup_date, "window_start": start,
            "window_end": end, "notes": notes}