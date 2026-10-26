# auto_assign.py - suggests WHICH driver/vehicle should take a pickup, and WHEN.
# Pure logic (no database): the caller hands in the trucks, the pickups already planned and the
# drivers' availability, and gets back a suggestion plus a plain-language explanation.

from datetime import date as _date, timedelta
from typing import Callable, Optional

from Operations import capacity, vehicles

SLOT_STEP = 30             # minutes between the start times we try
SEARCH_DAYS = 7            # how far ahead to look when the customer gave no date
DEFAULT_MINUTES = capacity.DEFAULT_SLOT_MINUTES


def _hhmm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def working_intervals(day: str, availability: dict, time_off: list):
    """The stretches of `day` (minutes since midnight) the driver can work. [] = not working."""
    weekday = _date.fromisoformat(day).isoweekday()
    if weekday not in availability["work_days"]:
        return []
    free = [(capacity.to_minutes(availability["shift_start"]), capacity.to_minutes(availability["shift_end"]))]
    for off in time_off:
        if off["off_date"] != day:
            continue
        if not off.get("start_time"):
            return []
        a, b = capacity.to_minutes(off["start_time"]), capacity.to_minutes(off.get("end_time") or "23:59")
        cut = []
        for lo, hi in free:
            if b <= lo or a >= hi:
                cut.append((lo, hi))
                continue
            if a > lo:
                cut.append((lo, a))
            if b < hi:
                cut.append((b, hi))
        free = cut
    return [(lo, hi) for lo, hi in free if hi > lo]


def _overlaps(start, end, stops):
    for s in stops:
        w = capacity.stop_window(s)
        if w and start < w[1] and w[0] < end:
            return True
    return False


def find_slot(intervals, stops, duration, exact_start=None, hint=None):
    """Earliest (start, end) minutes that fits a working interval and clashes with no stop."""
    if exact_start is not None:
        start, end = exact_start, exact_start + duration
        if any(lo <= start and end <= hi for lo, hi in intervals) and not _overlaps(start, end, stops):
            return start, end
        return None
    lo_hint = capacity.to_minutes(hint[0]) if hint else 0
    hi_hint = capacity.to_minutes(hint[1]) if hint else 24 * 60
    for lo, hi in intervals:
        start = max(lo, lo_hint)
        start += (-start) % SLOT_STEP                      # round up to the next half hour
        while start + duration <= hi and start < hi_hint:
            if not _overlaps(start, start + duration, stops):
                return start, start + duration
            start += SLOT_STEP
    return None


def _short(name):
    parts = (name or "").split()
    return f"{parts[0]} {parts[-1][0]}." if len(parts) > 1 else (parts[0] if parts else "")


def _who(truck):
    return f"{_short(truck.get('driver_name')) or 'No driver'} ({truck['code']})"


def _evaluate(pickup, truck, day, stops, availability, time_off, rank_limit, duration):
    """(candidate or None, reason it was rejected)."""
    if not truck.get("driver_id") or truck.get("driver_active") == 0:
        return None, "has no active driver"
    if rank_limit is not None and vehicles.rank(truck.get("vehicle_type")) > rank_limit:
        return None, f"the {vehicles.type_label(truck.get('vehicle_type')).lower()} is too big for the access"
    intervals = working_intervals(day, availability, time_off)
    if not intervals:
        return None, "is off duty that day"
    load = sum(s["expected_kg"] for s in stops)
    projected = load + pickup["expected_kg"]
    if projected > truck["capacity_kg"]:
        return None, f"{capacity.fmt_kg(projected - truck['capacity_kg'])} over its {capacity.fmt_kg(truck['capacity_kg'])} capacity"

    exact = capacity.to_minutes(pickup["window_start"]) if pickup.get("window_start") else None
    if exact is not None and pickup.get("window_end"):
        duration = max(capacity.to_minutes(pickup["window_end"]) - exact, 1)
    slot = find_slot(intervals, stops, duration, exact_start=exact, hint=pickup.get("_time_hint"))
    if slot is None:
        if exact is not None:
            return None, (f"is not free at {capacity.fmt_time(pickup['window_start'])} "
                          f"(off shift or already booked)")
        return None, "has no free time slot that day"

    same_area = bool(pickup.get("area")) and any(
        (s.get("area") or "").strip().lower() == pickup["area"].strip().lower() for s in stops)
    return {
        "truck": truck, "start": slot[0], "end": slot[1], "load": load, "projected": projected,
        "spare": truck["capacity_kg"] - projected, "same_area": same_area,
        "shift": (availability["shift_start"], availability["shift_end"]),
    }, None


