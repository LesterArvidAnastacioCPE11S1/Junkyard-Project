# ops_db.py - database access for trucks, pickups and routes. Every function takes a shop_id,
# so one shop can never read or change another shop's data.
from backend.db import connect, now_iso
from Operations.schema import SCHEMA

TRUCK_FIELDS = ("code", "label", "capacity_kg", "driver_id", "is_active")
PICKUP_FIELDS = ("customer_name", "organization", "phone", "address", "area", "access_note",
                 "stop_note", "pickup_date", "window_start", "window_end", "truck_id", "status",
                 "cancel_reason", "approved_by", "approved_at", "collected_by", "collected_at",
                 "photo_ref")
STATUSES = ("pending_approval", "confirmed", "collected", "cancelled")


def init_ops_db():
    with connect() as conn:
        conn.executescript(SCHEMA)


# trucks
_TRUCK_SELECT = """SELECT t.*, u.full_name AS driver_name
                   FROM trucks t LEFT JOIN users u ON u.id = t.driver_id"""


def _truck(row):
    if row is None:
        return None
    d = dict(row)
    d["is_active"] = bool(d["is_active"])
    return d


def list_trucks(shop_id, active_only=True):
    sql = _TRUCK_SELECT + " WHERE t.shop_id = ?" + (" AND t.is_active = 1" if active_only else "")
    with connect() as conn:
        rows = conn.execute(sql + " ORDER BY t.code", (shop_id,)).fetchall()
    return [_truck(r) for r in rows]


def get_truck(shop_id, truck_id):
    with connect() as conn:
        row = conn.execute(_TRUCK_SELECT + " WHERE t.shop_id = ? AND t.id = ?",
                           (shop_id, truck_id)).fetchone()
    return _truck(row)


def create_truck(shop_id, code, label, capacity_kg, driver_id=None):
    """Raises sqlite3.IntegrityError when the shop already has that code."""
    with connect() as conn:
        new_id = conn.execute(
            """INSERT INTO trucks (shop_id, code, label, capacity_kg, driver_id, is_active, created_at)
               VALUES (?, ?, ?, ?, ?, 1, ?)""",
            (shop_id, code, label, capacity_kg, driver_id, now_iso())).lastrowid
    return get_truck(shop_id, new_id)


def update_truck(shop_id, truck_id, **fields):
    fields = {k: v for k, v in fields.items() if k in TRUCK_FIELDS}
    if "is_active" in fields:
        fields["is_active"] = int(bool(fields["is_active"]))
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        with connect() as conn:
            conn.execute(f"UPDATE trucks SET {sets} WHERE id = ? AND shop_id = ?",
                         (*fields.values(), truck_id, shop_id))
    return get_truck(shop_id, truck_id)


# pickups
def _money(x):
    return round(x, 2)


def _shape(row, items):
    d = dict(row)
    d["items"] = items
    d["expected_kg"] = _money(sum(i["expected_kg"] for i in items))
    d["requested_total"] = _money(sum(i["expected_kg"] * i["requested_rate"]
                                      for i in items if i["requested_rate"] is not None))
    d["approved_total"] = _money(sum(i["expected_kg"] * i["approved_rate"]
                                     for i in items if i["approved_rate"] is not None))
    weighed = [i["actual_kg"] for i in items if i["actual_kg"] is not None]
    d["actual_kg"] = _money(sum(weighed)) if weighed else None
    d["amount_due"] = (_money(sum(i["actual_kg"] * i["approved_rate"] for i in items
                                  if i["actual_kg"] is not None and i["approved_rate"] is not None))
                       if weighed else None)
    return d


def _load(conn, rows):
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    marks = ",".join("?" * len(ids))
    items = conn.execute(f"SELECT * FROM pickup_items WHERE pickup_id IN ({marks}) ORDER BY id",
                         ids).fetchall()
    by_pickup = {}
    for it in items:
        by_pickup.setdefault(it["pickup_id"], []).append(dict(it))
    return [_shape(r, by_pickup.get(r["id"], [])) for r in rows]


