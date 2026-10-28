# http://127.0.0.1:8000/docs
# api.py - the Recyclable Pricing Assistant backend.
# Run from the project root:  uvicorn backend.api:app --reload
from backend import config  # noqa: F401  (loads .env first)

import asyncio
import os
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend import accounts_db, db, email_service, pipeline
from backend.auth import any_user, bearer  # noqa: F401
from backend.auth_routes import router as auth_router
from backend.channel_routes import router as channel_router
from backend.errors import ApiError
from backend.inbox_routes import router as inbox_router

from Operations import ops_db
from Operations.collection_routes import router as collections_router
from Operations.planning_routes import router as planning_router
from Prices import inventory, price_catalog, subscriptions
from Prices.inventory_routes import router as inventory_router
from Prices.price_routes import router as price_router
from Prices.update_routes import router as price_updates_router

from pathlib import Path
from fastapi.staticfiles import StaticFiles


@asynccontextmanager
async def lifespan(app: FastAPI):
    pipeline.load_models()                 # load both classifiers once at startup
    db.init_db()                           # create / upgrade the database
    ops_db.init_ops_db()                   # trucks, pickups, routes tables
    price_catalog.load()                   # Junkshop price survery
    subscriptions.init_subscriptions_db()  # customers who agreed to price updates
    inventory.init_inventory_db()          # the shop's own price list                      # Shop's price list
    accounts_db.purge_expired_sessions()
    accounts_db.purge_old_attempts((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds"))

    poll_task = None
    interval = int(os.environ.get("EMAIL_POLL_SECONDS", "60") or 0)
    if interval > 0:                       # 0 turns automatic email checking off
        poll_task = asyncio.create_task(email_service.poll_loop(interval))
    yield
    if poll_task:
        poll_task.cancel()
        with suppress(asyncio.CancelledError):
            await poll_task
    pipeline.state.clear()


app = FastAPI(title="Recyclable Pricing Assistant API", lifespan=lifespan)

origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
if origins:                                # only needed for a browser-based app
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)

@app.middleware("http")
async def revalidate_frontend_files(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".js", ".css", ".html")):
        response.headers["Cache-Control"] = "no-cache"      # the browser re-checks, so edits show up on refresh
    return response

app.include_router(auth_router)
app.include_router(inbox_router)
app.include_router(channel_router)
app.include_router(planning_router)
app.include_router(collections_router)
app.include_router(price_router)
app.include_router(inventory_router)
app.include_router(price_updates_router)

from pathlib import Path
from fastapi.staticfiles import StaticFiles

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

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


# Classification endpoints (any logged-in user; nothing is stored)
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/classify", response_model=MaterialsResponse)
def classify(req: MessageRequest, user: dict = Depends(any_user)):
    """Which recyclable materials does this message mention?"""
    return pipeline.run_materials(req.text)


@app.post("/intent", response_model=IntentResponse)
def intent(req: MessageRequest, user: dict = Depends(any_user)):
    """What does the customer want (price, pickup, bulk deal, or unrelated)?"""
    return pipeline.run_intent(req.text)


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: MessageRequest, user: dict = Depends(any_user)):
    """Full pipeline: intent first, then materials unless the message is unrelated."""
    return pipeline.analyze_text(req.text)

# Serves the web app at http://127.0.0.1:8000/  (keep this LAST)
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
