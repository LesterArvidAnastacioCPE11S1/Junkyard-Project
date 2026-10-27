# inventory.py - the shop's OWN price list: the items it buys (and optionally sells) and the prices it quotes.
import re

from backend.db import connect, now_iso
from backend.errors import ApiError
from Prices import material_map, price_catalog

SCHEMA = """
CREATE TABLE IF NOT EXISTS price_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id     INTEGER NOT NULL REFERENCES shops(id),
    name        TEXT NOT NULL COLLATE NOCASE,
    category    TEXT,
    unit        TEXT NOT NULL DEFAULT 'kg' CHECK (unit IN ('kg', 'unit')),
    buy_price   REAL,                          -- what the shop pays the customer per unit
    sell_price  REAL,                          -- optional: what the shop charges when it sells this item
    catalog_key TEXT,                          -- link to the price survey (NULL = no survey match)
    aliases     TEXT,                          -- everyday words, comma separated: karton, carton
    note        TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1,    -- 0 = hidden from replies and suggestions
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    updated_by  INTEGER REFERENCES users(id),
    UNIQUE (shop_id, name)
);
CREATE INDEX IF NOT EXISTS ix_price_items_shop ON price_items(shop_id);

CREATE TABLE IF NOT EXISTS price_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id    INTEGER NOT NULL REFERENCES price_items(id) ON DELETE CASCADE,
    shop_id    INTEGER NOT NULL REFERENCES shops(id),
    field      TEXT NOT NULL CHECK (field IN ('buy_price', 'sell_price')),
    old_value  REAL,
    new_value  REAL,
    changed_by INTEGER REFERENCES users(id),
    changed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_price_history_item ON price_history(item_id);
"""

MAX_PRICE = 100000
MATCH_LIMIT = 10
CATEGORY_LIMIT = 8
EDITABLE = ("name", "category", "unit", "buy_price", "sell_price", "catalog_key", "aliases", "note", "is_active")


def init_inventory_db():
    with connect() as conn:
        conn.executescript(SCHEMA)


# cleaning input
def _price(value, label):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ApiError(422, f"{label} must be a number.")
    if number <= 0 or number > MAX_PRICE:
        raise ApiError(422, f"{label} must be above 0 and at most {MAX_PRICE:,}.")
    return round(number, 2)


def _aliases(value):
    """'Karton, carton ,KARTON' -> 'karton, carton'."""
    if isinstance(value, (list, tuple)):
        value = ",".join(value)
    seen = []
    for part in re.split(r"[,\n;]", value or ""):
        word = re.sub(r"\s+", " ", part.strip().lower())
        if word and word not in seen:
            if len(word) > 40:
                raise ApiError(422, "Each alias must be 40 characters or fewer.")
            seen.append(word)
    if len(seen) > 15:
        raise ApiError(422, "Use at most 15 aliases.")
    return ", ".join(seen) or None


def _text(value, label, limit, required=False):
    value = re.sub(r"\s+", " ", (value or "").strip())
    if required and not value:
        raise ApiError(422, f"{label} is required.")
    if len(value) > limit:
        raise ApiError(422, f"{label} must be {limit} characters or fewer.")
    return value or None


def _auto_key(name, aliases):
    """The survey material this item most likely is, from its name and aliases."""
    words = [re.sub(r"\(.*?\)", " ", name)] + [w.strip() for w in (aliases or "").split(",")]
    for word in words:
        key = price_catalog.resolve(word)
        if key:
            return key
    return None


def _check_key(key, unit):
    if not any(k == key for k, _ in price_catalog.get().groups):
        raise ApiError(422, "That survey material does not exist.")


def _clean(data, unit_default="kg"):
    """Validate the fields that were sent; returns only those."""
    out = {}
    if "name" in data:
        out["name"] = _text(data["name"], "Name", 100, required=True)
    if "category" in data:
        out["category"] = _text(data["category"], "Category", 60)
    if "unit" in data:
        if data["unit"] not in ("kg", "unit"):
            raise ApiError(422, "Unit must be kg or unit.")
        out["unit"] = data["unit"]
    if "buy_price" in data:
        out["buy_price"] = _price(data["buy_price"], "Buy price")
    if "sell_price" in data:
        out["sell_price"] = _price(data["sell_price"], "Sell price")
    if "aliases" in data:
        out["aliases"] = _aliases(data["aliases"])
    if "note" in data:
        out["note"] = _text(data["note"], "Note", 200)
    if "is_active" in data:
        out["is_active"] = 1 if data["is_active"] else 0
    if "catalog_key" in data:
        out["catalog_key"] = data["catalog_key"]                  # "auto" / a key / empty - resolved by the caller
    return out


