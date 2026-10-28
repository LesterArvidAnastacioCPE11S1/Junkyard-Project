# forecast.py - simple next-day buying-price forecast (Objective 4).

from datetime import date, datetime, timedelta, timezone

from backend.db import connect

PH = timezone(timedelta(hours=8))          # Philippine time (no daylight saving)

LOOKBACK_DAYS = 30        # how far back the history is read
TREND_DAYS = 7            # how many recent days the trend line is fitted on (a price that has sat still all week is 'steady')
MAX_DAILY_MOVE = 0.05     # a one-day forecast never moves more than 5% from today's price
STEADY_BELOW = 0.01       # moves under 1% (or under 25 centavos) are reported as "steady"
ROUND_TO = 0.25
MIN_DAYS_FOR_TREND = 5

METHOD_NOTE = ("Estimated from this shop's own recorded price changes (straight-line trend over "
               "the last week). It is a guide, not a promise.")


def today_ph():
    return datetime.now(PH).date()


def _to_ph_date(iso_text):
    value = datetime.fromisoformat(iso_text)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(PH).date()


def _round(value):
    return round(round(value / ROUND_TO) * ROUND_TO, 2)


# step 1: one price per day
def daily_series(current_price, created_on, changes, today):
    """[(date, price), ...] from the first day we know the price until `today`.

    `changes` is [(date, old_value, new_value), ...] oldest first. The price before the first
    recorded change is that change's old value. The series never starts before the item was
    created, so a new item is not treated as if it had a month of history."""
    window_start = today - timedelta(days=LOOKBACK_DAYS - 1)
    start = max(window_start, created_on)
    if start > today:
        start = today

    if changes:
        first_old = changes[0][1]
        value = first_old if first_old is not None else changes[0][2]
        if first_old is None:                              # the price only appeared on that day
            start = max(start, changes[0][0])
    else:
        value = current_price

    by_day = {}
    for day, _old, new in changes:
        if new is not None:
            by_day[day] = new                              # several changes in a day: the last one wins

    series, day = [], start
    while day <= today:
        if day in by_day:
            value = by_day[day]
        series.append((day, value))
        day += timedelta(days=1)
    return series


# step 2: the trend
def _slope(values):
    """Least-squares slope per day through `values` (equally spaced days)."""
    n = len(values)
    if n < 2:
        return 0.0
    mean_x = (n - 1) / 2
    mean_y = sum(values) / n
    denom = sum((i - mean_x) ** 2 for i in range(n))
    return sum((i - mean_x) * (y - mean_y) for i, y in enumerate(values)) / denom if denom else 0.0


def _confidence(changes_in_window, days_of_data):
    if days_of_data < 7 or changes_in_window < 3:
        return "low"
    if changes_in_window >= 6 and days_of_data >= 14:
        return "high"
    return "medium"


def forecast_series(series, changes_in_window):
    """Forecast tomorrow from a daily series. Returns a dict (no database access)."""
    prices = [p for _, p in series]
    current = prices[-1]
    days = len(prices)

    if days < MIN_DAYS_FOR_TREND or changes_in_window == 0:
        slope, reason = 0.0, ("Price has not changed in the recorded history, so it is expected to stay the same."
                              if changes_in_window == 0 else
                              "Not enough price history yet, so it is expected to stay the same.")
    else:
        slope = _slope(prices[-(TREND_DAYS + 1):])
        reason = None

    cap = current * MAX_DAILY_MOVE
    move = max(-cap, min(cap, slope))
    expected = _round(current + move)
    delta = round(expected - current, 2)
    pct = (delta / current) if current else 0.0

    if abs(delta) < ROUND_TO or abs(pct) < STEADY_BELOW:
        expected, delta, pct, direction = current, 0.0, 0.0, "steady"
    else:
        direction = "up" if delta > 0 else "down"

    # what the price has actually done over the last week (a plain fact from the history, not a guess)
    if days >= 8:
        week_change, trend_days = round(current - prices[-8], 2), 7
    elif days >= MIN_DAYS_FOR_TREND:
        week_change, trend_days = round(current - prices[0], 2), days - 1
    else:
        week_change, trend_days = 0.0, 0
    bar = max(ROUND_TO, current * STEADY_BELOW)
    trend = "flat" if (changes_in_window == 0 or not trend_days) else (
        "up" if week_change >= bar else "down" if week_change <= -bar else "flat")

    first = prices[0]
    return {
        "current_price": current,
        "expected_price": expected,
        "change": delta,
        "change_pct": round(pct * 100, 1),
        "direction": direction,
        "confidence": _confidence(changes_in_window, days),
        "days_of_data": days,
        "changes_in_window": changes_in_window,
        "period_change": round(current - first, 2),          # how much it moved over the data we have
        "trend": trend,                                      # up / down / flat over the last week
        "week_change": week_change,
        "trend_days": trend_days,
        "reason": reason,
    }


