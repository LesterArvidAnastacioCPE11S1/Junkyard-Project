"""
Evaluates the intent classifier on the held-out test set(s).
"""

import sys

from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score

from dataset_utils import LABELS, TEST_PATHS, load_test_dataset
from intent_classifier import classify_intent, load_intent_model

SHOW_PASSING = True          # set False to print only the failing messages
PREVIEW_CHARS = 90


def show_message(text, saved):
    result = classify_intent(text, saved)
    print(f"\nMessage: {text}")
    print(f"  -> {result.label}  ({result.confidence:.2f})"
          f"{'   [needs review]' if result.needs_review else ''}")
    for label, score in sorted(result.scores.items(), key=lambda kv: -kv[1]):
        print(f"       {label:<18}{score:.3f}")


def print_confusion(y_true, y_pred):
    matrix = confusion_matrix(y_true, y_pred, labels=LABELS)
    print("\nConfusion matrix (rows = expected, columns = predicted):")
    print(f"{'':<18}" + "".join(f"{label[:12]:>14}" for label in LABELS))
    for label, row in zip(LABELS, matrix):
        print(f"{label:<18}" + "".join(f"{count:>14}" for count in row))


def evaluate_file(path, saved, y_true, y_pred, review_count):
    df = load_test_dataset(path)
    if df is None:
        print(f"\n{path}: missing or empty, skipped.")
        return

    print("\n" + "=" * 72)
    print(f"{path}  ({len(df)} messages)")
    print("=" * 72)

    for number, row in enumerate(df.itertuples(), start=1):
        expected = str(row.intent).strip()
        result = classify_intent(row.text, saved)
        correct = result.label == expected

        y_true.append(expected)
        y_pred.append(result.label)
        review_count[0] += result.needs_review

        if correct and not SHOW_PASSING:
            continue
        status = "OK  " if correct else "MISS"
        preview = row.text[:PREVIEW_CHARS].replace("\n", " ")
        print(f"\n[{status}] #{number}  {preview}")
        if correct:
            print(f"       {result.label}  ({result.confidence:.2f})")
        else:
            print(f"       expected: {expected}")
            print(f"       got:      {result.label}  ({result.confidence:.2f})")


def main():
    saved = load_intent_model()

    if len(sys.argv) > 1:
        show_message(" ".join(sys.argv[1:]), saved)
        return

    y_true, y_pred, review_count = [], [], [0]
    for path in TEST_PATHS:
        evaluate_file(path, saved, y_true, y_pred, review_count)

    if not y_true:
        return

    print("\n" + "=" * 72)
    print("OVERALL")
    print("=" * 72)
    print(f"Accuracy: {accuracy_score(y_true, y_pred):.3f}   "
          f"Macro F1: {f1_score(y_true, y_pred, labels=LABELS, average='macro', zero_division=0):.3f}   "
          f"({sum(t == p for t, p in zip(y_true, y_pred))}/{len(y_true)} correct)")
    print(f"Flagged for review (low confidence): {review_count[0]}/{len(y_true)}\n")
    print(classification_report(y_true, y_pred, labels=LABELS, digits=3, zero_division=0))
    print_confusion(y_true, y_pred)


if __name__ == "__main__":
    main()