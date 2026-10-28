#!/usr/bin/env python3
"""Standalone evaluation/reporting tool for the Recyclable Pricing Assistant.

This script READS the existing project and datasets. It does not edit source files,
model files, datasets, or the project PDF. Generated artifacts go to ./evaluation_results
beside this script (or --output-dir). The script also exports Appendix B code listings.

Usage:
  python evaluate_project.py --project-root "C:/path/to/extracted/CODES"
  python evaluate_code.py --project-root "C:/path/to/extracted/CODES"
  python evaluate_code.py --project-root "C:/path/to/extracted/CODES" --appendix-b-only
"""
from __future__ import annotations
import argparse, csv, json, sys, warnings
from pathlib import Path
from collections import Counter

import pandas as pd
from sklearn.metrics import (accuracy_score, classification_report, confusion_matrix,
                             f1_score, precision_recall_fscore_support)
from sklearn.model_selection import StratifiedKFold, KFold
from sklearn.preprocessing import MultiLabelBinarizer

LABELS_INTENT = ["Price_Inquiry", "Pickup_Request", "Bulk_Negotiation", "Other"]
SAMPLE = ("Magandang umaga po, may mga bote, karton at aluminum cans po ako. "
          "Magkano po kilo? Pwede po ba kunin sa bahay?")


def read_csv(path):
    return pd.read_csv(path, encoding="utf-8-sig").rename(columns=lambda x: x.strip())


def find_project_root(path: Path) -> Path:
    path = path.expanduser().resolve()
    if (path / "Intent_classifier" / "data").is_dir() and (path / "Classifier" / "data").is_dir():
        return path
    raise FileNotFoundError(
        f"Project root not recognized: {path}\nExpected Intent_classifier/data and Classifier/data folders."
    )


def pct(x): return f"{100*x:.2f}%"


def section(title):
    print("\n" + "=" * 78 + "\n" + title + "\n" + "=" * 78)


def print_counts(title, df, label_col=None):
    print(f"\n{title}: {len(df)} rows")
    if "language" in df:
        print("  Language:", dict(sorted(df.language.fillna("<missing>").value_counts().items())))
    if "source" in df:
        print("  Source:", dict(sorted(df.source.fillna("<missing>").value_counts().items())))
    if label_col == "materials":
        counts = Counter(lab.strip() for value in df[label_col].fillna("").astype(str) for lab in value.split("|") if lab.strip())
        print("  Material label instances:", dict(sorted(counts.items())))
        print("  Distinct label combinations:", int(df[label_col].nunique()))
    elif label_col:
        print("  Label counts:", dict(sorted(df[label_col].fillna("<missing>").value_counts().items())))


