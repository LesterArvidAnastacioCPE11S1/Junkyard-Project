
import pandas as pd
from pathlib import Path

DATASET_PATH = Path("data/material_dataset.csv")


def main():
    df = pd.read_csv(DATASET_PATH)

    print("Dataset loaded successfully!")
    print(f"Number of examples: {len(df)}")
    print("\nColumns:")
    print(df.columns.tolist())

    print("\nExamples per language:")
    print(df["language"].value_counts())

    print("\nExamples per material label:")
    labels = df["materials"].str.split("|").explode()
    print(labels.value_counts())

    print("\nMissing values:")
    print(df.isnull().sum())


if __name__ == "__main__":
    main()