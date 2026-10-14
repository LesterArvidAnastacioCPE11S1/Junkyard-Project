
from pathlib import Path

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import MultiLabelBinarizer
from sklearn.multiclass import OneVsRestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

DATASET_PATH = Path("data/material_dataset.csv")
MODEL_DIR = Path("models")
MODEL_PATH = MODEL_DIR / "material_classifier.joblib"


def main():
    if not DATASET_PATH.exists():
        raise FileNotFoundError(
            f"Dataset not found: {DATASET_PATH}"
        )

    df = pd.read_csv(DATASET_PATH)

    required_columns = {"text", "language", "materials"}
    if not required_columns.issubset(df.columns):
        raise ValueError(
            f"Dataset must contain: {required_columns}"
        )

    df = df.dropna(subset=["text", "materials"])
    df["text"] = df["text"].astype(str).str.strip()
    df = df[df["text"] != ""]

    # Convert "Plastic|Cardboard" into multiple labels.
    labels = df["materials"].apply(
        lambda value: [
            label.strip()
            for label in str(value).split("|")
            if label.strip()
        ]
    )

    label_binarizer = MultiLabelBinarizer()
    y = label_binarizer.fit_transform(labels)

    # Word and character patterns help with variations
    # in wording and spelling.
    model = Pipeline([
        (
            "tfidf",
            TfidfVectorizer(
                analyzer="char_wb",
                ngram_range=(2, 5),
                lowercase=True,
                min_df=1,
                sublinear_tf=True
            )
        ),
        (
            "classifier",
            OneVsRestClassifier(
                LogisticRegression(
                    max_iter=1000,
                    class_weight="balanced"
                )
            )
        )
    ])

    print("Training material classifier...")
    model.fit(df["text"], y)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    joblib.dump(
        {
            "model": model,
            "label_binarizer": label_binarizer,
            "languages": sorted(df["language"].unique()),
        },
        MODEL_PATH
    )

    print("\nTraining completed!")
    print(f"Training examples: {len(df)}")
    print(f"Material labels: {list(label_binarizer.classes_)}")
    print(f"Saved model to: {MODEL_PATH.resolve()}")


if __name__ == "__main__":
    main()