# reading
def _last_changes(conn, shop_id):
    changes = {}
    for r in conn.execute("""SELECT item_id, old_value, new_value, changed_at FROM price_history
                             WHERE shop_id = ? AND field = 'buy_price' ORDER BY id DESC""", (shop_id,)):
        changes.setdefault(r["item_id"], {"old": r["old_value"], "new": r["new_value"], "at": r["changed_at"]})
    return changes


def _shape(row, last_change=None):
    item = dict(row)
    item["is_active"] = bool(item["is_active"])
    item["aliases_list"] = [a for a in (item["aliases"] or "").split(", ") if a]
    stats = price_catalog.stats(item["catalog_key"], item["unit"]) if item["catalog_key"] else None
    item["survey"] = ({"average": stats["average"], "min": stats["min"], "max": stats["max"],
                       "shops": stats["shops"], "name": stats["name"]} if stats else None)
    item["last_change"] = last_change
    return item


def list_items(shop_id):
    with connect() as conn:
        rows = conn.execute("SELECT * FROM price_items WHERE shop_id = ? ORDER BY category COLLATE NOCASE, name COLLATE NOCASE",
                            (shop_id,)).fetchall()
        changes = _last_changes(conn, shop_id)
    return [_shape(r, changes.get(r["id"])) for r in rows]


