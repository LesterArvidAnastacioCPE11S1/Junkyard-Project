# services.py - the rules for planning and collecting pickups.

import re
import sqlite3
from datetime import date as _date, datetime, timedelta, timezone

from backend import accounts_db, inbox_db
from backend.db import now_iso
from backend.errors import ApiError
from Operations import auto_assign, capacity, extractor, ops_db, vehicles
from Operations.request_parser import parse_request
from Prices import price_catalog

PH = timezone(timedelta(hours=8))          # Philippine time (no daylight saving)
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
NON_MATERIALS = ("Unknown",)


# small helpers
def today_ph() -> str:
    return datetime.now(PH).date().isoformat()


def check_date(value):
    if value is None:
        return today_ph()
    try:
        return _date.fromisoformat(value).isoformat()
    except ValueError:
        raise ApiError(422, "Date must look like 2026-10-21.")


def check_time(value, label):
    if value is not None and not _HHMM.match(value):
        raise ApiError(422, f"{label} must look like 13:30 (24-hour time).")
    return value


def short_name(full_name):
    """'Rico Mendoza' -> 'Rico M.'"""
    parts = (full_name or "").split()
    return f"{parts[0]} {parts[-1][0]}." if len(parts) > 1 else (parts[0] if parts else "")


def _first_name(name):
    return (name or "").split()[0] if name else "this pickup"


def _need_pickup(shop_id, pickup_id):
    p = ops_db.get_pickup(shop_id, pickup_id)
    if p is None:
        raise ApiError(404, "Pickup not found.")
    return p


def get_pickup(shop_id, pickup_id):
    return _need_pickup(shop_id, pickup_id)


def _need_truck(shop_id, truck_id):
    t = ops_db.get_truck(shop_id, truck_id)
    if t is None or not t["is_active"]:
        raise ApiError(404, "Truck not found.")
    return t


def _check_window(start, end):
    check_time(start, "Start time")
    check_time(end, "End time")
    if start and end and end <= start:
        raise ApiError(422, "End time must be after the start time.")


def _materials_label(pickup):
    names = [i["material"] for i in pickup["items"]]
    return ", ".join(names) if names else "Unspecified"


def _window_label(p):
    if not p.get("window_start"):
        return None
    a = capacity.fmt_time(p["window_start"])
    return f"{a}-{capacity.fmt_time(p['window_end'])}" if p.get("window_end") else a


# trucks
def _driver_check(shop_id, driver_id):
    if driver_id is None:
        return
    u = accounts_db.get_user(driver_id)
    if u is None or u["shop_id"] != shop_id or u["role"] != "driver" or not u["is_active"]:
        raise ApiError(422, "driver_id must be an active driver of this shop.")


def _check_vehicle_type(value):
    if value is not None and value not in vehicles.VEHICLE_TYPES:
        raise ApiError(422, "vehicle_type must be one of: " + ", ".join(vehicles.VEHICLE_TYPES))
    return value


def create_truck(shop_id, code, label, capacity_kg, driver_id=None, vehicle_type=None):
    _driver_check(shop_id, driver_id)
    _check_vehicle_type(vehicle_type)
    try:
        return ops_db.create_truck(shop_id, code.strip().upper(), label.strip(), capacity_kg, driver_id,
                                   vehicle_type)
    except sqlite3.IntegrityError:
        raise ApiError(409, "You already have a truck with that code.")


def update_truck(shop_id, truck_id, fields):
    _need_truck_any(shop_id, truck_id)
    if "vehicle_type" in fields:
        _check_vehicle_type(fields["vehicle_type"])
    if "driver_id" in fields:
        _driver_check(shop_id, fields["driver_id"])
    if "code" in fields:
        fields["code"] = fields["code"].strip().upper()
    try:
        return ops_db.update_truck(shop_id, truck_id, **fields)
    except sqlite3.IntegrityError:
        raise ApiError(409, "You already have a truck with that code.")


def _need_truck_any(shop_id, truck_id):
    t = ops_db.get_truck(shop_id, truck_id)
    if t is None:
        raise ApiError(404, "Truck not found.")
    return t