def dataset_inventory(root, out):
    section("DATASET INVENTORY — COUNTS READ FROM THE PROJECT CSV FILES")
    intent_train = read_csv(root / "Intent_classifier/data/intent_dataset.csv")
    intent_test = read_csv(root / "Intent_classifier/data/intent_test.csv")
    print_counts("Intent training dataset", intent_train, "intent")
    print_counts("Intent held-out test dataset", intent_test, "intent")
    # Keep this order identical to Classifier/train_material_classifier.py.
    material_files = [
        ("short", root / "Classifier/data/short_material_dataset.csv"),
        ("long", root / "Classifier/data/long_material_dataset.csv"),
        ("vocabulary", root / "Classifier/data/vocab_material_dataset.csv"),
        ("items/single-item", root / "Classifier/data/items_material_dataset.csv"),
    ]
    parts = []
    for name, path in material_files:
        df = read_csv(path); df["dataset_part"] = name; parts.append(df)
        print_counts(f"Material training subset — {name}", df, "materials")
    mat_train = pd.concat(parts, ignore_index=True)
    print_counts("Combined material training rows before duplicate/leakage filtering", mat_train)
    print("  Unique text rows:", int(mat_train.text.astype(str).str.strip().str.lower().nunique()))
    print("  Multi-label rows (2+ labels):", int(mat_train.materials.astype(str).str.contains(r"\|").sum()))
    print("  Material label instances:", dict(sorted(Counter(
        lab.strip() for value in mat_train.materials.astype(str) for lab in value.split("|") if lab.strip()
    ).items())))
    for filename in ["material_test.csv", "material_test_mixed.csv", "material_test_blind.csv"]:
        df = read_csv(root / "Classifier/data" / filename)
        print_counts(f"Material evaluation set — {filename}", df, "materials")
        print("  Multi-label rows (2+ labels):", int(df.materials.astype(str).str.contains(r"\|").sum()))
    rows = []
    for group, df in [("intent_train", intent_train), ("intent_test", intent_test)]:
        rows.append({"dataset": group, "rows": len(df), "language_counts": json.dumps(df.language.value_counts().to_dict()),
                     "source_counts": json.dumps(df.source.value_counts().to_dict()), "label_counts": json.dumps(df.intent.value_counts().to_dict()),
                     "multi_label_rows": 0})
    for name, path in material_files + [("standard_test",root/"Classifier/data/material_test.csv"),
                                         ("mixed_test",root/"Classifier/data/material_test_mixed.csv"),
                                         ("blind_test",root/"Classifier/data/material_test_blind.csv")]:
        df=read_csv(path)
        rows.append({"dataset":name,"rows":len(df),"language_counts":json.dumps(df.language.value_counts().to_dict()),
                     "source_counts":json.dumps(df.source.value_counts().to_dict()),"label_counts":json.dumps(df.materials.value_counts().to_dict()),
                     "multi_label_rows":int(df.materials.astype(str).str.contains(r"\|").sum())})
    pd.DataFrame(rows).to_csv(out / "dataset_inventory.csv", index=False)
    return intent_train, intent_test, mat_train


def evaluate_intent(root, test_df, out):
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "Intent_classifier"))
    from Intent_classifier.intent_classifier import load_intent_model, classify_intent
    saved = load_intent_model(root / "Intent_classifier/models/intent_classifier.joblib")
    y_true, y_pred, rows = [], [], []
    review_count = 0
    for i, r in enumerate(test_df.itertuples(index=False), 1):
        result = classify_intent(str(r.text), saved)
        expected = str(r.intent).strip()
        y_true.append(expected); y_pred.append(result.label); review_count += int(result.needs_review)
        rows.append({"row": i, "text": r.text, "language": getattr(r,"language",""), "expected": expected,
                     "predicted": result.label, "correct": result.label == expected,
                     "confidence": result.confidence, "needs_review": result.needs_review,
                     "scores": json.dumps(result.scores, ensure_ascii=False)})
    labels = [lab for lab in LABELS_INTENT if lab in set(y_true) | set(y_pred)]
    acc = accuracy_score(y_true, y_pred)
    p,r,f,_ = precision_recall_fscore_support(y_true,y_pred,labels=labels,average="macro",zero_division=0)
    print("\nSAVED INTENT MODEL — HELD-OUT TEST")
    print(f"Test rows: {len(y_true)} | Correct: {sum(a==b for a,b in zip(y_true,y_pred))}/{len(y_true)}")
    print(f"Accuracy: {pct(acc)} | Macro precision: {pct(p)} | Macro recall: {pct(r)} | Macro F1: {pct(f)}")
    print(f"Flagged for operator review: {review_count}/{len(y_true)} ({pct(review_count/len(y_true)) if y_true else 'n/a'})")
    print("\nPer-class report:")
    print(classification_report(y_true,y_pred,labels=labels,digits=4,zero_division=0))
    cm=confusion_matrix(y_true,y_pred,labels=labels)
    print("Confusion matrix (rows=expected, columns=predicted):")
    print(pd.DataFrame(cm,index=labels,columns=labels).to_string())
    pd.DataFrame(rows).to_csv(out/"intent_test_predictions.csv",index=False)
    pd.DataFrame(cm,index=labels,columns=labels).to_csv(out/"intent_confusion_matrix.csv")
    macro_f1 = f1_score(y_true,y_pred,labels=labels,average="macro",zero_division=0)
    with open(out/"intent_metrics.json","w",encoding="utf-8") as metrics_file:
        json.dump({"test_rows":len(y_true),"correct":int(sum(a==b for a,b in zip(y_true,y_pred)),),"accuracy":float(acc),
                   "macro_precision":float(p),"macro_recall":float(r),"macro_f1":float(macro_f1),
                   "review_count":int(review_count),"labels":labels},metrics_file,indent=2)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax=plt.subplots(figsize=(9,7))
        im=ax.imshow(cm, interpolation="nearest")
        ax.figure.colorbar(im, ax=ax)
        ax.set(xticks=range(len(labels)),yticks=range(len(labels)),xticklabels=labels,yticklabels=labels,
               ylabel="Expected label",xlabel="Predicted label",title="Intent Classifier Confusion Matrix")
        plt.setp(ax.get_xticklabels(),rotation=30,ha="right",rotation_mode="anchor")
        threshold=cm.max()/2 if cm.size else 0
        for i in range(cm.shape[0]):
            for j in range(cm.shape[1]): ax.text(j,i,str(cm[i,j]),ha="center",va="center")
        fig.tight_layout(); fig.savefig(out/"intent_confusion_matrix.png",dpi=180); plt.close(fig)
    except Exception as e: print(f"[INFO] PNG confusion matrix not created (matplotlib unavailable): {e}")
    return saved, {"test_rows": int(len(y_true)), "correct": int(sum(a == b for a, b in zip(y_true, y_pred))), "accuracy": float(acc), "macro_precision": float(p), "macro_recall": float(r), "macro_f1": float(macro_f1)}


