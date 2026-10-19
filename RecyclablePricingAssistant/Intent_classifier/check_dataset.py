import pandas as pd

from dataset_utils import (
    TRAIN_PATH, TEST_PATHS,
    find_problems, load_dataset,
)

DATASET_FILES = {"TRAIN": TRAIN_PATH}
for number, path in enumerate(TEST_PATHS, start=1):
    DATASET_FILES[f"TEST {number} ({path.name})"] = path

TRAIN_NAMES = ("TRAIN",)
TEST_NAMES = tuple(name for name in DATASET_FILES if name not in TRAIN_NAMES)


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
        print("  Per intent:", df["intent"].astype(str).str.strip().value_counts().to_dict())

        # Intent x language table, to spot a language that is missing for an intent.
        table = pd.crosstab(df["intent"].astype(str).str.strip(), df["language"])
        print("  Intent by language:")
        for line in table.to_string().splitlines():
            print("    " + line)

        problems = find_problems(df)
        if problems:
            print(f"  PROBLEMS FOUND ({len(problems)}):")
            for problem in problems:
                print("   -", problem)
        else:
            print("  No problems found.")

    # No test message may appear in a training file.
    for test_name in TEST_NAMES:
        if test_name not in loaded:
            continue
        test_texts = set(loaded[test_name]["text"].astype(str).str.strip().str.lower())
        for name in TRAIN_NAMES:
            if name in loaded:
                train_texts = set(loaded[name]["text"].astype(str).str.strip().str.lower())
                overlap = test_texts & train_texts
                if overlap:
                    print("=" * 60)
                    print(f"WARNING: {len(overlap)} message(s) of {test_name} "
                          f"also appear in {name}.")
                    for text in sorted(overlap):
                        print("   -", text)


if __name__ == "__main__":
    main()