def _score(c):
    return (0 if c["same_area"] else 1, c["spare"], vehicles.rank(c["truck"].get("vehicle_type")), len(c["truck"]["code"]))


def _explain(pickup, c, day, assumed_date):
    t = c["truck"]
    parts = [f"{capacity.fmt_kg(pickup['expected_kg'])} fits with {capacity.fmt_kg(c['spare'])} to spare"]
    if c["same_area"]:
        parts.append("already heading to the same area")
    parts.append(f"free {capacity.fmt_time(_hhmm(c['start']))}, shift "
                 f"{capacity.fmt_time(c['shift'][0])}-{capacity.fmt_time(c['shift'][1])}")
    text = (f"Suggested {_short(t.get('driver_name'))} ({t['code']}, "
            f"{vehicles.type_label(t.get('vehicle_type')).lower()}): " + "; ".join(parts) + ".")
    if assumed_date:
        text += " The customer gave no date, so this is the earliest day with a free driver."
    return text


def suggest(pickup: dict, trucks: list, stops_for_day: Callable[[str], list],
            availability_for: Callable[[int], dict], time_off: list, today: _date,
            rank_limit: Optional[int] = None, time_hint=None) -> dict:
    """Pick a truck, date and time. Always returns a dict with `truck_id` (None when nothing fits),
    `note` (why), and, when a slot was found, `pickup_date`, `window_start`, `window_end`."""
    item = dict(pickup)
    item["_time_hint"] = time_hint
    if not trucks:
        return {"truck_id": None, "note": "No trucks are set up yet. Add one in More > Trucks."}
    biggest = max(t["capacity_kg"] for t in trucks)
    if item["expected_kg"] > biggest:
        return {"truck_id": None, "note": (
            f"{capacity.fmt_kg(item['expected_kg'])} is more than any single vehicle can carry "
            f"(largest is {capacity.fmt_kg(biggest)}). Split it into two pickups or reduce the weight.")}

    assumed_date = not item.get("pickup_date")
    first_day = today + timedelta(days=1)
    days = ([item["pickup_date"]] if not assumed_date
            else [(first_day + timedelta(days=n)).isoformat() for n in range(SEARCH_DAYS)])
    duration = DEFAULT_MINUTES
    rejected = {}

    def best_for(day):
        stops = [s for s in stops_for_day(day) if s["id"] != item["id"]]
        found = []
        for t in trucks:
            if not t.get("driver_id"):
                rejected.setdefault(day, []).append(f"{_who(t)} has no active driver")
                continue
            mine = [s for s in stops if s.get("truck_id") == t["id"]]
            cand, why = _evaluate(item, t, day, mine, availability_for(t["driver_id"]),
                                  [o for o in time_off if o["driver_id"] == t["driver_id"]],
                                  rank_limit, duration)
            if cand:
                found.append(cand)
            else:
                rejected.setdefault(day, []).append(f"{_who(t)} {why}")
        return min(found, key=_score) if found else None

    for day in days:
        best = best_for(day)
        if best:
            return {"truck_id": best["truck"]["id"], "pickup_date": day,
                    "window_start": _hhmm(best["start"]), "window_end": pickup.get("window_end"),
                    "note": _explain(item, best, day, assumed_date), "date_assumed": assumed_date}

    # Nothing fits. Say why, and (when the customer fixed the date) when the next opening is.
    first = days[0]
    note = "No driver could take this on the requested day: " + "; ".join(rejected.get(first, [])) + "."
    if not assumed_date:
        start = _date.fromisoformat(first)
        for n in range(1, SEARCH_DAYS + 1):
            day = (start + timedelta(days=n)).isoformat()
            alt = best_for(day)
            if alt:
                note += (f" Earliest alternative: {_date.fromisoformat(day):%a, %b %d} at "
                         f"{capacity.fmt_time(_hhmm(alt['start']))} with {_short(alt['truck'].get('driver_name'))}")
                note += "" if note.endswith(".") else "."
                break
    else:
        note = f"No driver is free in the next {SEARCH_DAYS} days: " + "; ".join(rejected.get(first, [])) + "."
    return {"truck_id": None, "note": note}