def material_scores(y_true_sets, y_pred_sets):
    tp=fp=fn=exact=0
    for exp,pred in zip(y_true_sets,y_pred_sets):
        tp += len(exp & pred); fp += len(pred-exp); fn += len(exp-pred); exact += int(exp==pred)
    precision=tp/(tp+fp) if tp+fp else 0.0
    recall=tp/(tp+fn) if tp+fn else 0.0
    f1=2*precision*recall/(precision+recall) if precision+recall else 0.0
    return {"rows":len(y_true_sets),"exact_correct":exact,"exact_match":exact/len(y_true_sets) if y_true_sets else 0,
            "precision":precision,"recall":recall,"f1":f1,"tp":tp,"fp":fp,"fn":fn}


def evaluate_material(root, out):
    sys.path.insert(0, str(root / "Classifier"))
    from Classifier.material_classifier import load_model, classify_material, labels_or_unknown
    saved=load_model(root/"Classifier/models/material_classifier.joblib")
    all_metrics=[]
    for filename, shortname in [("material_test.csv","standard"),("material_test_blind.csv","blind"),("material_test_mixed.csv","mixed")]:
        df=read_csv(root/"Classifier/data"/filename)
        truths=[]; preds=[]; rows=[]
        for i,row in enumerate(df.itertuples(index=False),1):
            expected=set(x.strip() for x in str(row.materials).split("|") if x.strip())
            matches=classify_material(str(row.text),saved)
            predicted=set(labels_or_unknown(matches))
            truths.append(expected);preds.append(predicted)
            rows.append({"row":i,"text":row.text,"language":getattr(row,"language",""),"expected":"|".join(sorted(expected)),
                         "predicted":"|".join(sorted(predicted)),"exact_match":expected==predicted,
                         "true_positive_labels":"|".join(sorted(expected&predicted)),"false_positive_labels":"|".join(sorted(predicted-expected)),
                         "missed_labels":"|".join(sorted(expected-predicted)),"match_details":json.dumps([{"label":m.label,"confidence":m.confidence,"evidence":m.evidence} for m in matches],ensure_ascii=False)})
        m=material_scores(truths,preds);m["dataset"]=shortname;all_metrics.append(m)
        print(f"\nSAVED MATERIAL MODEL — {shortname.upper()} TEST ({len(df)} rows)")
        print(f"Exact match: {m['exact_correct']}/{m['rows']} ({pct(m['exact_match'])})")
        print(f"Micro precision: {pct(m['precision'])} | Micro recall: {pct(m['recall'])} | Micro F1: {pct(m['f1'])}")
        print(f"Label counts: TP={m['tp']} FP={m['fp']} FN={m['fn']}")
        pd.DataFrame(rows).to_csv(out/f"material_{shortname}_predictions.csv",index=False)
    pd.DataFrame(all_metrics).to_csv(out/"material_metrics.csv",index=False)
    with open(out/"material_metrics.json","w",encoding="utf-8") as f: json.dump(all_metrics,f,indent=2)
    return saved, all_metrics


