# driver_notify.py - emails the driver when a pickup is assigned to them, changed, or cancelled.

from datetime import date as _date

from backend import accounts_db, reply_service
from backend.db import connect, now_iso
from Operations import capacity, ops_db

SEND_TIMEOUT = 10          # seconds; keeps "Approve" from hanging if the mail server is slow

# what a driver needs to know changed, shown in the "updated" email
CHANGE_LABELS = (
    ("pickup_date", "Date"), ("window_start", "Start time"), ("window_end", "End time"),
    ("address", "Address"), ("area", "Area"), ("access_note", "Access"),
    ("stop_note", "Note for you"), ("phone", "Customer phone"), ("customer_name", "Customer"),
    ("organization", "Organization"),
)


# wording
def _day_label(iso):
    if not iso:
        return "Date to be confirmed"
    try:
        d = _date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d:%A}, {d.day} {d:%B %Y}"


def _time_label(p):
    if not p.get("window_start"):
        return "Time to be confirmed"
    start = capacity.fmt_time(p["window_start"])
    return f"{start} - {capacity.fmt_time(p['window_end'])}" if p.get("window_end") else f"from {start}"


def _show(field, value):
    if value in (None, ""):
        return "(none)"
    if field == "pickup_date":
        return _day_label(value)
    if field in ("window_start", "window_end"):
        return capacity.fmt_time(value)
    return str(value)


def _kg(x):
    return f"{x:g} kg"


def _customer_block(p):
    who = p["customer_name"] + (f" ({p['organization']})" if p.get("organization") else "")
    lines = [f"Customer : {who}"]
    if p.get("phone"):
        lines.append(f"Phone    : {p['phone']}")
    place = ", ".join(x for x in (p.get("address"), p.get("area")) if x)
    lines.append(f"Address  : {place or '(not given)'}")
    if p.get("access_note"):
        lines.append(f"Access   : {p['access_note']}")
    if p.get("stop_note"):
        lines.append(f"Note     : {p['stop_note']}")
    return lines


def _items_block(p):
    lines = []
    for i in p["items"]:
        rate = i["approved_rate"] if i.get("approved_rate") is not None else i.get("requested_rate")
        price = f" @ \u20b1{rate:g}/kg" if rate else ""
        lines.append(f"  - {i['material']}: about {_kg(i['expected_kg'])}{price}")
    lines.append(f"  Expected total: {_kg(p['expected_kg'])}")
    return lines


def build_email(kind, pickup, truck, shop_name, driver_name, changes=None):
    """-> (subject, body) for kind 'assigned' | 'updated' | 'cancelled'."""
    first = (driver_name or "").split()[0] if driver_name else "there"
    when = f"{_day_label(pickup['pickup_date'])}, {_time_label(pickup)}"
    vehicle = f"{truck['code']} ({truck['label']})" if truck else "your vehicle"
    stop = f"{pickup['customer_name']} - {_day_label(pickup['pickup_date'])}"

    if kind == "cancelled":
        subject = f"Pickup CANCELLED: {stop}"
        lines = [f"Hi {first},", "",
                 "This pickup has been cancelled. You do not need to go.", "",
                 f"Was scheduled : {when}", f"Vehicle       : {vehicle}", *_customer_block(pickup)]
        if pickup.get("cancel_reason"):
            lines.append(f"Reason        : {pickup['cancel_reason']}")
    else:
        if kind == "updated":
            subject = f"Pickup UPDATED: {stop}"
            lines = [f"Hi {first},", "",
                     "A pickup assigned to you was changed. Please use these details "
                     "instead of the earlier email.", ""]
            if changes:
                lines.append("What changed:")
                lines += [f"  - {label}: {_show(f, old)}  ->  {_show(f, new)}"
                          for f, label, old, new in changes]
                lines.append("")
        else:
            subject = f"New pickup assigned: {stop}"
            lines = [f"Hi {first},", "", "A new pickup has been approved and assigned to you.", ""]
        lines += [f"When    : {when}", f"Vehicle : {vehicle}", "", *_customer_block(pickup), "",
                  "Materials (expected):", *_items_block(pickup), "",
                  "Open ScrapDesk > Collections to see your full route for the day and to record "
                  "the weights when you collect."]
    lines += ["", f"- {shop_name}"]
    return subject, "\n".join(lines)


# sending
def _log(shop_id, pickup_id, driver_id, to_address, kind, status, error=None):
    try:
        with connect() as conn:
            conn.execute(
                """INSERT INTO driver_notices (shop_id, pickup_id, driver_id, to_address, kind, status, error, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (shop_id, pickup_id, driver_id, to_address, kind, status, error, now_iso()))
    except Exception:                                         # noqa: BLE001 - logging must never break a pickup
        pass


def _result(shop_id, pickup, driver, to, kind, sent, message):
    _log(shop_id, pickup["id"], driver["id"] if driver else None, to, kind,
         "sent" if sent else "failed", None if sent else message)
    return {"sent": sent, "to": to, "driver": driver["full_name"] if driver else None, "message": message}


def notify(shop_id, pickup, kind, truck_id=None, changes=None):
    """Email the driver of `pickup` (or of `truck_id`, when given). Never raises."""
    try:
        truck = ops_db.get_truck(shop_id, truck_id or pickup.get("truck_id")) if (truck_id or pickup.get("truck_id")) else None
        if truck is None:
            return {"sent": False, "to": None, "driver": None, "message": "No vehicle is set on this pickup."}
        driver = accounts_db.get_user(truck["driver_id"]) if truck.get("driver_id") else None
        if driver is None or driver["shop_id"] != shop_id:
            return _result(shop_id, pickup, None, None, kind, False,
                           f"{truck['code']} has no driver assigned, so nobody was emailed. "
                           "Set a driver under Trucks & vehicles.")
        if not driver.get("is_active"):
            return _result(shop_id, pickup, driver, driver["email"], kind, False,
                           f"{driver['full_name']}'s account is switched off, so they were not emailed.")
        shop = accounts_db.get_shop(shop_id) or {}
        subject, body = build_email(kind, pickup, truck, shop.get("name") or "ScrapDesk",
                                    driver["full_name"], changes)
        try:
            reply_service.send_plain_email(shop_id, driver["email"], subject, body, timeout=SEND_TIMEOUT)
        except RuntimeError as error:
            return _result(shop_id, pickup, driver, driver["email"], kind, False,
                           f"Driver not emailed: {error}")
        return _result(shop_id, pickup, driver, driver["email"], kind, True,
                       f"Emailed {driver['full_name']} ({driver['email']}).")
    except Exception as error:                                # noqa: BLE001
        name = type(error).__name__
        reason = ("The saved mail login can't be read (APP_SECRET changed?). Reconnect the email in More."
                  if name == "InvalidToken" else f"Driver not emailed ({name}).")
        return {"sent": False, "to": None, "driver": None, "message": reason}


def changed_fields(before, after):
    """[(field, label, old, new)] for the details a driver cares about that differ."""
    return [(f, label, before.get(f), after.get(f)) for f, label in CHANGE_LABELS
            if (before.get(f) or None) != (after.get(f) or None)]