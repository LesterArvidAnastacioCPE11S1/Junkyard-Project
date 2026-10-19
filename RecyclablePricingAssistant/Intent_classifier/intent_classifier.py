# Intent classifier for the Recyclable Pricing Assistant.
# Decides what a customer message is ABOUT such as a price question, a pickup request,
# a bulk-rate negotiation, or something unrelated (OTPs, promos, thank-yous... etc).
import re
from dataclasses import dataclass
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline, make_union

MODEL_PATH = Path(__file__).resolve().parent / "models" / "intent_classifier.joblib"

# Below this confidence the app should ask the operator to double-check.
REVIEW_THRESHOLD = 0.50

_URL = re.compile(r"(?:https?://|www\.)\S+|\b[\w-]+\.(?:com|ph|ly|net)\S*", re.IGNORECASE)
_LONG_NUMBER = re.compile(r"\d{4,}")   # OTP codes, phone numbers, prize amounts


@dataclass
class IntentResult:
    label: str
    confidence: float          # probability of the chosen label
    scores: dict               # probability of every label
    needs_review: bool         # True when confidence is below the threshold


def normalize_text(text):
    """Light cleanup so codes and links don't confuse the model.

    This is applied OUTSIDE the sklearn pipeline on purpose: the saved model
    then contains only scikit-learn objects and loads from any folder.
    """
    text = str(text).strip()
    text = _URL.sub(" urltoken ", text)
    text = _LONG_NUMBER.sub(" longnumber ", text)
    return re.sub(r"\s+", " ", text).strip()


def build_model(C=10):
    """Word + character TF-IDF -> multinomial logistic regression."""
    features = make_union(
        TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5),
                        lowercase=True, sublinear_tf=True),
        TfidfVectorizer(analyzer="word", ngram_range=(1, 2),
                        lowercase=True, sublinear_tf=True),
    )
    classifier = LogisticRegression(C=C, max_iter=2000, class_weight="balanced")
    return Pipeline([("features", features), ("classifier", classifier)])


def load_intent_model(path=MODEL_PATH):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Model not found at {path}. Train it first.")
    return joblib.load(path)


def classify_intent(text, saved, review_threshold=REVIEW_THRESHOLD):
    """Return an IntentResult for one message."""
    model = saved["model"]
    classes = list(model.classes_)

    clean = normalize_text(text)
    if not clean:
        return IntentResult("Other", 0.0, {c: 0.0 for c in classes}, True)

    probabilities = model.predict_proba([clean])[0]
    best = int(probabilities.argmax())
    confidence = round(float(probabilities[best]), 3)
    scores = {c: round(float(p), 3) for c, p in zip(classes, probabilities)}

    return IntentResult(
        label=classes[best],
        confidence=confidence,
        scores=scores,
        needs_review=confidence < review_threshold,
    )