def run_sample(root, intent_saved, material_saved, out):
    sys.path.insert(0,str(root))
    from Intent_classifier.intent_classifier import classify_intent
    from Classifier.material_classifier import classify_material, labels_or_unknown
    intent=classify_intent(SAMPLE,intent_saved)
    materials=None
    if intent.label != "Other":
        matches=classify_material(SAMPLE,material_saved)
        materials={"labels":labels_or_unknown(matches),"matches":[{"label":m.label,"confidence":m.confidence,"evidence":m.evidence} for m in matches]}
    result={"sample_message":SAMPLE,"intent":{"label":intent.label,"confidence":intent.confidence,"needs_review":intent.needs_review,"scores":intent.scores},"materials":materials}
    section("SAMPLE MESSAGE ANALYSIS — RUN THROUGH THE PROJECT'S EXISTING CLASSIFIERS")
    print("Message:",SAMPLE)
    print(f"Intent: {intent.label} | confidence={intent.confidence:.3f} | needs_review={intent.needs_review}")
    print("Intent scores:",json.dumps(intent.scores,ensure_ascii=False))
    if materials is None: print("Material analysis: skipped because predicted intent is Other (same gate as backend pipeline).")
    else:
        print("Material labels:",", ".join(materials["labels"]))
        for match in materials["matches"]: print(f"  - {match['label']} ({match['confidence']:.3f}); evidence: {match['evidence']}")
    with open(out/"sample_message_analysis.json","w",encoding="utf-8") as f: json.dump(result,f,ensure_ascii=False,indent=2)


