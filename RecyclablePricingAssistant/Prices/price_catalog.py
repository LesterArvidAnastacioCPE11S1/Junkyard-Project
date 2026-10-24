# price_catalog.py - the junkshop price list (Prices/data/junkshop_prices.csv) loaded once at startup.
#
# What it gives the rest of the app:
#   stats(key)            - min / median / max price of one material across the surveyed shops
#   search(text)          - find materials from everyday words ("karton", "bakal", "PET")
#   resolve(text)         - the ONE catalog key a word means, or None when it is ambiguous
#   compare(key, rate)    - is a requested rate below / within / above what shops pay?
#   for_classifier(labels)- price lines for the labels the material classifier produced
import csv
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from Prices import material_map

CSV_PATH = Path(__file__).resolve().parent / "data" / "junkshop_prices.csv"
REQUIRED_COLUMNS = ["junkshop_name", "location", "raw_item_label", "standardized_material_name",
                    "category", "unit_price_php", "unit"]

OUTLIER_FACTOR = 3.0      # a price this many times above/below the median is flagged
ABOVE_TOLERANCE = 1.10    # a rate up to 10% over the highest normal price still counts as "within"
BELOW_TOLERANCE = 0.90
LOW_DATA = 3              # fewer shops than this -> the comparison is marked low confidence

# The CSV's "standardized" names are not fully standardized (e.g. "Aluminum" vs
# "Aluminum (Assorted)", "Panta / Plastic Containers" vs "Panta (Hard Plastic)").
# These rules merge the variants into one key. First match wins, so order matters.
_RULES = [
    (r"copper class a", "copper_a", "Copper Class A (Tanzo)"),
    (r"copper class b", "copper_b", "Copper Class B"),
    (r"copper class c3", "copper_c3", "Copper Class C3"),
    (r"copper class c", "copper_c", "Copper Class C"),
    (r"copper class d", "copper_d", "Copper Class D"),
    (r"dilaw", "brass_dilaw", "Dilaw (Brass / Yellow Copper)"),
    (r"bullet shell", "brass_shell", "Bullet Shell (Brass)"),
    (r"\bjal", "aluminum_jalousie", "Jalousie Aluminum"),
    (r"aluminum hard", "aluminum_hard", "Aluminum (Hard)"),
    (r"kaldero", "aluminum_cookware", "Kaldero (Aluminum Cookware)"),
    (r"^aluminum", "aluminum", "Aluminum (Assorted)"),
    (r"pantalum", "pantalum", "Pantalum (Aluminum Plastic)"),
    (r"pet plastic bottles", "pet_bottles", "PET Plastic Bottles"),
    (r"panta|\bjea\b", "panta", "Panta (Hard Plastic / Containers)"),
    (r"sibak", "plastic_sibak", "Sibak (Hard Plastic)"),
    (r"kaltas", "plastic_kaltas", "Kaltas (Scrap Plastic)"),
    (r"karton", "cardboard", "Cardboard (Karton)"),
    (r"glass bottles", "glass_bottles", "Glass Bottles"),
    (r"zinc", "zinc", "Zinc"),
    (r"tingga", "lead", "Lead (Tingga)"),
    (r"stainless", "stainless_steel", "Stainless Steel"),
    (r"bakal solid", "iron_solid", "Bakal Solid (Heavy Iron)"),
    (r"^bakal", "iron_light", "Bakal (Assorted / Light Iron)"),
    (r"yero|taslas|iron sheet", "iron_sheet", "Yero / Iron Sheet"),
    (r"\blata\b|tin cans", "tin_cans", "Tin Cans (Lata)"),
    (r"radiator heavy|copper radiator", "radiator_heavy", "Radiator (Heavy / Copper)"),
    (r"radiator", "radiator_light", "Radiator (Light / Large)"),
    (r"condenser", "condenser", "Condenser (Copper/Aluminum)"),
    (r"hard drive board", "hdd_board", "Hard Drive Board"),
    (r"hard drive|hardisk", "hard_drive", "Hard Drive / Hardisk"),
    (r"ic chips", "ic_chips", "IC Chips / Circuit Board"),
    (r"tv board|ic board", "tv_board", "TV Board / IC Board"),
    (r"mcb|circuit breaker", "mcb", "MCB / Circuit Breaker"),
    (r"cd/dvd|cd drive", "cd_drive", "CD/DVD Drive"),
    (r"m2 computer", "motherboard_m2", "M2 Computer Motherboard"),
    (r"computer motherboard", "motherboard_computer", "Computer Motherboard"),
    (r"cellion|smartphone", "phone_board", "Cellphone Board"),
    (r"single board", "single_board", "Single Board / Fan Board"),
    (r"modem", "modem_board", "Modem / Router Board"),
    (r"mc mainboard", "mainboard_mc", "MC Mainboard"),
    (r"^motherboard", "motherboard", "Motherboard"),
    (r"aircon", "aircon_compressor", "Aircon Compressor"),
    (r"plantsa", "flat_iron", "Plantsa (Flat Iron)"),
]
_COMPILED = [(re.compile(p, re.I), key, name) for p, key, name in _RULES]