# the shop-wide forecast
def _load(shop_id):
    with connect() as conn:
        items = conn.execute("""SELECT id, name, category, unit, buy_price, created_at FROM price_items
                                WHERE shop_id = ? AND is_active = 1 AND buy_price IS NOT NULL
                                ORDER BY category COLLATE NOCASE, name COLLATE NOCASE""", (shop_id,)).fetchall()
        history = conn.execute("""SELECT item_id, old_value, new_value, changed_at FROM price_history
                                  WHERE shop_id = ? AND field = 'buy_price' ORDER BY id""", (shop_id,)).fetchall()
    changes = {}
    for row in history:
        changes.setdefault(row["item_id"], []).append(
            (_to_ph_date(row["changed_at"]), row["old_value"], row["new_value"]))
    return items, changes


def forecast_shop(shop_id, today=None):
    """Tomorrow's expected buying price for every active item that has a buy price."""
    today = today or today_ph()
    window_start = today - timedelta(days=LOOKBACK_DAYS - 1)
    items, all_changes = _load(shop_id)
    out = []
    for item in items:
        changes = all_changes.get(item["id"], [])
        in_window = [c for c in changes if c[0] >= window_start]
        created_on = _to_ph_date(item["created_at"])
        series = daily_series(item["buy_price"], created_on, changes, today)
        result = forecast_series(series, len(in_window))
        result.update({"item_id": item["id"], "name": item["name"], "category": item["category"],
                       "unit": item["unit"]})
        out.append(result)
    return {"as_of": today.isoformat(), "for_date": (today + timedelta(days=1)).isoformat(),
            "method": METHOD_NOTE, "forecasts": out}


# the customer-facing text
def _money(value):
    return f"₱{value:,.2f}" if round(value, 2) % 1 else f"₱{value:,.0f}"


def _unit(unit):
    return " each" if unit == "unit" else "/kg"


def _line(f):
    unit = _unit(f["unit"])
    if f["direction"] != "steady":                           # a change is expected tomorrow
        word = "up" if f["direction"] == "up" else "down"
        return f"- {f['name']}: {_money(f['expected_price'])}{unit}, {word} from {_money(f['current_price'])}"
    if f["trend"] != "flat":                                 # same price tomorrow, but it has been moving
        return f"- {f['name']}: about {_money(f['current_price'])}{unit}, trending {f['trend']} this week"
    return f"- {f['name']}: {_money(f['current_price'])}{unit}, steady"


def compose_message(shop_name, result, max_chars=1300):
    """The text sent to subscribers. Always carries the 'estimate' note and the STOP instruction."""
    when = datetime.fromisoformat(result["for_date"]).strftime("%b %d").replace(" 0", " ")
    head = f"{shop_name} price update. Expected buying prices for {when}:"
    foot = ("These are estimates only. The final amount depends on the weighed material. "
            "Reply STOP to unsubscribe.")
    def interest(f):                                         # items that are moving come first
        moving = f["direction"] != "steady" or f["trend"] != "flat"
        size = abs(f["change_pct"]) + (abs(f["week_change"]) / f["current_price"] * 100 if f["current_price"] else 0)
        return (not moving, -size, f["name"].lower())
    ordered = sorted(result["forecasts"], key=interest)
    lines = []
    for f in ordered:
        candidate = _line(f)
        if len("\n".join([head, *lines, candidate, foot])) > max_chars:
            break
        lines.append(candidate)
    return "\n".join([head, *lines, foot]) if lines else ""
