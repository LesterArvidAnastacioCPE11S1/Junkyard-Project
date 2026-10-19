# this is the main classifier for the Recyclable Pricing Assistant and it is trained on the
# "materials" column of the dataset, which is a pipe-separated list of materials.
import re
from dataclasses import dataclass
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier
from sklearn.pipeline import Pipeline, make_union


MODEL_PATH = Path(__file__).resolve().parent / "models" / "material_classifier.joblib"

# ---- Inference settings ------------------------------------------------------
THRESHOLD = 0.50          # minimum clause-level probability to accept a material
UNKNOWN_TRIGGER = 0.70    # a clause this "unknown-ish" means the sender is unsure
UNKNOWN_STRICT = 0.80     # ...so materials then need this much confidence instead

# Words/phrases that split one sentence into item clauses.
_CLAUSE_SPLIT = re.compile(
    r"[,;:\n]+"
    r"|\s+(?:and|at|pati|pati na|kasama|kasama ang|plus|as well as|such as|"
    r"including|also|saka|tsaka|tapos|or|"
    # list introducers: "...mixed recyclables consisting of PET bottles, ..."
    r"consisting of|composed of|made up of|namely|like|"
    r"gaya ng|tulad ng|binubuo ng|kabilang ang)\s+",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

# Phrases that mean "what follows is NOT being sold", e.g.
# "We have separated them from the plastic bottles and glass jars."
# Kept deliberately strict: ambiguous cues such as "other than"
_EXCLUDE_CUE = re.compile(
    r"\b(?:separated\s+(?:them\s+)?from|except(?:\s+for)?|excluding|"
    r"not\s+including|not\s+selling|not\s+for\s+sale|maliban(?:\s+sa)?|"
    r"hindi\s+kasama|(?:huwag|wag)\s+isama|hindi\s+ibebenta)\b",
    re.IGNORECASE,
)


@dataclass
class MaterialMatch:
    label: str
    confidence: float   # best clause-level probability for this material
    evidence: str       # the clause that produced it


def build_model(C=10):
    """Word + character TF-IDF -> one-vs-rest logistic regression."""
    features = make_union(
        TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5),
                        lowercase=True, sublinear_tf=True),
        TfidfVectorizer(analyzer="word", ngram_range=(1, 2),
                        lowercase=True, sublinear_tf=True),
    )
    classifier = OneVsRestClassifier(
        LogisticRegression(C=C, max_iter=2000, class_weight="balanced")
    )
    return Pipeline([("features", features), ("classifier", classifier)])


def split_into_clauses(text):
    """Return the clauses that should be scored, dropping excluded text."""
    clauses = []
    for sentence in _SENTENCE_SPLIT.split(str(text)):
        cue = _EXCLUDE_CUE.search(sentence)
        if cue:
            # Keep only what comes BEFORE the cue; the rest is "not for sale".
            sentence = sentence[:cue.start()]
        for part in _CLAUSE_SPLIT.split(sentence):
            part = part.strip()
            if part:
                clauses.append(part)
    return clauses


def load_model(path=MODEL_PATH):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Model not found at {path}. Train it first.")
    return joblib.load(path)


def classify_material(text, saved, threshold=THRESHOLD):
    """
    Return a list of MaterialMatch (best first), or [] if nothing is
    recognised. An empty list means "Unknown" - the caller decides how to
    present that (see `labels_or_unknown`).
    """
    model = saved["model"]
    classes = list(saved["label_binarizer"].classes_)

    clauses = split_into_clauses(text)
    if not clauses:
        return []

    probabilities = model.predict_proba(clauses)

    # Is the sender telling us they don't know what the items are?
    unknown_idx = classes.index("Unknown") if "Unknown" in classes else None
    unsure = (
        unknown_idx is not None
        and probabilities[:, unknown_idx].max() >= UNKNOWN_TRIGGER
    )
    cutoff = max(threshold, UNKNOWN_STRICT) if unsure else threshold

    best = {}
    for clause, row in zip(clauses, probabilities):
        for label, p in zip(classes, row):
            if label == "Unknown" or p < cutoff:
                continue
            if label not in best or p > best[label].confidence:
                best[label] = MaterialMatch(label, round(float(p), 3), clause)

    return sorted(best.values(), key=lambda m: -m.confidence)


def labels_or_unknown(matches):
    return sorted(m.label for m in matches) or ["Unknown"]