def _slug(text: str) -> str:
    text = re.sub(r"\(.*?\)", "", text.lower())
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_") or "unknown"


def canonical(standardized_name: str):
    """(key, display name) for one CSV row."""
    for pattern, key, name in _COMPILED:
        if pattern.search(standardized_name):
            return key, name
    return _slug(standardized_name), standardized_name.strip()


@dataclass(frozen=True)
class PriceRow:
    shop: str
    location: str
    raw_label: str
    name: str
    category: str
    price: float
    unit: str
    key: str


class Catalog:
    def __init__(self, rows):
        self.rows = rows
        self.groups = {}                      # (key, unit) -> [PriceRow]
        for r in rows:
            self.groups.setdefault((r.key, r.unit), []).append(r)


_catalog: Optional[Catalog] = None


def load(path: Path = CSV_PATH) -> Catalog:
    """Read the CSV and keep it in memory. Called once at server start."""
    global _catalog
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{Path(path).name} is missing columns: {', '.join(missing)}")
        for n, rec in enumerate(reader, start=2):
            try:
                price = float(rec["unit_price_php"])
            except (TypeError, ValueError):
                print(f"[prices] skipped line {n}: price {rec['unit_price_php']!r} is not a number")
                continue
            if price <= 0:
                print(f"[prices] skipped line {n}: price must be above 0")
                continue
            key, name = canonical(rec["standardized_material_name"])
            rows.append(PriceRow(
                shop=rec["junkshop_name"].strip(), location=rec["location"].strip(),
                raw_label=rec["raw_item_label"].strip(), name=name,
                category=rec["category"].strip(), price=price,
                unit=rec["unit"].strip().lower(), key=key))
    _catalog = Catalog(rows)
    return _catalog


def get() -> Catalog:
    return _catalog if _catalog is not None else load()


# statistics
def _split_outliers(prices):
    """Return (normal, outliers). Needs 3+ prices to tell what is unusual."""
    if len(prices) < 3:
        return list(prices), []
    med = statistics.median(prices)
    normal = [p for p in prices if med / OUTLIER_FACTOR <= p <= med * OUTLIER_FACTOR]
    outliers = [p for p in prices if p not in normal]
    return (normal or list(prices)), outliers


def _group_stats(key, unit, rows, detail=False):
    prices = [r.price for r in rows]
    normal, outliers = _split_outliers(prices)
    out = {
        "key": key,
        "name": rows[0].name,
        "category": rows[0].category,
        "unit": unit,
        "shops": len({r.shop for r in rows}),
        "min": min(normal),
        "median": statistics.median(normal),
        "max": max(normal),
        "average": round(sum(normal) / len(normal), 2),
        "outliers": outliers,
    }
    if detail:
        out["prices"] = sorted(
            ({"shop": r.shop, "location": r.location, "label": r.raw_label, "price": r.price,
              "outlier": r.price in outliers} for r in rows),
            key=lambda x: -x["price"])
    return out


def stats(key: str, unit: str = "kg", detail: bool = False):
    rows = get().groups.get((key, unit))
    return _group_stats(key, unit, rows, detail) if rows else None