def driver_status(shop_id, truck, day):
    """Is this truck's driver working on `day`? -> {working, label} (label = shift hours or the reason)."""
    if not truck.get("driver_id"):
        return {"working": False, "label": "No driver"}
    avail = ops_db.get_availability(shop_id, truck["driver_id"])
    intervals = auto_assign.working_intervals(day, avail, ops_db.list_time_off(shop_id, truck["driver_id"], day))
    if not intervals:
        return {"working": False, "label": "Off duty"}
    lo, hi = intervals[0][0], intervals[-1][1]
    return {"working": True, "label": f"{capacity.fmt_time(auto_assign._hhmm(lo))}-"
                                       f"{capacity.fmt_time(auto_assign._hhmm(hi))}"}


def _truck_card(t, day_pickups, shop_id=None, day=None):
    mine = [p for p in day_pickups if p["truck_id"] == t["id"]]
    load = capacity.day_load_kg(mine)
    status = driver_status(shop_id, t, day) if shop_id is not None else {"working": True, "label": ""}
    return {"id": t["id"], "code": t["code"], "label": t["label"],
            "vehicle_type": t.get("vehicle_type"), "vehicle_label": t.get("vehicle_label"),
            "driver_id": t["driver_id"], "driver_name": t["driver_name"],
            "driver_short": short_name(t["driver_name"]),
            "working": status["working"], "shift_label": status["label"],
            "capacity_kg": t["capacity_kg"], "load_kg": load,
            "available_kg": max(0, t["capacity_kg"] - load),
            "load_percent": round(load / t["capacity_kg"] * 100), "stops": len(mine)}


# creating pickups
def _clean_items(items):
    out = []
    for it in items or []:
        material = (it.get("material") or "").strip()
        if not material:
            raise ApiError(422, "Every material line needs a name.")
        key = it.get("catalog_key") or price_catalog.resolve(material)
        out.append({"material": material, "catalog_key": key,
                    "expected_kg": it.get("expected_kg") or 0,
                    "requested_rate": it.get("requested_rate")})
    return out


def create_pickup(shop_id, fields, items):
    _check_window(fields.get("window_start"), fields.get("window_end"))
    if fields.get("pickup_date"):
        fields["pickup_date"] = check_date(fields["pickup_date"])
    return ops_db.create_pickup(shop_id, fields, _clean_items(items))


PICKUP_WORDS = re.compile(r"\b(pick\s?-?up|pa-?pickup|collect|kuha(?:in)?|hakot|kunin|come (?:get|by))\b", re.I)


def wants_pickup(intent, text):
    """Should a message become a draft pickup on its own?"""
    if intent == "Pickup_Request":
        return True
    return intent == "Bulk_Negotiation" and bool(PICKUP_WORDS.search(text or ""))


def _vehicle_limit(shop_id, p):
    """Biggest vehicle rank the customer's access allows (None = no limit) and why."""
    parts = [p.get("access_note") or "", p.get("stop_note") or ""]
    if p.get("message_id"):
        msg = inbox_db.get_message(shop_id, p["message_id"])
        if msg:
            parts.append(msg["text"])
    return extractor.find_vehicle_limit(" ".join(parts))


def _suggestion(shop_id, p, rank_limit, time_hint=None, today=None):
    """Ask the assignment engine which driver/vehicle and time suit this pickup."""
    today = today or datetime.now(PH).date()
    trucks = ops_db.list_trucks(shop_id)
    availability = {t["driver_id"]: ops_db.get_availability(shop_id, t["driver_id"])
                    for t in trucks if t["driver_id"]}
    time_off = ops_db.list_time_off(shop_id, from_date=today.isoformat())

    def stops_for_day(day):
        rows = ops_db.list_pickups(shop_id, date=day, statuses=("confirmed", "collected", "pending_approval"))
        return [r for r in rows if r["status"] != "pending_approval" or r["truck_id"]]

    return auto_assign.suggest(p, trucks, stops_for_day, availability.__getitem__, time_off, today,
                               rank_limit, time_hint)


