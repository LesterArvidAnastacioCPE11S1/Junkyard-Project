"""
Evaluates the material classifier on the held-out test sets and
Every message that is printed here is the SAME message that gets scored, and
its expected labels come from the CSV, so the numbers always match the lines
above them.
"""

import sys
from collections import Counter

from RecyclablePricingAssistant.Classifier.dataset_utils import TEST_PATHS, load_test_dataset, split_labels
from RecyclablePricingAssistant.Classifier.material_classifier import classify_material, labels_or_unknown, load_model

SHOW_PASSING = True          # set False to print only the failing messages
PREVIEW_CHARS = 90


def show_message(text, saved):
    matches = classify_material(text, saved)
    print(f"\nMessage: {text}")
    if not matches:
        print("  -> Unknown")
    for m in matches:
        print(f"  -> {m.label:<17} {m.confidence:.2f}   from: \"{m.evidence}\"")


def evaluate_file(path, saved, totals):
    df = load_test_dataset(path)
    if df is None:
        print(f"\n{path}: missing or empty, skipped.")
        return

    print("\n" + "=" * 72)
    print(f"{path}  ({len(df)} messages)")
    print("=" * 72)

    exact = tp = fp = fn = 0
    for number, row in enumerate(df.itertuples(), start=1):
        expected = set(split_labels(row.materials))
        matches = classify_material(row.text, saved)
        predicted = set(labels_or_unknown(matches))

        for label in expected | predicted:
            if label in expected and label in predicted:
                totals["tp"][label] += 1
                tp += 1
            elif label in predicted:
                totals["fp"][label] += 1
                fp += 1
            else:
                totals["fn"][label] += 1
                fn += 1

        correct = predicted == expected
        exact += correct
        totals["exact"] += correct
        totals["n"] += 1

        if correct and not SHOW_PASSING:
            continue
        status = "OK  " if correct else "MISS"
        preview = row.text[:PREVIEW_CHARS].replace("\n", " ")
        print(f"\n[{status}] #{number}  {preview}...")
        print(f"       expected: {sorted(expected)}")
        print(f"       got:      {sorted(predicted)}")
        if not correct:
            print(f"       missed: {sorted(expected - predicted)}   "
                  f"extra: {sorted(predicted - expected)}")
            for m in matches:
                if m.label in predicted - expected:
                    print(f"       (false alarm '{m.label}' came from: "
                          f"\"{m.evidence}\")")

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    print("-" * 72)
    print(f"Exact match: {exact}/{len(df)} ({exact / len(df):.0%})   "
          f"precision {precision:.3f} | recall {recall:.3f} | F1 {f1:.3f}")
    totals["tp_all"] += tp
    totals["fp_all"] += fp
    totals["fn_all"] += fn


def print_summary(totals):
    tp, fp, fn = totals["tp_all"], totals["fp_all"], totals["fn_all"]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    print("\n" + "=" * 72)
    print("OVERALL (all test sets combined)")
    print("=" * 72)
    print(f"Exact match: {totals['exact']}/{totals['n']} "
          f"({totals['exact'] / totals['n']:.0%})")
    print(f"Micro precision {precision:.3f} | recall {recall:.3f} | F1 {f1:.3f}\n")

    print(f"{'Label':<18}{'Precision':>10}{'Recall':>10}{'F1':>8}{'Support':>9}")
    labels = sorted(set(totals["tp"]) | set(totals["fp"]) | set(totals["fn"]))
    for label in labels:
        t, f_p, f_n = totals["tp"][label], totals["fp"][label], totals["fn"][label]
        p = t / (t + f_p) if t + f_p else 0.0
        r = t / (t + f_n) if t + f_n else 0.0
        f = 2 * p * r / (p + r) if p + r else 0.0
        print(f"{label:<18}{p:>10.3f}{r:>10.3f}{f:>8.3f}{t + f_n:>9}")


def main():
    saved = load_model()

    if len(sys.argv) > 1:
        show_message(" ".join(sys.argv[1:]), saved)
        return

    totals = {"tp": Counter(), "fp": Counter(), "fn": Counter(),
              "exact": 0, "n": 0, "tp_all": 0, "fp_all": 0, "fn_all": 0}
    for path in TEST_PATHS:
        evaluate_file(path, saved, totals)
    if totals["n"]:
        print_summary(totals)


if __name__ == "__main__":
    main()