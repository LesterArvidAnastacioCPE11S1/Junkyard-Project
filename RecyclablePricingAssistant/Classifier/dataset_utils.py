# This is made to catch any typos and stuff within the datasets like Plastics, english, 
# empty rows, and Unknown|Plastic, and it reports them with the CSV line number.

from pathlib import Path

import pandas as pd

VALID_LABELS = {
    "Plastic", "Paper", "Cardboard", "Aluminum",
    "Other_Metals", "Glass", "Electronic_Waste", "Unknown",
}
VALID_LANGUAGES = {"English", "Filipino", "Taglish"}
REQUIRED_COLUMNS = ["text", "language", "materials", "source"]

SHORT_PATH = Path("data/short_material_dataset.csv")
LONG_PATH = Path("data/long_material_dataset.csv")
VOCAB_PATH = Path("data/vocab_material_dataset.csv")

ITEMS_PATH = Path("data/items_material_dataset.csv")

LONG_TEST_PATH = Path("data/material_test.csv")
TEST_PATHS = [
    LONG_TEST_PATH,
    Path("data/material_test_mixed.csv"),
    Path("data/material_test_blind.csv"),
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


def split_labels(value):
    return [label.strip() for label in str(value).split("|") if label.strip()]


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

        if pd.isna(row["materials"]) or not split_labels(row["materials"]):
            problems.append(f"line {line}: materials is empty")
        else:
            labels = split_labels(row["materials"])
            bad = [label for label in labels if label not in VALID_LABELS]
            if bad:
                problems.append(
                    f"line {line}: unknown label(s) {bad} "
                    f"(valid: {sorted(VALID_LABELS)})"
                )
            if "Unknown" in labels and len(labels) > 1:
                problems.append(
                    f"line {line}: 'Unknown' cannot be combined with other labels"
                )

        if row["language"] not in VALID_LANGUAGES:
            problems.append(
                f"line {line}: language '{row['language']}' "
                f"(use one of {sorted(VALID_LANGUAGES)})"
            )

    return problems


def load_test_dataset(path=LONG_TEST_PATH):
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