def _insert_items(conn, pickup_id, items):
    for it in items:
        conn.execute(
            """INSERT INTO pickup_items (pickup_id, material, catalog_key, expected_kg,
                                         requested_rate, approved_rate)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (pickup_id, it["material"], it.get("catalog_key"), it.get("expected_kg") or 0,
             it.get("requested_rate"), it.get("approved_rate")))


def create_pickup(shop_id, fields, items, message_id=None):
    """Raises sqlite3.IntegrityError if this message already has an open pickup."""
    cols = {k: v for k, v in fields.items() if k in PICKUP_FIELDS}
    cols.setdefault("status", "pending_approval")
    now = now_iso()
    names = ["shop_id", "message_id", "created_at", "updated_at", *cols]
    values = [shop_id, message_id, now, now, *cols.values()]
    with connect() as conn:
        pickup_id = conn.execute(
            f"INSERT INTO pickups ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})",
            values).lastrowid
        _insert_items(conn, pickup_id, items)
    return get_pickup(shop_id, pickup_id)


def get_pickup(shop_id, pickup_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM pickups WHERE id = ? AND shop_id = ?",
                           (pickup_id, shop_id)).fetchone()
        return _load(conn, [row])[0] if row else None


def find_by_message(shop_id, message_id):
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM pickups WHERE shop_id = ? AND message_id = ? AND status != 'cancelled'",
            (shop_id, message_id)).fetchone()
        return _load(conn, [row])[0] if row else None


def list_pickups(shop_id, date=None, statuses=None, truck_id=None, undated=False, limit=200):
    """date + undated=True also returns pickups that have no date yet."""
    where, params = ["shop_id = ?"], [shop_id]
    if date and undated:
        where.append("(pickup_date = ? OR pickup_date IS NULL)")
        params.append(date)
    elif date:
        where.append("pickup_date = ?")
        params.append(date)
    if statuses:
        where.append(f"status IN ({','.join('?' * len(statuses))})")
        params.extend(statuses)
    if truck_id is not None:
        where.append("truck_id = ?")
        params.append(truck_id)
    with connect() as conn:
        rows = conn.execute(
            f"""SELECT * FROM pickups WHERE {' AND '.join(where)}
                ORDER BY COALESCE(window_start, '99:99'), id LIMIT ?""", (*params, limit)).fetchall()
        return _load(conn, rows)


def update_pickup(shop_id, pickup_id, items=None, **fields):
    """Change fields; pass items=[...] to replace the material lines."""
    fields = {k: v for k, v in fields.items() if k in PICKUP_FIELDS}
    fields["updated_at"] = now_iso()
    sets = ", ".join(f"{k} = ?" for k in fields)
    with connect() as conn:
        conn.execute(f"UPDATE pickups SET {sets} WHERE id = ? AND shop_id = ?",
                     (*fields.values(), pickup_id, shop_id))
        if items is not None:
            conn.execute("DELETE FROM pickup_items WHERE pickup_id = ?", (pickup_id,))
            _insert_items(conn, pickup_id, items)
    return get_pickup(shop_id, pickup_id)


def set_item_rates(pickup_id, rates):
    """rates = {item_id: approved pesos/kg}"""
    with connect() as conn:
        for item_id, rate in rates.items():
            conn.execute("UPDATE pickup_items SET approved_rate = ? WHERE id = ? AND pickup_id = ?",
                         (rate, item_id, pickup_id))


def set_item_actuals(pickup_id, actuals):
    """actuals = {item_id: weighed kg}"""
    with connect() as conn:
        for item_id, kg in actuals.items():
            conn.execute("UPDATE pickup_items SET actual_kg = ? WHERE id = ? AND pickup_id = ?",
                         (kg, item_id, pickup_id))


# route runs
def get_run(shop_id, truck_id, run_date):
    with connect() as conn:
        row = conn.execute("SELECT * FROM route_runs WHERE shop_id = ? AND truck_id = ? AND run_date = ?",
                           (shop_id, truck_id, run_date)).fetchone()
    return dict(row) if row else None


def start_run(shop_id, truck_id, run_date):
    with connect() as conn:
        conn.execute("""INSERT OR IGNORE INTO route_runs (shop_id, truck_id, run_date, status, started_at)
                        VALUES (?, ?, ?, 'started', ?)""", (shop_id, truck_id, run_date, now_iso()))
    return get_run(shop_id, truck_id, run_date)


def complete_run(shop_id, truck_id, run_date):
    with connect() as conn:
        conn.execute("""UPDATE route_runs SET status = 'completed', completed_at = ?
                        WHERE shop_id = ? AND truck_id = ? AND run_date = ?""",
                     (now_iso(), shop_id, truck_id, run_date))
    return get_run(shop_id, truck_id, run_date)