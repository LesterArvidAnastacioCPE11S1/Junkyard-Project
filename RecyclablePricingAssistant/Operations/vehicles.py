# vehicles.py - the kinds of vehicle a junkshop uses, smallest to largest.
# Used by the automatic driver assignment.

VEHICLE_TYPES = {
    "tricycle": (1, "Tricycle / motorcycle"),
    "multicab": (2, "Multicab / van"),
    "pickup": (3, "Pickup"),
    "small_truck": (4, "Small / light truck"),
    "large_truck": (5, "Large truck"),
}
DEFAULT_TYPE = "small_truck"


def rank(vehicle_type):
    return VEHICLE_TYPES.get(vehicle_type or DEFAULT_TYPE, VEHICLE_TYPES[DEFAULT_TYPE])[0]


def type_label(vehicle_type):
    return VEHICLE_TYPES.get(vehicle_type or DEFAULT_TYPE, VEHICLE_TYPES[DEFAULT_TYPE])[1]


def infer_from_label(label, capacity_kg=None):
    """Guess the type for trucks that were added before vehicle types existed."""
    text = (label or "").lower()
    if any(w in text for w in ("tricycle", "trike", "motor", "sidecar")):
        return "tricycle"
    if any(w in text for w in ("multicab", "van", "l300")):
        return "multicab"
    if "pickup" in text or "pick-up" in text:
        return "pickup"
    if any(w in text for w in ("large", "big", "heavy", "10-wheel", "wing", "elf")):
        return "large_truck"
    if any(w in text for w in ("small", "light", "mini")):
        return "small_truck"
    if capacity_kg:                       # fall back on how much it can carry
        if capacity_kg <= 150:
            return "tricycle"
        if capacity_kg <= 600:
            return "multicab"
        if capacity_kg <= 1000:
            return "pickup"
        if capacity_kg <= 2500:
            return "small_truck"
        return "large_truck"
    return DEFAULT_TYPE