def create_from_message(shop_id, message_id):
    """Turn an inquiry into a draft pickup: read the details from the text, suggest a driver,
    and leave it waiting for the dispatcher to review and approve."""
    msg = inbox_db.get_message(shop_id, message_id)
    if msg is None:
        raise ApiError(404, "Message not found.")
    existing = ops_db.find_by_message(shop_id, message_id)
    if existing:
        return existing, False

    today = datetime.now(PH).date()
    text = msg["text"]
    parsed = parse_request(text, today)
    details = extractor.extract_details(text, msg.get("sender"), msg.get("channel") or "manual", msg.get("subject"))
    items = parsed["items"]
    notes = []                                       # what the dispatcher should double-check
    if not items:                                    # fall back to what the classifier saw
        labels = (msg.get("corrected_materials")
                  or (msg["materials"]["labels"] if msg.get("materials") else []))
        items = [{"material": l.replace("_", " "), "expected_kg": 0, "requested_rate": None}
                 for l in labels if l not in NON_MATERIALS]
        notes.append("No weights found in the message - enter the kg for each material.")
    else:
        for line in parsed["notes"]:
            if line.startswith("Found"):
                notes.append(line)
        if any(not i["requested_rate"] for i in items):
            notes.append("The customer did not name a rate for every material - check the suggested rates.")
    if not details["address"]:
        notes.append("No street address found - confirm it with the customer.")
    if not details["phone"]:
        notes.append("No phone number found.")
    if details["vehicle_note"]:
        notes.append(f"Customer limit: {details['vehicle_note']}.")

    fields = {"customer_name": details["customer_name"], "organization": details["organization"],
              "phone": details["phone"], "address": details["address"], "area": details["area"],
              "access_note": details["access_note"], "pickup_date": parsed["pickup_date"],
              "window_start": parsed["window_start"], "window_end": parsed["window_end"],
              "auto_filled": True, "auto_notes": notes}
    try:
        pickup = ops_db.create_pickup(shop_id, fields, _clean_items(items), message_id=message_id)
    except sqlite3.IntegrityError:
        return ops_db.find_by_message(shop_id, message_id), False

    pickup = _apply_suggestion(shop_id, pickup, details["max_vehicle_rank"], parsed.get("time_hint"), today)
    return pickup, True


def _apply_suggestion(shop_id, pickup, rank_limit, time_hint, today):
    if pickup["expected_kg"] <= 0:
        note = "Driver not suggested yet: the weight is unknown. Enter the kg, then tap Suggest driver."
        return ops_db.update_pickup(shop_id, pickup["id"], assign_note=note)
    result = _suggestion(shop_id, pickup, rank_limit, time_hint, today)
    changes = {"assign_note": result["note"]}
    if result.get("truck_id"):
        changes.update(truck_id=result["truck_id"], pickup_date=result["pickup_date"],
                       window_start=result["window_start"])
    return ops_db.update_pickup(shop_id, pickup["id"], **changes)


def auto_draft_if_needed(shop_id, message):
    """Called for every new (or re-labelled) message. Never raises: a failure here must not lose a message."""
    try:
        intent = message.get("corrected_intent") or message["intent"]
        if wants_pickup(intent, message["text"]) and ops_db.find_by_message(shop_id, message["id"]) is None:
            pickup, created = create_from_message(shop_id, message["id"])
            return pickup if created else None
    except Exception as error:                       # noqa: BLE001
        print(f"[auto-draft] message {message.get('id')}: {type(error).__name__}: {error}")
    return None


def suggest_driver(shop_id, pickup_id, date=None, start=None, end=None, total_kg=None):
    """What the 'Suggest driver' button shows. Uses the form's current date/time/weight but saves nothing."""
    p = _need_pickup(shop_id, pickup_id)
    if p["status"] != "pending_approval":
        raise ApiError(409, "Only requests waiting for approval can be re-assigned.")
    check_time(start, "Start time"), check_time(end, "End time")
    item = dict(p)
    if date:
        item["pickup_date"] = check_date(date)
    if start:
        item["window_start"], item["window_end"] = start, end
    if total_kg is not None:
        item["expected_kg"] = total_kg
    if item["expected_kg"] <= 0:
        raise ApiError(422, "Enter the weight first so a vehicle with enough room can be chosen.")
    rank, _ = _vehicle_limit(shop_id, p)
    result = _suggestion(shop_id, item, rank, time_hint=None)
    truck = ops_db.get_truck(shop_id, result["truck_id"]) if result.get("truck_id") else None
    return {**result, "driver_short": short_name(truck["driver_name"]) if truck else None,
            "truck_code": truck["code"] if truck else None}


