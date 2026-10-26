# ops_db.py - database access for trucks, pickups and routes. Every function takes a shop_id,
# so one shop can never read or change another shop's data.
import json

from backend.db import connect, now_iso
from Operations import vehicles
from Operations.schema import SCHEMA

TRUCK_FIELDS = ("code", "label", "capacity_kg", "vehicle_type", "driver_id", "is_active")
PICKUP_FIELDS = ("customer_name", "organization", "phone", "address", "area", "access_note",
                 "stop_note", "pickup_date", "window_start", "window_end", "truck_id", "status",
                 "cancel_reason", "approved_by", "approved_at", "collected_by", "collected_at",
                 "photo_ref", "auto_filled", "auto_notes", "assign_note")
STATUSES = ("pending_approval", "confirmed", "collected", "cancelled")


def _columns(conn, table):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def init_ops_db():
    with connect() as conn:
        conn.executescript(SCHEMA)
        # Upgrades for databases created by earlier versions
        if "vehicle_type" not in _columns(conn, "trucks"):
            conn.execute("ALTER TABLE trucks ADD COLUMN vehicle_type TEXT NOT NULL DEFAULT 'small_truck'")
            for row in conn.execute("SELECT id, label, capacity_kg FROM trucks").fetchall():
                conn.execute("UPDATE trucks SET vehicle_type = ? WHERE id = ?",
                             (vehicles.infer_from_label(row["label"], row["capacity_kg"]), row["id"]))
        existing = _columns(conn, "pickups")
        for column, definition in (("auto_filled", "INTEGER NOT NULL DEFAULT 0"),
                                   ("auto_notes", "TEXT"), ("assign_note", "TEXT")):
            if column not in existing:
                conn.execute(f"ALTER TABLE pickups ADD COLUMN {column} {definition}")


# trucks
_TRUCK_SELECT = """SELECT t.*, u.full_name AS driver_name, u.is_active AS driver_active
                   FROM trucks t LEFT JOIN users u ON u.id = t.driver_id"""


def _truck(row):
    if row is None:
        return None
    d = dict(row)
    d["is_active"] = bool(d["is_active"])
    d["vehicle_label"] = vehicles.type_label(d.get("vehicle_type"))
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


def create_truck(shop_id, code, label, capacity_kg, driver_id=None, vehicle_type=None):
    """Raises sqlite3.IntegrityError when the shop already has that code."""
    vehicle_type = vehicle_type or vehicles.infer_from_label(label, capacity_kg)
    with connect() as conn:
        new_id = conn.execute(
            """INSERT INTO trucks (shop_id, code, label, capacity_kg, vehicle_type, driver_id, is_active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
            (shop_id, code, label, capacity_kg, vehicle_type, driver_id, now_iso())).lastrowid
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
    d["auto_filled"] = bool(d.get("auto_filled"))
    try:
        d["auto_notes"] = json.loads(d["auto_notes"]) if d.get("auto_notes") else []
    except ValueError:
        d["auto_notes"] = []
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


def _pack(cols):
    """Store the list of notes as JSON and the flag as 0/1."""
    if "auto_notes" in cols and not isinstance(cols["auto_notes"], str) and cols["auto_notes"] is not None:
        cols["auto_notes"] = json.dumps(list(cols["auto_notes"]))
    if "auto_filled" in cols:
        cols["auto_filled"] = int(bool(cols["auto_filled"]))


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
    _pack(cols)
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

def statuses_for_message(shop_id, message_id):
    with connect() as conn:
        rows = conn.execute("SELECT status FROM pickups WHERE shop_id = ? AND message_id = ?",
                            (shop_id, message_id)).fetchall()
    return [r["status"] for r in rows]


def detach_message(shop_id, message_id):
    """The inquiry is being deleted: cancel any draft that was waiting for approval, and keep every
    pickup record (they are needed for payouts and history) without the link to the deleted message."""
    now = now_iso()
    with connect() as conn:
        conn.execute("""UPDATE pickups SET status = 'cancelled', cancel_reason = 'Inquiry deleted', updated_at = ?
                        WHERE shop_id = ? AND message_id = ? AND status = 'pending_approval'""",
                     (now, shop_id, message_id))
        conn.execute("UPDATE pickups SET message_id = NULL, updated_at = ? WHERE shop_id = ? AND message_id = ?",
                     (now, shop_id, message_id))

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
    _pack(fields)
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


# driver availability (who can work when)
DEFAULT_SHIFT = ("08:00", "17:00")
DEFAULT_WORK_DAYS = (1, 2, 3, 4, 5, 6, 7)        # every day until the owner sets days off


def _availability(row, driver_id):
    if row is None:
        return {"driver_id": driver_id, "shift_start": DEFAULT_SHIFT[0], "shift_end": DEFAULT_SHIFT[1],
                "work_days": list(DEFAULT_WORK_DAYS), "is_default": True}
    days = [int(x) for x in (row["work_days"] or "").split(",") if x.strip().isdigit()]
    return {"driver_id": driver_id, "shift_start": row["shift_start"], "shift_end": row["shift_end"],
            "work_days": days, "is_default": False}


def get_availability(shop_id, driver_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM driver_availability WHERE shop_id = ? AND driver_id = ?",
                           (shop_id, driver_id)).fetchone()
    return _availability(row, driver_id)


def set_availability(shop_id, driver_id, shift_start, shift_end, work_days):
    days = ",".join(str(d) for d in sorted(set(work_days)))
    with connect() as conn:
        conn.execute(
            """INSERT INTO driver_availability (shop_id, driver_id, shift_start, shift_end, work_days)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(shop_id, driver_id) DO UPDATE SET
                 shift_start = excluded.shift_start, shift_end = excluded.shift_end,
                 work_days = excluded.work_days""",
            (shop_id, driver_id, shift_start, shift_end, days))
    return get_availability(shop_id, driver_id)


def list_time_off(shop_id, driver_id=None, from_date=None):
    where, params = ["shop_id = ?"], [shop_id]
    if driver_id is not None:
        where.append("driver_id = ?")
        params.append(driver_id)
    if from_date:
        where.append("off_date >= ?")
        params.append(from_date)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM driver_time_off WHERE {' AND '.join(where)} ORDER BY off_date, start_time",
            params).fetchall()
    return [dict(r) for r in rows]


def add_time_off(shop_id, driver_id, off_date, start_time=None, end_time=None, note=None):
    with connect() as conn:
        new_id = conn.execute(
            """INSERT INTO driver_time_off (shop_id, driver_id, off_date, start_time, end_time, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (shop_id, driver_id, off_date, start_time, end_time, note, now_iso())).lastrowid
        row = conn.execute("SELECT * FROM driver_time_off WHERE id = ?", (new_id,)).fetchone()
    return dict(row)


def delete_time_off(shop_id, time_off_id):
    with connect() as conn:
        cur = conn.execute("DELETE FROM driver_time_off WHERE id = ? AND shop_id = ?", (time_off_id, shop_id))
        return cur.rowcount > 0