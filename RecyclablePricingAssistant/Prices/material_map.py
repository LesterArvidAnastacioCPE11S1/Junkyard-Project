# material_map.py - connects the words customers use, and the 7 labels of the material
# classifier, to the junkshop price catalog (Prices/data/junkshop_prices.csv).

# Classifier label -> price-list categories (the "category" column of the CSV).
CLASSIFIER_CATEGORIES = {
    "Plastic": ["Plastic", "Mixed Plastic/Metal"],
    "Paper": ["Paper"],
    "Cardboard": ["Paper"],
    "Aluminum": ["Metal - Aluminum"],
    "Other_Metals": ["Metal - Copper", "Metal - Iron", "Metal - Zinc", "Metal - Lead",
                     "Metal - Brass", "Metal - Steel", "Metal - Mixed"],
    "Glass": ["Glass"],
    "Electronic_Waste": ["E-Waste", "E-Waste / Appliance", "Battery"],
}

# Everyday words (English / Filipino) -> catalog material keys. A word that maps to ONE key
# can be priced automatically; a word that maps to several is shown as a list instead.
KEY_ALIASES = {
    "cardboard": ["cardboard"], "karton": ["cardboard"], "carton": ["cardboard"],
    "corrugated": ["cardboard"],
    "pet": ["pet_bottles"], "pet bottles": ["pet_bottles"], "pet bottle": ["pet_bottles"],
    "plastic bottles": ["pet_bottles"], "plastic bottle": ["pet_bottles"],
    "panta": ["panta"], "hard plastic": ["panta"], "plastic containers": ["panta"],
    "sibak": ["plastic_sibak"], "kaltas": ["plastic_kaltas"],
    "glass": ["glass_bottles"], "glass bottles": ["glass_bottles"], "bote": ["glass_bottles"],
    "bottles": ["glass_bottles"],
    "zinc": ["zinc"], "lead": ["lead"], "tingga": ["lead"],
    "stainless": ["stainless_steel"], "stainless steel": ["stainless_steel"],
    "yero": ["iron_sheet"], "taslas": ["iron_sheet"], "iron sheet": ["iron_sheet"],
    "lata": ["tin_cans"], "tin cans": ["tin_cans"], "cans": ["tin_cans"],
    "jalousie": ["aluminum_jalousie"], "jal": ["aluminum_jalousie"],
    "kaldero": ["aluminum_cookware"],
    "dilaw": ["brass_dilaw"], "radiator": ["radiator_light", "radiator_heavy"],
    "condenser": ["condenser"], "mcb": ["mcb"], "tv board": ["tv_board"],
    "hard drive": ["hard_drive"], "hardisk": ["hard_drive"],
    "motherboard": ["motherboard", "motherboard_computer", "motherboard_m2"],
    "aluminum": ["aluminum", "aluminum_hard", "aluminum_jalousie", "aluminum_cookware"],
    "aluminium": ["aluminum", "aluminum_hard", "aluminum_jalousie", "aluminum_cookware"],
    "copper": ["copper_a", "copper_b", "copper_c", "copper_c3", "copper_d"],
    "tanso": ["copper_a", "copper_b", "copper_c", "copper_c3", "copper_d"],
    "tanzo": ["copper_a", "copper_b", "copper_c", "copper_c3", "copper_d"],
    "bakal": ["iron_light", "iron_solid"], "iron": ["iron_light", "iron_solid"],
    "scrap iron": ["iron_light", "iron_solid"],
    "brass": ["brass_dilaw", "brass_shell"],
}

# Words that stand for a whole category rather than particular materials.
CATEGORY_ALIASES = {
    "battery": "Battery", "batteries": "Battery", "baterya": "Battery",
    "e-waste": "E-Waste", "ewaste": "E-Waste", "electronics": "E-Waste",
    "plastic": "Plastic", "plastics": "Plastic", "paper": "Paper", "papel": "Paper",
}

# Pretty names for words the request parser finds, when a word has no single catalog key.
DISPLAY = {
    "cardboard": "Cardboard", "karton": "Cardboard", "carton": "Cardboard",
    "pet": "PET bottles", "pet bottles": "PET bottles", "pet bottle": "PET bottles",
    "plastic bottles": "PET bottles", "plastic bottle": "PET bottles",
    "glass": "Glass bottles", "glass bottles": "Glass bottles", "bote": "Glass bottles",
    "bottles": "Glass bottles", "paper": "Paper", "papel": "Paper", "plastic": "Plastic",
    "plastics": "Plastic", "copper": "Copper", "tanso": "Copper", "aluminum": "Aluminum",
    "aluminium": "Aluminum", "bakal": "Scrap iron", "iron": "Scrap iron",
    "scrap iron": "Scrap iron", "lata": "Tin cans", "cans": "Tin cans",
    "tin cans": "Tin cans", "battery": "Batteries", "batteries": "Batteries",
    "baterya": "Batteries", "e-waste": "E-waste", "ewaste": "E-waste",
    "electronics": "E-waste", "mixed scrap": "Mixed scrap", "scrap": "Mixed scrap",
}


def all_alias_words():
    """Every word/phrase we recognise, longest first (so 'pet bottles' wins over 'pet')."""
    words = set(KEY_ALIASES) | set(CATEGORY_ALIASES) | set(DISPLAY)
    return sorted(words, key=len, reverse=True)