def edit_pickup(shop_id, pickup_id, fields, items=None):
    p = _need_pickup(shop_id, pickup_id)
    if p["status"] in ("collected", "cancelled"):
        raise ApiError(409, f"A {p['status']} pickup can't be edited.")
    if items is not None and p["status"] != "pending_approval":
        raise ApiError(409, "Materials and weights can only change before the prices are approved.")
    start = fields.get("window_start", p["window_start"])
    end = fields.get("window_end", p["window_end"])
    _check_window(start, end)
    if fields.get("pickup_date"):
        fields["pickup_date"] = check_date(fields["pickup_date"])
    if p["status"] == "confirmed" and ({"pickup_date", "window_start", "window_end"} & set(fields)):
        _recheck_confirmed(shop_id, p, fields)
    return ops_db.update_pickup(shop_id, pickup_id,
                                items=_clean_items(items) if items is not None else None, **fields)


def _recheck_confirmed(shop_id, p, fields):
    truck = _need_truck(shop_id, p["truck_id"])
    day = fields.get("pickup_date", p["pickup_date"])
    others = ops_db.list_pickups(shop_id, date=day, statuses=capacity.COUNTED, truck_id=truck["id"])
    result = capacity.check_assignment(p, truck, others,
                                       fields.get("window_start", p["window_start"]),
                                       fields.get("window_end", p["window_end"]))
    if not result["ok"]:
        raise ApiError(409, capacity.describe(result))

# deleting inquiries
def delete_inquiries(shop_id, ids):
    """Delete inquiries and the replies sent for them. A draft pickup made from one is cancelled; a pickup that
    is already scheduled blocks the deletion (cancel the pickup first); collected pickups are kept as records."""
    deleted, blocked = [], []
    for message_id in dict.fromkeys(ids):
        if inbox_db.get_message(shop_id, message_id) is None:
            continue
        if "confirmed" in ops_db.statuses_for_message(shop_id, message_id):
            blocked.append({"id": message_id, "reason": "It has a scheduled pickup. Cancel the pickup first."})
            continue
        ops_db.detach_message(shop_id, message_id)
        if inbox_db.delete_message(shop_id, message_id):
            deleted.append(message_id)
    return {"deleted": len(deleted), "deleted_ids": deleted, "blocked": blocked}

# price review
def price_review(shop_id, pickup_id):
    p = _need_pickup(shop_id, pickup_id)
    lines = []
    for i in p["items"]:
        rate = i["approved_rate"] if i["approved_rate"] is not None else i["requested_rate"]
        review = None
        if rate and i["catalog_key"]:
            review = price_catalog.compare(i["catalog_key"], rate)
        elif rate:
            review = {"verdict": "no_reference", "message": "No matching material in the price survey."}
        survey = price_catalog.stats(i["catalog_key"]) if i["catalog_key"] else None
        lines.append({"item_id": i["id"], "material": i["material"], "expected_kg": i["expected_kg"],
                      "requested_rate": i["requested_rate"], "approved_rate": i["approved_rate"],
                      "suggested_rate": survey["median"] if survey else None,
                      "line_total": round(i["expected_kg"] * rate, 2) if rate else None,
                      "review": review})
    flagged = [l for l in lines if l["review"] and l["review"]["verdict"] in ("above_market", "below_market")]
    return {"pickup_id": p["id"], "lines": lines, "requested_total": p["requested_total"],
            "approved_total": p["approved_total"], "flagged": len(flagged),
            "estimate_only": p["status"] == "pending_approval"}