def cross_validate(root, intent_df, material_df):
    """Reproduce the project's training scripts' 5-fold CV procedure in memory."""
    section("5-FOLD CROSS-VALIDATION — MATCHING THE PROJECT TRAINING SCRIPTS")
    from Intent_classifier.intent_classifier import build_model as build_intent, normalize_text, classify_intent
    from Classifier.material_classifier import build_model as build_material, classify_material, labels_or_unknown
    from Classifier.dataset_utils import split_labels

    # Intent: same de-duplication and held-out-text exclusion as train_intent_classifier.py.
    it = intent_df.copy()
    it["text"] = it["text"].astype(str).str.strip()
    it["intent"] = it["intent"].astype(str).str.strip()
    it = it.drop_duplicates(subset="text")
    intent_test_texts = set(read_csv(root / "Intent_classifier/data/intent_test.csv")["text"].astype(str).str.strip().str.lower())
    it = it[~it["text"].str.lower().isin(intent_test_texts)].reset_index(drop=True)

    iy_true, iy_pred = [], []
    splitter = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    for tr, va in splitter.split(it, it["intent"]):
        model = build_intent()
        model.fit(it.iloc[tr]["text"].map(normalize_text), it.iloc[tr]["intent"])
        saved_intent = {"model": model}
        for row in it.iloc[va].itertuples(index=False):
            iy_true.append(row.intent)
            iy_pred.append(classify_intent(row.text, saved_intent).label)

    ilabels = [lab for lab in LABELS_INTENT if lab in set(iy_true) | set(iy_pred)]
    ia = accuracy_score(iy_true, iy_pred)
    ip, ir, iff, _ = precision_recall_fscore_support(iy_true, iy_pred, labels=ilabels, average="macro", zero_division=0)
    print(f"Intent CV rows: {len(it)} | Accuracy: {pct(ia)} | Macro precision: {pct(ip)} | Macro recall: {pct(ir)} | Macro F1: {pct(iff)}")

    # Material: concatenate in trainer's declared order, exact-text de-duplicate,
    # then remove every text appearing in any held-out set. This is important.
    mt = material_df.copy()
    mt["text"] = mt["text"].astype(str).str.strip()
    mt = mt.drop_duplicates(subset="text")
    material_test_texts = set()
    for name in ["material_test.csv", "material_test_mixed.csv", "material_test_blind.csv"]:
        test_path = root / "Classifier/data" / name
        if test_path.exists():
            material_test_texts |= set(read_csv(test_path)["text"].astype(str).str.strip().str.lower())
    mt = mt[~mt["text"].str.lower().isin(material_test_texts)].reset_index(drop=True)

    all_truths, all_preds = [], []
    for tr, va in KFold(n_splits=5, shuffle=True, random_state=42).split(mt):
        train_df = mt.iloc[tr]
        lb = MultiLabelBinarizer()
        y = lb.fit_transform(train_df["materials"].apply(split_labels))
        model = build_material()
        model.fit(train_df["text"], y)
        saved_material = {"model": model, "label_binarizer": lb}
        for row in mt.iloc[va].itertuples(index=False):
            all_truths.append(set(split_labels(row.materials)))
            all_preds.append(set(labels_or_unknown(classify_material(row.text, saved_material))))
    mm = material_scores(all_truths, all_preds)
    print(f"Material CV rows: {len(mt)} | Exact match: {pct(mm['exact_match'])} | Micro precision: {pct(mm['precision'])} | Micro recall: {pct(mm['recall'])} | Micro F1: {pct(mm['f1'])}")
    return {
        "intent": {"rows": int(len(it)), "accuracy": float(ia), "macro_precision": float(ip), "macro_recall": float(ir), "macro_f1": float(iff)},
        "material": mm,
    }


