# capacity.py - pure logic (no database): "will this pickup fit on this truck, at this time?"
# Mirrors the red warning in the Pickup planning design:

DEFAULT_SLOT_MINUTES = 60      # a stop with no end time is assumed to take an hour
COUNTED = ("confirmed", "collected")

def to_minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def fmt_time(hhmm):
    """'13:00' -> '1:00 PM'"""
    if not hhmm:
        return ""
    h, m = (int(x) for x in hhmm.split(":"))
    return f"{(h % 12) or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


def fmt_kg(kg):
    return f"{kg:,.0f} kg" if float(kg).is_integer() else f"{kg:,.1f} kg"


def stop_window(pickup):
    """(start, end) in minutes, or None when the pickup has no start time yet."""
    if not pickup.get("window_start"):
        return None
    start = to_minutes(pickup["window_start"])
    end = to_minutes(pickup["window_end"]) if pickup.get("window_end") else start + DEFAULT_SLOT_MINUTES
    return start, max(end, start + 1)


def day_load_kg(pickups):
    return sum(p["expected_kg"] for p in pickups if p["status"] in COUNTED)


def check_assignment(pickup, truck, day_pickups, start=None, end=None):
    """Would `pickup` fit on `truck`? day_pickups = everything already on that truck that day.
    Returns a dict; `ok` is False on over-capacity or an overlapping stop."""
    others = [p for p in day_pickups
              if p["id"] != pickup["id"] and p["status"] in COUNTED and p.get("truck_id") == truck["id"]]
    load = day_load_kg(others)
    projected = load + pickup["expected_kg"]
    over_by = max(0.0, projected - truck["capacity_kg"])

    window = stop_window({"window_start": start or pickup.get("window_start"),
                          "window_end": end if start else pickup.get("window_end")})
    conflicts = []
    if window:
        for o in others:
            ow = stop_window(o)
            if ow and window[0] < ow[1] and ow[0] < window[1]:
                conflicts.append({"pickup_id": o["id"], "customer_name": o["customer_name"],
                                  "window_start": o["window_start"]})
    return {"truck_id": truck["id"], "truck_code": truck["code"], "load_kg": load,
            "projected_kg": projected, "capacity_kg": truck["capacity_kg"],
            "over_by_kg": over_by, "conflicts": conflicts,
            "ok": over_by == 0 and not conflicts}


def describe(check):
    """One plain sentence about what is wrong ('' when everything fits)."""
    parts = []
    for c in check["conflicts"]:
        parts.append(f"Already has {c['customer_name']} at {fmt_time(c['window_start'])}.")
    if check["over_by_kg"]:
        parts.append(f"The load would reach {fmt_kg(check['projected_kg'])} - "
                     f"{fmt_kg(check['over_by_kg'])} over capacity.")
    return " ".join(parts)