# planning a day
def _full_check(shop_id, p, truck, day, start=None, end=None):
    """Capacity and overlapping stops (capacity.py) plus: is the driver working then, and is the
    vehicle small enough for the customer's access?"""
    others = ops_db.list_pickups(shop_id, date=day, statuses=capacity.COUNTED, truck_id=truck["id"])
    result = capacity.check_assignment(p, truck, others, start, end)
    extra = []

    if not truck.get("driver_id"):
        extra.append(f"{truck['code']} has no driver assigned.")
    else:
        name = short_name(truck["driver_name"]) or truck["code"]
        avail = ops_db.get_availability(shop_id, truck["driver_id"])
        intervals = auto_assign.working_intervals(day, avail, ops_db.list_time_off(shop_id, truck["driver_id"], day))
        s_time = start or p.get("window_start")
        if not intervals:
            extra.append(f"{name} is off duty on that day.")
        elif s_time:
            a = capacity.to_minutes(s_time)
            e_time = end if start else p.get("window_end")
            b = capacity.to_minutes(e_time) if e_time else a + capacity.DEFAULT_SLOT_MINUTES
            if not any(lo <= a and b <= hi for lo, hi in intervals):
                extra.append(f"{name} is not available at {capacity.fmt_time(s_time)} "
                             f"(works {capacity.fmt_time(avail['shift_start'])}-{capacity.fmt_time(avail['shift_end'])}).")

    rank, reason = _vehicle_limit(shop_id, p)
    if rank is not None and vehicles.rank(truck.get("vehicle_type")) > rank:
        extra.append(f"The customer mentioned {reason}, but {truck['code']} is a "
                     f"{vehicles.type_label(truck.get('vehicle_type')).lower()}.")

    result["availability_issues"] = extra
    result["ok"] = result["ok"] and not extra
    result["message"] = " ".join(x for x in [capacity.describe(result), *extra] if x)
    return result


def check_for_truck(shop_id, pickup_id, truck_id, date=None, start=None, end=None):
    p = _need_pickup(shop_id, pickup_id)
    truck = _need_truck(shop_id, truck_id)
    day = check_date(date or p["pickup_date"])
    check_time(start, "Start time"), check_time(end, "End time")
    return _full_check(shop_id, p, truck, day, start, end)


def day_overview(shop_id, date):
    date = check_date(date)
    trucks = ops_db.list_trucks(shop_id)
    day = ops_db.list_pickups(shop_id, date=date, statuses=capacity.COUNTED)
    pending = ops_db.list_pickups(shop_id, date=date, statuses=("pending_approval",), undated=True)
    by_truck = {t["id"]: t for t in trucks}

    schedule = []
    for p in day:
        t = by_truck.get(p["truck_id"])
        schedule.append({"id": p["id"], "customer_name": p["customer_name"], "status": p["status"],
                         "window_start": p["window_start"], "window_end": p["window_end"],
                         "time_label": capacity.fmt_time(p["window_start"]),
                         "truck_id": p["truck_id"], "truck_code": t["code"] if t else None,
                         "driver_short": short_name(t["driver_name"]) if t else None,
                         "expected_kg": p["expected_kg"]})

    pending_cards, warnings = [], []
    for p in pending:
        checks, recommended = [], None
        for t in trucks:
            c = capacity.check_assignment(p, t, day)
            c["message"] = capacity.describe(c)
            checks.append(c)
            if c["ok"] and (recommended is None or c["projected_kg"] < recommended["projected_kg"]):
                recommended = c
            if not c["ok"]:
                t_name = short_name(by_truck[t["id"]]["driver_name"]) or t["code"]
                warnings.append({"pickup_id": p["id"], "truck_id": t["id"],
                                 "title": f"If {_first_name(p['customer_name'])} is assigned to {t_name}",
                                 "detail": c["message"] + " Review the time and truck once approved."})
        pending_cards.append({
            "id": p["id"], "message_id": p["message_id"], "customer_name": p["customer_name"],
            "area": p["area"], "expected_kg": p["expected_kg"], "materials": _materials_label(p),
            "requested_window": _window_label(p), "requested_total": p["requested_total"],
            "unassigned": p["truck_id"] is None, "checks": checks,
            "recommended_truck_id": recommended["truck_id"] if recommended else None,
            "note": "Awaiting price approval - not included in the "
                    f"{len(day)} confirmed pickups."})

    return {
        "date": date, "is_today": date == today_ph(),
        "summary": {"pickups": len(day), "confirmed": len(day),
                    "planned_kg": capacity.day_load_kg(day),
                    "to_collect_kg": sum(p["expected_kg"] for p in day if p["status"] == "confirmed"),
                    "drivers_assigned": sum(1 for t in trucks if t["driver_id"]),
                    "drivers_total": len(trucks)},
        "schedule": schedule,
        "trucks": [_truck_card(t, day, shop_id, date) for t in trucks],
        "pending": pending_cards,
        "review_queue": _review_queue(shop_id, by_truck),
        "warnings": warnings,
    }


