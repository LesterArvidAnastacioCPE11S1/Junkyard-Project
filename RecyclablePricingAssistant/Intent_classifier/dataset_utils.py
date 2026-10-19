# Dataset helpers for the intent classifier. Catches typos in labels/languages,
# empty rows and duplicates, and reports them with the CSV line number.

from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

LABELS = ["Price_Inquiry", "Pickup_Request", "Bulk_Negotiation", "Other"]
VALID_INTENTS = set(LABELS)
VALID_LANGUAGES = {"English", "Filipino", "Taglish"}
REQUIRED_COLUMNS = ["text", "language", "intent", "source"]

TRAIN_PATH = DATA_DIR / "intent_dataset.csv"
TEST_PATHS = [
    DATA_DIR / "intent_test.csv",
]


def load_dataset(path):
    """Read one dataset CSV (handles the BOM that Excel adds)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")

    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = [column.strip() for column in df.columns]

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path} is missing columns: {missing}")
    return df


def find_problems(df):
    """Return a list of readable problems (line numbers match the CSV file)."""
    problems = []
    seen = {}

    for index, row in df.iterrows():
        line = index + 2  # line 1 is the header

        text = row["text"]
        if pd.isna(text) or not str(text).strip():
            problems.append(f"line {line}: text is empty")
            continue

        key = str(text).strip().lower()
        if key in seen:
            problems.append(f"line {line}: duplicate of line {seen[key]}")
        else:
            seen[key] = line

        intent = row["intent"]
        if pd.isna(intent) or str(intent).strip() not in VALID_INTENTS:
            problems.append(
                f"line {line}: intent '{intent}' (valid: {sorted(VALID_INTENTS)})"
            )

        if row["language"] not in VALID_LANGUAGES:
            problems.append(
                f"line {line}: language '{row['language']}' "
                f"(use one of {sorted(VALID_LANGUAGES)})"
            )

    return problems


def load_test_dataset(path):
    """Return one held-out test set, or None if the file is missing or empty."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        df = load_dataset(path)
    except pd.errors.EmptyDataError:
        return None
    return df if len(df) > 0 else None


def load_all_test_texts():
    """Every held-out test text (lower-cased), used to stop training leakage."""
    texts = set()
    for path in TEST_PATHS:
        df = load_test_dataset(path)
        if df is not None:
            texts |= set(df["text"].astype(str).str.strip().str.lower())
    return texts