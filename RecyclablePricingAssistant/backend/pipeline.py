# pipeline.py - loads both classifiers once and runs the two-stage analysis.
from Classifier.material_classifier import (
    classify_material,
    labels_or_unknown,
    load_model as load_material_model,
)
from Intent_classifier.intent_classifier import classify_intent, load_intent_model

state = {}


def load_models():
    state["materials"] = load_material_model()
    state["intent"] = load_intent_model()


def run_materials(text: str) -> dict:
    matches = classify_material(text, state["materials"])
    return {
        "labels": labels_or_unknown(matches),
        "matches": [
            {"label": m.label, "confidence": m.confidence, "evidence": m.evidence}
            for m in matches
        ],
    }


def run_intent(text: str) -> dict:
    result = classify_intent(text, state["intent"])
    return {
        "intent": result.label,
        "confidence": result.confidence,
        "needs_review": result.needs_review,
        "scores": result.scores,
    }


def analyze_text(text: str) -> dict:
    """Intent first; materials only when the message is a real customer inquiry."""
    intent = run_intent(text)
    materials = None if intent["intent"] == "Other" else run_materials(text)
    return {"intent": intent, "materials": materials}