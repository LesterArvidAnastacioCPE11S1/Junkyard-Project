import joblib
import pandas as pd
from sklearn.model_selection import KFold
from sklearn.preprocessing import MultiLabelBinarizer

from RecyclablePricingAssistant.Classifier.dataset_utils import (
    LONG_PATH, SHORT_PATH, VOCAB_PATH,
    find_problems, load_all_test_texts, load_dataset, split_labels,
)
from RecyclablePricingAssistant.Classifier.material_classifier import (
    MODEL_PATH, build_model, classify_material, labels_or_unknown,
)

DATASET_PATHS = [SHORT_PATH, LONG_PATH, VOCAB_PATH]


def load_training_data():
    frames = []
    for path in DATASET_PATHS:
        part = load_dataset(path)

        problems = [p for p in find_problems(part) if "duplicate" not in p]
        if problems:
            print(f"Fix these problems in {path} first:")
            for problem in problems:
                print(" -", problem)
            raise SystemExit(1)

        print(f"Loaded {len(part)} examples from {path}")
        frames.append(part)

    df = pd.concat(frames, ignore_index=True)
    df["text"] = df["text"].astype(str).str.strip()

    before = len(df)
    df = df.drop_duplicates(subset="text")
    if len(df) < before:
        print(f"Removed {before - len(df)} duplicate text(s).")

    # Never train on any held-out test message.
    leaked = df["text"].str.lower().isin(load_all_test_texts())
    if leaked.any():
        print(f"WARNING: removed {int(leaked.sum())} training row(s) "
              "that are also in a test file.")
        df = df[~leaked]

    return df.reset_index(drop=True)


def fit(df):
    label_binarizer = MultiLabelBinarizer()
    y = label_binarizer.fit_transform(df["materials"].apply(split_labels))
    model = build_model()
    model.fit(df["text"], y)
    return {
        "model": model,
        "label_binarizer": label_binarizer,
        "languages": sorted(df["language"].unique()),
    }


def cross_validate(df, folds=5):
    """
    5-fold CV on the training data, scored with the SAME inference code the
    app uses (clause splitting + thresholds). Useful for the paper's
    "Model Training and Evaluation" section.
    """
    tp = fp = fn = exact = 0
    for train_idx, val_idx in KFold(folds, shuffle=True, random_state=42).split(df):
        saved = fit(df.iloc[train_idx])
        for row in df.iloc[val_idx].itertuples():
            expected = set(split_labels(row.materials))
            predicted = set(labels_or_unknown(classify_material(row.text, saved)))
            tp += len(expected & predicted)
            fp += len(predicted - expected)
            fn += len(expected - predicted)
            exact += expected == predicted

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    print(f"\n{folds}-fold cross-validation on training data "
          f"({len(df)} examples):")
    print(f"  Exact match: {exact}/{len(df)} ({exact / len(df):.1%})")
    print(f"  Micro precision {precision:.3f} | recall {recall:.3f} | F1 {f1:.3f}")


def main():
    df = load_training_data()
    print(f"\nTotal training examples: {len(df)}")

    print("Training material classifier...")
    saved = fit(df)

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(saved, MODEL_PATH)

    print("\nTraining completed!")
    print(f"Material labels: {list(saved['label_binarizer'].classes_)}")
    print(f"Saved model to: {MODEL_PATH.resolve()}")

    cross_validate(df)


if __name__ == "__main__":
    main()