def list_materials(category: Optional[str] = None, unit: Optional[str] = None):
    out = []
    for (key, u), rows in get().groups.items():
        if unit and u != unit:
            continue
        if category and rows[0].category.lower() != category.lower():
            continue
        out.append(_group_stats(key, u, rows))
    return sorted(out, key=lambda s: (s["category"], s["name"]))


def categories():
    counts = {}
    for r in get().rows:
        counts[r.category] = counts.get(r.category, 0) + 1
    return [{"category": c, "rows": n} for c, n in sorted(counts.items())]


def shops():
    seen = {}
    for r in get().rows:
        info = seen.setdefault(r.shop, {"shop": r.shop, "location": r.location, "items": 0})
        info["items"] += 1
    return sorted(seen.values(), key=lambda s: s["shop"])


# finding materials
def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9/ \-]+", " ", (text or "").lower())).strip()


def _all_keys():
    return {key for key, _ in get().groups}


def search(text: str, limit: int = 10):
    """Materials matching everyday words. Best matches first; each entry is a stats dict."""
    q = _norm(text)
    if not q:
        return []
    scores = {}                                               # (key, unit) -> score
    cat = material_map.CATEGORY_ALIASES.get(q)
    for (key, unit), rows in get().groups.items():
        score = 0
        if key in material_map.KEY_ALIASES.get(q, []):
            score += 100
        if cat and rows[0].category.lower().startswith(cat.lower()):
            score += 60
        haystack = _norm(" ".join([rows[0].name] + [r.raw_label for r in rows]))
        for token in q.split():
            if len(token) >= 3 and token in haystack:
                score += 10
        if score:
            scores[(key, unit)] = score
    ranked = sorted(scores, key=lambda g: (-scores[g], g))[:limit]
    return [_group_stats(k, u, get().groups[(k, u)]) for k, u in ranked]


def resolve(text: str) -> Optional[str]:
    """The single catalog key a word means ("karton" -> "cardboard"), or None if unclear."""
    q = _norm(text)
    keys = [k for k in material_map.KEY_ALIASES.get(q, []) if k in _all_keys()]
    return keys[0] if len(keys) == 1 else None


def display_name(text: str) -> str:
    """A tidy name for a word the customer used ('karton' -> 'Cardboard')."""
    q = _norm(text)
    return material_map.DISPLAY.get(q) or (text or "").strip().title()


def for_classifier(labels):
    """Price lines for the labels the material classifier gave (e.g. ['Plastic', 'Paper'])."""
    wanted = set()
    for label in labels or []:
        wanted.update(c.lower() for c in material_map.CLASSIFIER_CATEGORIES.get(label, []))
    if not wanted:
        return []
    return [s for s in list_materials() if s["category"].lower() in wanted]


# price check
def compare(key: str, rate: float, unit: str = "kg") -> dict:
    """Is `rate` low, normal or high compared with what the surveyed shops pay?"""
    if rate is None or rate <= 0:
        raise ValueError("rate must be above 0")
    s = stats(key, unit) if key else None
    if s is None:
        return {"verdict": "no_reference", "rate": rate, "unit": unit, "reference": None,
                "confidence": None, "message": "No price in the survey for this material."}
    if rate > s["max"] * ABOVE_TOLERANCE:
        verdict = "above_market"
    elif rate < s["min"] * BELOW_TOLERANCE:
        verdict = "below_market"
    else:
        verdict = "within_market"
    confidence = "low" if s["shops"] < LOW_DATA else "ok"
    pct = round((rate - s["median"]) / s["median"] * 100)
    text = {
        "above_market": f"₱{rate:g}/{unit} is above what surveyed shops pay (₱{s['min']:g}–₱{s['max']:g}).",
        "below_market": f"₱{rate:g}/{unit} is below what surveyed shops pay (₱{s['min']:g}–₱{s['max']:g}).",
        "within_market": f"₱{rate:g}/{unit} is within the surveyed range (₱{s['min']:g}–₱{s['max']:g}).",
    }[verdict]
    if confidence == "low":
        text += f" Based on only {s['shops']} shop{'s' if s['shops'] != 1 else ''}."
    return {"verdict": verdict, "rate": rate, "unit": unit, "percent_vs_median": pct,
            "confidence": confidence, "reference": s, "message": text}