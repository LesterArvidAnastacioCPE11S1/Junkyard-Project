import joblib
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import StratifiedKFold

from dataset_utils import (
    LABELS, TRAIN_PATH, find_problems, load_all_test_texts, load_dataset,
)
from intent_classifier import MODEL_PATH, build_model, classify_intent, normalize_text


def load_training_data():
    df = load_dataset(TRAIN_PATH)

    problems = [p for p in find_problems(df) if "duplicate" not in p]
    if problems:
        print(f"Fix these problems in {TRAIN_PATH} first:")
        for problem in problems:
            print(" -", problem)
        raise SystemExit(1)
    print(f"Loaded {len(df)} examples from {TRAIN_PATH}")

    df["text"] = df["text"].astype(str).str.strip()
    df["intent"] = df["intent"].astype(str).str.strip()

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
    model = build_model()
    model.fit(df["text"].map(normalize_text), df["intent"])
    return {
        "model": model,
        "languages": sorted(df["language"].unique()),
    }


def cross_validate(df, folds=5):
    """
    Stratified k-fold CV scored with the SAME inference code the app uses.
    Handy for the paper's "Model Training and Evaluation" section. Training
    data is partly templated, so treat these numbers as optimistic and report
    the held-out test set (test_intent_classifier.py) as the headline result.
    """
    y_true, y_pred = [], []
    splitter = StratifiedKFold(folds, shuffle=True, random_state=42)
    for train_idx, val_idx in splitter.split(df, df["intent"]):
        saved = fit(df.iloc[train_idx])
        for row in df.iloc[val_idx].itertuples():
            y_true.append(row.intent)
            y_pred.append(classify_intent(row.text, saved).label)

    print(f"\n{folds}-fold cross-validation on training data ({len(df)} examples):")
    print(f"  Accuracy: {accuracy_score(y_true, y_pred):.3f}\n")
    print(classification_report(y_true, y_pred, labels=LABELS,
                                digits=3, zero_division=0))


def main():
    df = load_training_data()
    print(f"\nTotal training examples: {len(df)}")
    print("Per intent:", df["intent"].value_counts().to_dict())

    print("\nTraining intent classifier...")
    saved = fit(df)

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(saved, MODEL_PATH)

    print("\nTraining completed!")
    print(f"Intent labels: {list(saved['model'].classes_)}")
    print(f"Saved model to: {MODEL_PATH.resolve()}")

    cross_validate(df)


if __name__ == "__main__":
    main()