# schema.py - tables for trucks, pickups and routes. Created next to the existing tables
# (shops, users, messages) in backend/inbox.db by ops_db.init_ops_db().
SCHEMA = """
CREATE TABLE IF NOT EXISTS trucks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id     INTEGER NOT NULL REFERENCES shops(id),
    code        TEXT NOT NULL,                       -- e.g. SD-01
    label       TEXT NOT NULL,                       -- e.g. Small truck
    capacity_kg REAL NOT NULL CHECK (capacity_kg > 0),
    driver_id   INTEGER REFERENCES users(id),        -- a user whose role is 'driver'
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    UNIQUE (shop_id, code)
);

CREATE TABLE IF NOT EXISTS pickups (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id        INTEGER NOT NULL REFERENCES shops(id),
    message_id     INTEGER REFERENCES messages(id),  -- the inquiry this came from, if any
    customer_name  TEXT NOT NULL,
    organization   TEXT,
    phone          TEXT,
    address        TEXT,
    area           TEXT,                             -- e.g. Bagumbayan, QC
    access_note    TEXT,                             -- e.g. Small truck access, gate 2
    stop_note      TEXT,                             -- note for the driver
    pickup_date    TEXT,                             -- YYYY-MM-DD
    window_start   TEXT,                             -- HH:MM (24h)
    window_end     TEXT,
    truck_id       INTEGER REFERENCES trucks(id),
    status         TEXT NOT NULL DEFAULT 'pending_approval'
                   CHECK (status IN ('pending_approval', 'confirmed', 'collected', 'cancelled')),
    cancel_reason  TEXT,
    approved_by    INTEGER REFERENCES users(id),
    approved_at    TEXT,
    collected_by   INTEGER REFERENCES users(id),
    collected_at   TEXT,
    photo_ref      TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pickups_day ON pickups(shop_id, pickup_date, status);
CREATE UNIQUE INDEX IF NOT EXISTS ux_pickup_message
    ON pickups(message_id) WHERE message_id IS NOT NULL AND status != 'cancelled';

CREATE TABLE IF NOT EXISTS pickup_items (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    pickup_id      INTEGER NOT NULL REFERENCES pickups(id) ON DELETE CASCADE,
    material       TEXT NOT NULL,                    -- what the customer calls it
    catalog_key    TEXT,                             -- link to Prices (NULL if unclear)
    expected_kg    REAL NOT NULL DEFAULT 0 CHECK (expected_kg >= 0),
    requested_rate REAL,                             -- pesos per kg the customer asked for
    approved_rate  REAL,                             -- pesos per kg the shop agreed to
    actual_kg      REAL                              -- weighed by the driver
);
CREATE INDEX IF NOT EXISTS ix_items_pickup ON pickup_items(pickup_id);

CREATE TABLE IF NOT EXISTS route_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id      INTEGER NOT NULL REFERENCES shops(id),
    truck_id     INTEGER NOT NULL REFERENCES trucks(id),
    run_date     TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'started' CHECK (status IN ('started', 'completed')),
    started_at   TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE (truck_id, run_date)
);
"""