def _review_queue(shop_id, by_truck):
    """Every request waiting for approval (any date), drafts first - the dispatcher's to-do list."""
    queue = ops_db.list_pickups(shop_id, statuses=("pending_approval",), limit=100)
    queue.sort(key=lambda p: (p["pickup_date"] or "9999-99-99", p["window_start"] or "99:99", p["id"]))
    out = []
    for p in queue:
        t = by_truck.get(p["truck_id"])
        out.append({
            "id": p["id"], "message_id": p["message_id"], "customer_name": p["customer_name"],
            "area": p["area"], "expected_kg": p["expected_kg"], "materials": _materials_label(p),
            "pickup_date": p["pickup_date"], "window_label": _window_label(p),
            "requested_total": p["requested_total"], "auto_filled": p["auto_filled"],
            "truck_id": p["truck_id"], "truck_code": t["code"] if t else None,
            "driver_short": short_name(t["driver_name"]) if t else None,
            "assign_note": p["assign_note"], "check_count": len(p["auto_notes"])})
    return out


# approve / cancel
def approve(shop_id, user, pickup_id, truck_id, date, start, end, rates, force=False):
    """Confirm a pending request: fix the rates, truck and time. `rates` = {item_id: pesos/kg}."""
    p = _need_pickup(shop_id, pickup_id)
    if p["status"] != "pending_approval":
        raise ApiError(409, "Only requests waiting for approval can be approved.")
    truck = _need_truck(shop_id, truck_id)
    date = check_date(date or p["pickup_date"]) if (date or p["pickup_date"]) else None
    start = start or p["window_start"]
    end = end if end is not None else p["window_end"]
    if not date or not start:
        raise ApiError(422, "A pickup date and start time are needed before approving.")
    _check_window(start, end)

    known = {i["id"] for i in p["items"]}
    if set(rates) - known:
        raise ApiError(422, "A rate was given for a material that isn't on this pickup.")
    final = {}
    for i in p["items"]:
        rate = rates.get(i["id"], i["approved_rate"] if i["approved_rate"] is not None
                         else i["requested_rate"])
        if rate is None:
            if i["expected_kg"] > 0:
                raise ApiError(422, f"Set a rate for {i['material']} before approving.")
            continue
        if rate <= 0:
            raise ApiError(422, "Rates must be above 0.")
        final[i["id"]] = rate

    result = _full_check(shop_id, p, truck, date, start, end)
    if not result["ok"] and not force:
        raise ApiError(409, result["message"] + " Send force=true to confirm anyway.")

    ops_db.set_item_rates(p["id"], final)
    ops_db.update_pickup(shop_id, p["id"], status="confirmed", truck_id=truck_id, pickup_date=date,
                         window_start=start, window_end=end, approved_by=user["id"],
                         approved_at=now_iso())
    return ops_db.get_pickup(shop_id, p["id"])


def cancel(shop_id, pickup_id, reason=None):
    p = _need_pickup(shop_id, pickup_id)
    if p["status"] in ("collected", "cancelled"):
        raise ApiError(409, f"This pickup is already {p['status']}.")
    return ops_db.update_pickup(shop_id, pickup_id, status="cancelled", cancel_reason=reason)


