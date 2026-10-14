
from datasets import load_dataset, Image
from itertools import islice

DATASET_ID = "huaweilin/waste-classification"


def main():
    print("Connecting to Hugging Face...")

    dataset = load_dataset(
        DATASET_ID,
        split="cleaned",
        streaming=True
    )

    # Prevent automatic decoding of image data.
    dataset = dataset.cast_column("image", Image(decode=False))

    print("\nDataset fields:")
    print(dataset.features)

    print("\nInspecting the first 5 examples:\n")

    for index, example in enumerate(islice(dataset, 5)):

        print(f"Example {index + 1}")
        print("Class:", example.get("class"))
        print("Subclass:", example.get("subclass"))
        print("Options:", example.get("options"))
        print("Answer:", example.get("answer"))
        print("-" * 40)


if __name__ == "__main__":
    main()