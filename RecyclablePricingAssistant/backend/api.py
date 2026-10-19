# http://127.0.0.1:8000/docs
# api.py - exposes the classifiers over HTTP for the mobile app.
# Run from the project root:  uvicorn backend.api:app --reload
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from Classifier.material_classifier import (
    classify_material,
    labels_or_unknown,
    load_model as load_material_model,
)
from Intent_classifier.intent_classifier import (
    classify_intent,
    load_intent_model,
)

state = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    state["materials"] = load_material_model()   # load models once at startup
    state["intent"] = load_intent_model()
    yield
    state.clear()


app = FastAPI(title="Recyclable Pricing Assistant API", lifespan=lifespan)


# ---- Request / response shapes ------------------------------------------------
class MessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


class MaterialOut(BaseModel):
    label: str
    confidence: float
    evidence: str


class MaterialsResponse(BaseModel):
    labels: list[str]            # e.g. ["Paper", "Plastic"] or ["Unknown"]
    matches: list[MaterialOut]   # per-material confidence + evidence clause


class IntentResponse(BaseModel):
    intent: str                  # Price_Inquiry | Pickup_Request | Bulk_Negotiation | Other
    confidence: float
    needs_review: bool           # True -> ask the operator to double-check
    scores: dict[str, float]


class AnalyzeResponse(BaseModel):
    intent: IntentResponse
    materials: Optional[MaterialsResponse] = None   # None when intent is "Other"


# ---- Helpers ------------------------------------------------------------------
def run_materials(text: str) -> MaterialsResponse:
    matches = classify_material(text, state["materials"])
    return MaterialsResponse(
        labels=labels_or_unknown(matches),
        matches=[
            MaterialOut(label=m.label, confidence=m.confidence, evidence=m.evidence)
            for m in matches
        ],
    )


def run_intent(text: str) -> IntentResponse:
    result = classify_intent(text, state["intent"])
    return IntentResponse(
        intent=result.label,
        confidence=result.confidence,
        needs_review=result.needs_review,
        scores=result.scores,
    )


# ---- Endpoints ----------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/classify", response_model=MaterialsResponse)
def classify(req: MessageRequest):
    """Which recyclable materials does this message mention?"""
    return run_materials(req.text)


@app.post("/intent", response_model=IntentResponse)
def intent(req: MessageRequest):
    """What does the customer want (price, pickup, bulk deal, or unrelated)?"""
    return run_intent(req.text)


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: MessageRequest):
    """Full pipeline: intent first, then materials unless the message is unrelated."""
    intent_result = run_intent(req.text)
    materials = None if intent_result.intent == "Other" else run_materials(req.text)
    return AnalyzeResponse(intent=intent_result, materials=materials)