# collections (the driver's day)
def pick_truck(shop_id, user, truck_id=None):
    trucks = ops_db.list_trucks(shop_id)
    if user["role"] == "driver":
        mine = [t for t in trucks if t["driver_id"] == user["id"]]
        if not mine:
            raise ApiError(404, "No truck is assigned to you yet. Ask the owner or dispatcher.")
        if truck_id is None:
            return mine[0]
        chosen = next((t for t in mine if t["id"] == truck_id), None)
        if chosen is None:
            raise ApiError(403, "That isn't your truck.")
        return chosen
    if truck_id is None:
        if len(trucks) == 1:
            return trucks[0]
        raise ApiError(422, "Choose a truck (truck_id).")
    return _need_truck(shop_id, truck_id)


def collections_day(shop_id, user, date=None, truck_id=None):
    date = check_date(date)
    truck = pick_truck(shop_id, user, truck_id)
    stops = ops_db.list_pickups(shop_id, date=date, statuses=capacity.COUNTED, truck_id=truck["id"])
    planned = capacity.day_load_kg(stops)
    run = ops_db.get_run(shop_id, truck["id"], date)
    done = [s for s in stops if s["status"] == "collected"]

    shaped, up_next_given = [], False
    for n, s in enumerate(stops, start=1):
        if s["status"] == "collected":
            state = "collected"
        elif not up_next_given:
            state, up_next_given = "up_next", True
        else:
            state = "pending"
        shaped.append({
            "id": s["id"], "sequence": n, "state": state, "customer_name": s["customer_name"],
            "area": s["area"], "address": s["address"], "phone": s["phone"],
            "window_start": s["window_start"], "window_end": s["window_end"],
            "time_label": capacity.fmt_time(s["window_start"]),
            "expected_material": _materials_label(s), "expected_kg": s["expected_kg"],
            "actual_kg": s["actual_kg"], "note": s["stop_note"], "access_note": s["access_note"],
            "items": [{"id": i["id"], "material": i["material"], "expected_kg": i["expected_kg"],
                       "actual_kg": i["actual_kg"]} for i in s["items"]]})

    if run is None:
        route_status = "not_started"
    else:
        route_status = "completed" if run["status"] == "completed" else "in_progress"
    driver_name = truck["driver_name"]
    return {
        "date": date, "route_status": route_status,
        "truck": {"id": truck["id"], "code": truck["code"], "label": truck["label"],
                  "capacity_kg": truck["capacity_kg"]},
        "driver": {"id": truck["driver_id"], "name": driver_name, "short_name": short_name(driver_name)},
        "stops_total": len(stops), "collected_count": len(done),
        "expected_kg": planned, "collected_kg": round(sum(s["actual_kg"] or 0 for s in done), 2),
        "planned_percent": round(planned / truck["capacity_kg"] * 100),
        "remaining_capacity_kg": max(0, truck["capacity_kg"] - planned),
        "day_window": ({"start": stops[0]["window_start"], "end": stops[-1]["window_start"]}
                       if stops else None),
        "stops": shaped}


def start_route(shop_id, user, date=None, truck_id=None):
    date = check_date(date)
    truck = pick_truck(shop_id, user, truck_id)
    stops = ops_db.list_pickups(shop_id, date=date, statuses=capacity.COUNTED, truck_id=truck["id"])
    if not stops:
        raise ApiError(409, "There are no confirmed stops to start.")
    ops_db.start_run(shop_id, truck["id"], date)
    return collections_day(shop_id, user, date, truck["id"])