def write_report_tables(out, intent_metrics, material_metrics, cv_metrics):
    """Write copy/paste-ready report tables as CSV and Markdown."""
    rows = []
    if cv_metrics:
        icv = cv_metrics["intent"]
        rows.append({"Model": "Intent", "Evaluation": f"5-fold cross-validation (n={icv['rows']})", "Accuracy / Exact Match": icv["accuracy"], "Precision": icv["macro_precision"], "Recall": icv["macro_recall"], "F1-Score": icv["macro_f1"], "Metric definition": "Intent precision/recall/F1 are macro-averaged"})
    rows.append({"Model": "Intent", "Evaluation": f"Held-out test (n={intent_metrics['test_rows']})", "Accuracy / Exact Match": intent_metrics["accuracy"], "Precision": intent_metrics["macro_precision"], "Recall": intent_metrics["macro_recall"], "F1-Score": intent_metrics["macro_f1"], "Metric definition": "Intent precision/recall/F1 are macro-averaged"})
    if cv_metrics:
        mcv = cv_metrics["material"]
        rows.append({"Model": "Material", "Evaluation": f"5-fold cross-validation (n={mcv['rows']})", "Accuracy / Exact Match": mcv["exact_match"], "Precision": mcv["precision"], "Recall": mcv["recall"], "F1-Score": mcv["f1"], "Metric definition": "Exact match; micro-averaged label precision/recall/F1"})
    for m in material_metrics:
        rows.append({"Model": "Material", "Evaluation": f"{m['dataset'].capitalize()} test (n={m['rows']})", "Accuracy / Exact Match": m["exact_match"], "Precision": m["precision"], "Recall": m["recall"], "F1-Score": m["f1"], "Metric definition": "Exact match; micro-averaged label precision/recall/F1"})

    table = pd.DataFrame(rows)
    table.to_csv(out / "table_2_1_model_performance_summary.csv", index=False, float_format="%.6f")
    # Same rows for copy/paste into report, displayed as percentages.
    pretty = table.copy()
    for col in ["Accuracy / Exact Match", "Precision", "Recall", "F1-Score"]:
        pretty[col] = pretty[col].map(lambda v: f"{v*100:.2f}%" if pd.notna(v) else "N/A")
    markdown = "# Table 2.1. Model Performance Summary\n\n" + pretty.to_markdown(index=False) + "\n\n"
    intent_rows = pretty[pretty["Model"] == "Intent"][["Evaluation", "Accuracy / Exact Match", "Precision", "Recall", "F1-Score"]]
    markdown += "# Table 3.1. Intent Classifier Performance Metrics\n\n" + intent_rows.to_markdown(index=False) + "\n\n"
    material_rows = pretty[pretty["Model"] == "Material"][["Evaluation", "Accuracy / Exact Match", "Precision", "Recall", "F1-Score"]]
    markdown += "# Table 3.2. Material Classifier Performance Metrics Across Test Sets\n\n" + material_rows.to_markdown(index=False) + "\n\n"
    markdown += "## Metric definitions\n\n- Intent precision, recall, and F1 are macro averages.\n- Material exact match requires every predicted label to match the expected label set. Material precision, recall, and F1 are micro averages over material labels.\n- Cross-validation retrains a fresh model within each fold in memory; saved model files are not overwritten.\n"
    (out / "report_tables.md").write_text(markdown, encoding="utf-8")
    print("\n" + "=" * 78 + "\nREPORT-READY TABLES (percentages)\n" + "=" * 78)
    print(pretty[["Model", "Evaluation", "Accuracy / Exact Match", "Precision", "Recall", "F1-Score"]].to_string(index=False))



APPENDIX_B_FILES = [
    ("Intent_classifier/intent_classifier.py", "Intent classifier implementation"),
    ("Intent_classifier/train_intent_classifier.py", "Intent classifier training pipeline"),
    ("Intent_classifier/test_intent_classifier.py", "Intent classifier tests"),
    ("Intent_classifier/dataset_utils.py", "Intent dataset utilities"),
    ("Classifier/material_classifier.py", "Material classifier implementation"),
    ("Classifier/train_material_classifier.py", "Material classifier training pipeline"),
    ("Classifier/test_material_classifier.py", "Material classifier tests"),
    ("Classifier/dataset_utils.py", "Material dataset utilities"),
]

