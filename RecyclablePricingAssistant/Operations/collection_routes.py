# collections_routes.py
# Drivers only ever see their own truck. The owner and dispatchers can look at any truck.
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.auth import any_user
from Operations import services

router = APIRouter()


class StartRouteRequest(BaseModel):
    date: Optional[str] = None
    truck_id: Optional[int] = None


class WeighedItem(BaseModel):
    item_id: int
    actual_kg: float = Field(ge=0, le=100000)


class RecordRequest(BaseModel):
    items: Optional[list[WeighedItem]] = None     # one weight per material, or...
    total_kg: Optional[float] = Field(default=None, gt=0, le=100000)   # ...one total (single-material stop)
    photo_ref: Optional[str] = Field(default=None, max_length=300)


@router.get("/collections/day")
def collections_day(date: Optional[str] = None, truck_id: Optional[int] = None,
                    user: dict = Depends(any_user)):
    """Stops, expected load and progress for one truck on one day (default: today)."""
    return services.collections_day(user["shop_id"], user, date, truck_id)


@router.post("/collections/route/start")
def start_route(body: StartRouteRequest, user: dict = Depends(any_user)):
    return services.start_route(user["shop_id"], user, body.date, body.truck_id)


@router.post("/collections/stops/{pickup_id}/record")
def record_collection(pickup_id: int, body: RecordRequest, user: dict = Depends(any_user)):
    """Weigh, enter the actual kg, and mark the stop as collected."""
    items = [i.model_dump() if hasattr(i, "model_dump") else i.dict() for i in (body.items or [])]
    return services.record_collection(user["shop_id"], user, pickup_id, items or None,
                                      body.total_kg, body.photo_ref)