def record_collection(shop_id, user, pickup_id, items=None, total_kg=None, photo_ref=None):
    """The driver's 'Record collection': weigh, enter the real kg, mark as collected."""
    p = _need_pickup(shop_id, pickup_id)
    if p["status"] == "collected":
        raise ApiError(409, "This stop is already recorded as collected.")
    if p["status"] != "confirmed" or p["truck_id"] is None:
        raise ApiError(409, "Only confirmed stops can be collected.")
    truck = _need_truck(shop_id, p["truck_id"])
    if user["role"] == "driver" and truck["driver_id"] != user["id"]:
        raise ApiError(403, "This stop is on another driver's route.")

    ids = {i["id"] for i in p["items"]}
    if items:
        actuals = {}
        for line in items:
            if line["item_id"] not in ids:
                raise ApiError(422, "A weight was given for a material that isn't on this stop.")
            actuals[line["item_id"]] = line["actual_kg"]
        for item_id in ids - set(actuals):
            actuals[item_id] = 0
    elif total_kg is not None:
        if len(p["items"]) != 1:
            raise ApiError(422, "This stop has several materials - enter a weight for each one.")
        actuals = {p["items"][0]["id"]: total_kg}
    else:
        raise ApiError(422, "Enter the weighed kg.")
    if any(kg < 0 for kg in actuals.values()) or sum(actuals.values()) <= 0:
        raise ApiError(422, "Enter the weighed kg (it must be above 0).")

    if ops_db.get_run(shop_id, truck["id"], p["pickup_date"]) is None:
        ops_db.start_run(shop_id, truck["id"], p["pickup_date"])      # recording starts the route
    ops_db.set_item_actuals(p["id"], actuals)
    done = ops_db.update_pickup(shop_id, p["id"], status="collected", collected_at=now_iso(),
                                collected_by=user["id"], photo_ref=photo_ref)

    remaining = [s for s in ops_db.list_pickups(shop_id, date=p["pickup_date"], statuses=("confirmed",),
                                                truck_id=truck["id"])]
    if not remaining:
        ops_db.complete_run(shop_id, truck["id"], p["pickup_date"])
    variance = round(done["actual_kg"] - done["expected_kg"], 2)
    return {"pickup": done, "variance_kg": variance,
            "variance_percent": round(variance / done["expected_kg"] * 100) if done["expected_kg"] else None,
            "amount_due": done["amount_due"], "route_complete": not remaining}


# driver availability (shift hours, working days, time off)
def _driver_for(shop_id, driver_id):
    u = accounts_db.get_user(driver_id)
    if u is None or u["shop_id"] != shop_id or u["role"] != "driver":
        raise ApiError(404, "Driver not found.")
    return u


def list_availability(shop_id):
    today = today_ph()
    trucks = {t["driver_id"]: t for t in ops_db.list_trucks(shop_id) if t["driver_id"]}
    off = ops_db.list_time_off(shop_id, from_date=today)
    out = []
    for u in accounts_db.list_users(shop_id):
        if u["role"] != "driver" or not u["is_active"]:
            continue
        truck = trucks.get(u["id"])
        out.append({**ops_db.get_availability(shop_id, u["id"]),
                    "driver_name": u["full_name"], "driver_short": short_name(u["full_name"]),
                    "truck_code": truck["code"] if truck else None,
                    "time_off": [o for o in off if o["driver_id"] == u["id"]],
                    "off_today": bool(truck) and not driver_status(shop_id, truck, today)["working"]})
    return out


def set_availability(shop_id, driver_id, shift_start, shift_end, work_days):
    _driver_for(shop_id, driver_id)
    check_time(shift_start, "Shift start"), check_time(shift_end, "Shift end")
    if shift_end <= shift_start:
        raise ApiError(422, "The shift must end after it starts.")
    if not work_days or any(d not in range(1, 8) for d in work_days):
        raise ApiError(422, "Choose at least one working day (1 = Monday ... 7 = Sunday).")
    return ops_db.set_availability(shop_id, driver_id, shift_start, shift_end, work_days)


def add_time_off(shop_id, driver_id, off_date, start_time=None, end_time=None, note=None):
    _driver_for(shop_id, driver_id)
    day = check_date(off_date)
    check_time(start_time, "Start time"), check_time(end_time, "End time")
    if bool(start_time) != bool(end_time):
        raise ApiError(422, "Give both a start and an end time, or leave both empty for the whole day.")
    if start_time and end_time <= start_time:
        raise ApiError(422, "The end time must be after the start time.")
    return ops_db.add_time_off(shop_id, driver_id, day, start_time, end_time, (note or "").strip() or None)


def remove_time_off(shop_id, time_off_id):
    if not ops_db.delete_time_off(shop_id, time_off_id):
        raise ApiError(404, "Time-off entry not found.")