def get_item(shop_id, item_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM price_items WHERE id = ? AND shop_id = ?", (item_id, shop_id)).fetchone()
        changes = _last_changes(conn, shop_id) if row else {}
    if row is None:
        raise ApiError(404, "Item not found.")
    return _shape(row, changes.get(row["id"]))


def history(shop_id, item_id, limit=15):
    get_item(shop_id, item_id)
    with connect() as conn:
        rows = conn.execute("""SELECT h.field, h.old_value, h.new_value, h.changed_at, u.full_name AS changed_by
                               FROM price_history h LEFT JOIN users u ON u.id = h.changed_by
                               WHERE h.item_id = ? AND h.shop_id = ? ORDER BY h.id DESC LIMIT ?""",
                            (item_id, shop_id, limit)).fetchall()
    return [dict(r) for r in rows]


# writing
def _log(conn, shop_id, item_id, user, field, old, new):
    if old != new:
        conn.execute("""INSERT INTO price_history (item_id, shop_id, field, old_value, new_value, changed_by, changed_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                     (item_id, shop_id, field, old, new, user["id"] if user else None, now_iso()))


def create_item(shop_id, user, data):
    fields = _clean(data)
    name = fields.get("name")
    if not name:
        raise ApiError(422, "Name is required.")
    unit = fields.setdefault("unit", "kg")
    if fields.get("buy_price") is None and fields.get("sell_price") is None:
        raise ApiError(422, "Enter a buy price, a sell price, or both.")
    aliases = fields.get("aliases")
    key = data.get("catalog_key", "auto")
    if key == "auto":
        key = _auto_key(name, aliases)
    elif key:
        _check_key(key, unit)
    else:
        key = None
    category = fields.get("category")
    if not category and key:
        stats = price_catalog.stats(key, unit)
        category = stats["category"] if stats else None
    now = now_iso()
    with connect() as conn:
        if conn.execute("SELECT 1 FROM price_items WHERE shop_id = ? AND name = ?", (shop_id, name)).fetchone():
            raise ApiError(409, f"“{name}” is already on your price list.")
        cur = conn.execute(
            """INSERT INTO price_items (shop_id, name, category, unit, buy_price, sell_price, catalog_key, aliases,
                                        note, is_active, created_at, updated_at, updated_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
            (shop_id, name, category or "Other", unit, fields.get("buy_price"), fields.get("sell_price"), key,
             aliases, fields.get("note"), now, now, user["id"] if user else None))
        item_id = cur.lastrowid
    return get_item(shop_id, item_id)


def update_item(shop_id, user, item_id, data):
    current = get_item(shop_id, item_id)
    fields = _clean(data)
    merged = {**current, **fields}
    if merged["buy_price"] is None and merged["sell_price"] is None:
        raise ApiError(422, "An item needs a buy price, a sell price, or both. Hide it instead if you stop dealing in it.")
    if "catalog_key" in fields:
        key = data["catalog_key"]
        if key == "auto":
            key = _auto_key(merged["name"], merged["aliases"])
        elif key:
            _check_key(key, merged["unit"])
        fields["catalog_key"] = key or None
    if not fields:
        return current
    with connect() as conn:
        if "name" in fields and conn.execute("SELECT 1 FROM price_items WHERE shop_id = ? AND name = ? AND id <> ?",
                                             (shop_id, fields["name"], item_id)).fetchone():
            raise ApiError(409, f"“{fields['name']}” is already on your price list.")
        fields["updated_at"] = now_iso()
        fields["updated_by"] = user["id"] if user else None
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE price_items SET {sets} WHERE id = ? AND shop_id = ?",
                     (*fields.values(), item_id, shop_id))
        for field in ("buy_price", "sell_price"):
            if field in fields:
                _log(conn, shop_id, item_id, user, field, current[field], fields[field])
    return get_item(shop_id, item_id)


def delete_item(shop_id, item_id):
    get_item(shop_id, item_id)
    with connect() as conn:
        conn.execute("DELETE FROM price_items WHERE id = ? AND shop_id = ?", (item_id, shop_id))
    return {"deleted": item_id}


def _round_half(x):
    """Nearest 50 centavos, never below 0.50 (survey averages are rarely round numbers)."""
    return max(0.5, round(x * 2) / 2)


def import_survey(shop_id, user):
    """Add every surveyed material that is not on the list yet, priced at the survey average."""
    now = now_iso()
    added = skipped = 0
    with connect() as conn:
        have_keys = {(r["catalog_key"], r["unit"]) for r in conn.execute(
            "SELECT catalog_key, unit FROM price_items WHERE shop_id = ? AND catalog_key IS NOT NULL", (shop_id,))}
        have_names = {r["name"].lower() for r in conn.execute("SELECT name FROM price_items WHERE shop_id = ?", (shop_id,))}
        for s in price_catalog.list_materials():
            if (s["key"], s["unit"]) in have_keys or s["name"].lower() in have_names:
                skipped += 1
                continue
            words = sorted(w for w, keys in material_map.KEY_ALIASES.items() if s["key"] in keys)
            conn.execute(
                """INSERT INTO price_items (shop_id, name, category, unit, buy_price, catalog_key, aliases,
                                            is_active, created_at, updated_at, updated_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                (shop_id, s["name"], s["category"], s["unit"], _round_half(s["average"]), s["key"],
                 ", ".join(words) or None, now, now, user["id"] if user else None))
            have_names.add(s["name"].lower())
            added += 1
    return {"added": added, "skipped": skipped}


# matching a customer's words
def _norm(text):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9/ \-]+", " ", (text or "").lower())).strip()


def _has_word(text, term):
    return len(term) >= 3 and re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?:s|es)?(?![a-z0-9])", text) is not None


def _quotable(shop_id):
    with connect() as conn:
        rows = conn.execute("""SELECT * FROM price_items WHERE shop_id = ? AND is_active = 1
                               AND (buy_price IS NOT NULL OR sell_price IS NOT NULL)""", (shop_id,)).fetchall()
    return [_shape(r) for r in rows]


def _match_text(items, text):
    text = _norm(text)
    if not text:
        return []
    keys = set()
    for word in material_map.all_alias_words():
        if _has_word(text, word):
            keys.update(material_map.KEY_ALIASES.get(word, []))
    scored = []
    for item in items:
        score = 0
        terms = {_norm(re.sub(r"\(.*?\)", " ", item["name"]))} | set(item["aliases_list"])
        for term in terms:
            if _has_word(text, term):
                score = max(score, 10 + len(term))
        if item["catalog_key"] in keys:
            score = max(score, 8)
        if score:
            scored.append((-score, item["name"].lower(), item))
    scored.sort(key=lambda t: t[:2])
    return [t[2] for t in scored]


def match(shop_id, text, labels=None):
    """Items the message is asking about. Falls back to the classifier's material categories."""
    items = _quotable(shop_id)
    hits = _match_text(items, text)
    if hits:
        return {"items": hits[:MATCH_LIMIT], "basis": "text"}
    wanted = set()
    for label in labels or []:
        wanted.update(c.lower() for c in material_map.CLASSIFIER_CATEGORIES.get(label, []))
    if wanted:
        picks = sorted((i for i in items if (i["category"] or "").lower() in wanted), key=lambda i: i["name"].lower())
        if picks:
            return {"items": picks[:CATEGORY_LIMIT], "basis": "category"}
    return {"items": [], "basis": "none"}


def rate_for(shop_id, catalog_key, material):
    """The shop's own buying price per kg for a material, or None (the caller then uses the survey)."""
    with connect() as conn:
        if catalog_key:
            row = conn.execute("""SELECT buy_price FROM price_items WHERE shop_id = ? AND is_active = 1 AND unit = 'kg'
                                  AND catalog_key = ? AND buy_price IS NOT NULL ORDER BY id LIMIT 1""",
                               (shop_id, catalog_key)).fetchone()
            if row:
                return row["buy_price"]
    hits = [i for i in _match_text(_quotable(shop_id), material) if i["unit"] == "kg" and i["buy_price"] is not None]
    return hits[0]["buy_price"] if len(hits) == 1 else None