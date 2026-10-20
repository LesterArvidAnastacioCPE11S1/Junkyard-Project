import pandas as pd

from dataset_utils import (
    ITEMS_PATH, LONG_PATH, LONG_TEST_PATH, SHORT_PATH, TEST_PATHS, VOCAB_PATH,
    find_problems, load_dataset,
)

DATASET_FILES = {
    "SHORT (training)": SHORT_PATH,
    "LONG (training)": LONG_PATH,
    "VOCAB (training)": VOCAB_PATH,
    "LONG (held-out test)": LONG_TEST_PATH,
    "MIXED (held-out test)": TEST_PATHS[1],
    "BLIND (held-out test)": TEST_PATHS[2],
    "ITEMS (training)": ITEMS_PATH,
}
TRAIN_NAMES = ("SHORT (training)", "LONG (training)", "VOCAB (training)", "ITEMS (training)")
TEST_NAMES = ("LONG (held-out test)", "MIXED (held-out test)", "BLIND (held-out test)")

def main():
    loaded = {}

    for name, path in DATASET_FILES.items():
        print("=" * 60)
        print(f"{name}: {path}")

        if not path.exists():
            print("  File not found, skipping...")
            continue

        try:
            df = load_dataset(path)
        except pd.errors.EmptyDataError:
            print("  File is empty (no header row yet), skipping...")
            continue

        if len(df) == 0:
            print("  No rows yet, skipping...")
            continue

        loaded[name] = df

        print(f"  Examples: {len(df)}")
        print(f"  Text length (chars): min {df['text'].str.len().min()}, "
              f"mean {df['text'].str.len().mean():.0f}, "
              f"max {df['text'].str.len().max()}")
        print("  Per language:", df["language"].value_counts().to_dict())
        print("  Per source:", df["source"].value_counts().to_dict())
        labels = df["materials"].str.split("|").explode().str.strip()
        print("  Per material label:", labels.value_counts().to_dict())

        problems = find_problems(df)
        if problems:
            print(f"  PROBLEMS FOUND ({len(problems)}):")
            for problem in problems:
                print("   -", problem)
        else:
            print("  No problems found.")

    # No test set may appear in any training file.
    for test_name in TEST_NAMES:
        if test_name not in loaded:
            continue
        test_texts = set(loaded[test_name]["text"].str.strip().str.lower())
        for name in TRAIN_NAMES:
            if name in loaded:
                train_texts = set(loaded[name]["text"].str.strip().str.lower())
                overlap = test_texts & train_texts
                if overlap:
                    print("=" * 60)
                    print(f"WARNING: {len(overlap)} message(s) of {test_name} "
                          f"also appear in {name}.")


if __name__ == "__main__":
    main()