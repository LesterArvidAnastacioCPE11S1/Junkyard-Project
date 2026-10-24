""" Checks Prices/data/junkshop_prices.csv for problems before the server uses it."""
import csv
import sys
from collections import Counter, defaultdict

from Prices import price_catalog as pc

def main(path=pc.CSV_PATH):
    problems = 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = [c for c in pc.REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            print("MISSING COLUMNS:", ", ".join(missing))
            return 1
        raw = list(reader)

    print(f"{len(raw)} rows, {len({r['junkshop_name'] for r in raw})} shops")
    seen = Counter((r["junkshop_name"], r["standardized_material_name"]) for r in raw)
    for (shop, name), n in seen.items():
        if n > 1:
            problems += 1
            print(f"  duplicate: {shop} lists '{name}' {n} times")
    for i, r in enumerate(raw, start=2):
        try:
            if float(r["unit_price_php"]) <= 0:
                raise ValueError
        except ValueError:
            problems += 1
            print(f"  line {i}: bad price {r['unit_price_php']!r}")
        if r["unit"].strip().lower() not in ("kg", "unit"):
            problems += 1
            print(f"  line {i}: unit {r['unit']!r} is not kg/unit")
        for col in ("junkshop_name", "standardized_material_name", "category"):
            if not r[col].strip():
                problems += 1
                print(f"  line {i}: {col} is empty")

    catalog = pc.load(path)
    print(f"{len(catalog.groups)} material groups after merging name variants")

    by_key_units = defaultdict(set)
    for key, unit in catalog.groups:
        by_key_units[key].add(unit)
    for key, units in by_key_units.items():
        if len(units) > 1:
            print(f"  note: '{key}' is priced per {' and per '.join(sorted(units))} - kept separate")

    for (key, unit), rows in sorted(catalog.groups.items()):
        s = pc.stats(key, unit)
        if s["outliers"]:
            problems += 1
            names = ", ".join(f"{r.shop}: {r.price:g}" for r in rows if r.price in s["outliers"])
            print(f"  outlier: {s['name']} ({unit}) typical {s['min']:g}-{s['max']:g}, but {names}")
    print("Done." if not problems else f"Done - {problems} thing(s) to look at.")
    return 0


if __name__ == "__main__":
    sys.exit(main())