def export_appendix_b(root: Path, out: Path) -> Path:
    """Export a documentation-ready Appendix B from the real project source files."""
    target = out / "Appendix_B_Model_Training_and_Evaluation_Code.md"
    pieces = [
        "# Appendix B. Model Training and Evaluation Code\n\n",
        "This appendix lists the model implementation, training pipelines, dataset utilities, and tests used by the project. The listings are copied from the project source files at evaluation time; they are not rewritten or inferred. File paths are shown above each listing.\n\n",
        "The standalone evaluation/reporting script is also included at the end so that the reported metrics can be reproduced.\n\n",
    ]
    missing = []
    for rel, description in APPENDIX_B_FILES:
        source = root / rel
        pieces.append(f"## {description}\n\n**Source file:** `{rel}`\n\n")
        if not source.is_file():
            pieces.append(f"> Source file not found in this project copy: `{rel}`. This listing was omitted.\n\n")
            missing.append(rel)
            continue
        code = source.read_text(encoding="utf-8", errors="replace")
        suffix = source.suffix.lower()
        lang = "python" if suffix == ".py" else "text"
        pieces.append(f"```{lang}\n{code.rstrip()}\n```\n\n")
    this_script = Path(__file__).resolve()
    pieces.append("## Standalone evaluation and report-table generator\n\n")
    pieces.append(f"**Source file:** `{this_script.name}`\n\n")
    try:
        code = this_script.read_text(encoding="utf-8", errors="replace")
        pieces.append(f"```python\n{code.rstrip()}\n```\n")
    except OSError as exc:
        pieces.append(f"> Could not read the evaluation script for inclusion: {exc}\n")
    target.write_text("".join(pieces), encoding="utf-8")
    print(f"Appendix B source listing written to: {target}")
    if missing:
        print("Appendix B omitted missing project source files:", ", ".join(missing))
    return target


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-root", required=True, help="Path to the extracted project folder containing Intent_classifier and Classifier")
    ap.add_argument("--output-dir", default=None, help="Where to save CSV/JSON/PNG outputs")
    ap.add_argument("--skip-cv", action="store_true", help="Skip 5-fold CV (report tables will omit CV rows)")
    ap.add_argument("--appendix-b-only", action="store_true", help="Only export a documentation-ready Appendix B code listing, without running model evaluations")
    args = ap.parse_args()
    root = find_project_root(Path(args.project_root))
    out = Path(args.output_dir).expanduser().resolve() if args.output_dir else Path(__file__).resolve().parent / "evaluation_results"
    out.mkdir(parents=True, exist_ok=True)
    if args.appendix_b_only:
        export_appendix_b(root, out)
        return
    print("RECYCLABLE PRICING ASSISTANT — EVALUATION + REPORT TABLE GENERATOR")
    print("Project root:", root)
    print("Output folder:", out)
    print("Project source/data/model files are read-only; only the output folder is written.")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        export_appendix_b(root, out)
        intent_train, intent_test, material_train = dataset_inventory(root, out)
        _, intent_metrics = evaluate_intent(root, intent_test, out)
        _, material_metrics = evaluate_material(root, out)
        # For sample inference only, use the saved model files, as the application does.
        from Intent_classifier.intent_classifier import load_intent_model
        from Classifier.material_classifier import load_model as load_material_model
        intent_saved = load_intent_model(root / "Intent_classifier/models/intent_classifier.joblib")
        material_saved = load_material_model(root / "Classifier/models/material_classifier.joblib")
        run_sample(root, intent_saved, material_saved, out)
        # Always write a usable first version of the report tables from held-out tests
        # before the slower CV step, so an interrupted CV run still leaves test results.
        write_report_tables(out, intent_metrics, material_metrics, None)
        cv = None
        cv_path = out / "cross_validation_metrics.json"
        if args.skip_cv:
            # Avoid leaving stale CV metrics from a previous run that could be mistaken
            # for results from the current datasets/code.
            if cv_path.exists():
                cv_path.unlink()
        else:
            cv = cross_validate(root, intent_train, material_train)
            with open(cv_path, "w", encoding="utf-8") as f:
                json.dump(cv, f, indent=2)
            write_report_tables(out, intent_metrics, material_metrics, cv)
        if caught:
            print("\nMODEL/DEPENDENCY WARNINGS:")
            for w in caught[:8]:
                print(f"  {w.category.__name__}: {w.message}")
            if len(caught) > 8:
                print(f"  ... and {len(caught)-8} additional warning(s)")
    section("OUTPUT FILES CREATED")
    for f in sorted(out.iterdir()):
        if f.is_file():
            print(f"{f.name} ({f.stat().st_size:,} bytes)")
    print("\nImportant: use the generated report_tables.md / CSV values, and report the exact model/dataset version and averaging method. The script does not alter the project PDF.")

if __name__ == "__main__": main()
