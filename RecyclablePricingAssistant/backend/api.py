# http://127.0.0.1:8000/docs
# api.py - the Recyclable Pricing Assistant backend.
# Run from the project root:  uvicorn backend.api:app --reload
from backend import config  # noqa: F401  (loads .env first)

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from backend import inbox_db, pipeline
from backend.inbox_routes import router as inbox_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    pipeline.load_models()    # load both classifiers once at startup
    inbox_db.init_db()        # create the inbox database if it doesn't exist
    yield
    pipeline.state.clear()


app = FastAPI(title="Recyclable Pricing Assistant API", lifespan=lifespan)
app.include_router(inbox_router)


# Request / response shapes 
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


# Classification endpoints (no storage) 
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/classify", response_model=MaterialsResponse)
def classify(req: MessageRequest):
    """Which recyclable materials does this message mention?"""
    return pipeline.run_materials(req.text)


@app.post("/intent", response_model=IntentResponse)
def intent(req: MessageRequest):
    """What does the customer want (price, pickup, bulk deal, or unrelated)?"""
    return pipeline.run_intent(req.text)


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: MessageRequest):
    """Full pipeline: intent first, then materials unless the message is unrelated."""
    return pipeline.analyze_text(req.text)