# planning_routes.py - the Pickup planning screen and the requests behind it.
# Only the owner and dispatchers use these (drivers see their own route in collections_routes.py).
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.auth import inbox_staff, owner_only
from Operations import ops_db, services

VehicleType = Literal["tricycle", "multicab", "pickup", "small_truck", "large_truck"]

router = APIRouter()

def _set_fields(model):
    """Only the fields the caller actually sent (so null can mean 'clear this')."""
    return (model.model_dump(exclude_unset=True) if hasattr(model, "model_dump")
            else model.dict(exclude_unset=True))


# request shapes
class TruckCreate(BaseModel):
    code: str = Field(min_length=1, max_length=20)                 # e.g. SD-01
    label: str = Field(min_length=1, max_length=60)                # e.g. Small truck
    capacity_kg: float = Field(gt=0, le=100000)
    vehicle_type: Optional[VehicleType] = None                     # guessed from the label when empty
    driver_id: Optional[int] = None


class TruckUpdate(BaseModel):
    code: Optional[str] = Field(default=None, min_length=1, max_length=20)
    label: Optional[str] = Field(default=None, min_length=1, max_length=60)
    capacity_kg: Optional[float] = Field(default=None, gt=0, le=100000)
    vehicle_type: Optional[VehicleType] = None
    driver_id: Optional[int] = None
    is_active: Optional[bool] = None


class ItemIn(BaseModel):
    material: str = Field(min_length=1, max_length=100)
    expected_kg: float = Field(default=0, ge=0, le=100000)
    requested_rate: Optional[float] = Field(default=None, gt=0, le=100000)   # pesos per kg
    catalog_key: Optional[str] = Field(default=None, max_length=60)


class PickupCreate(BaseModel):
    customer_name: str = Field(min_length=1, max_length=200)
    organization: Optional[str] = Field(default=None, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=50)
    address: Optional[str] = Field(default=None, max_length=300)
    area: Optional[str] = Field(default=None, max_length=100)
    access_note: Optional[str] = Field(default=None, max_length=300)
    stop_note: Optional[str] = Field(default=None, max_length=300)
    pickup_date: Optional[str] = None            # 2026-10-21
    window_start: Optional[str] = None           # 13:00
    window_end: Optional[str] = None             # 15:00
    items: list[ItemIn] = []


class PickupEdit(BaseModel):
    customer_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    organization: Optional[str] = Field(default=None, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=50)
    address: Optional[str] = Field(default=None, max_length=300)
    area: Optional[str] = Field(default=None, max_length=100)
    access_note: Optional[str] = Field(default=None, max_length=300)
    stop_note: Optional[str] = Field(default=None, max_length=300)
    pickup_date: Optional[str] = None
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    items: Optional[list[ItemIn]] = None


class RateIn(BaseModel):
    item_id: int
    approved_rate: float = Field(gt=0, le=100000)


class ApproveRequest(BaseModel):
    truck_id: int
    pickup_date: Optional[str] = None
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    rates: list[RateIn] = []         # leave out a line to accept the customer's requested rate
    force: bool = False              # confirm even if the truck is over capacity / double-booked


class CancelRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=300)


class SuggestRequest(BaseModel):
    """What the review screen currently shows; nothing here is saved."""
    pickup_date: Optional[str] = None
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    total_kg: Optional[float] = Field(default=None, ge=0, le=100000)


class AvailabilityIn(BaseModel):
    shift_start: str = "08:00"
    shift_end: str = "17:00"
    work_days: list[int] = Field(default=[1, 2, 3, 4, 5, 6, 7], max_length=7)   # 1 = Monday ... 7 = Sunday


class TimeOffIn(BaseModel):
    off_date: str
    start_time: Optional[str] = None       # leave both times empty for the whole day
    end_time: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=200)


# planning
@router.get("/planning/day")
def planning_day(date: Optional[str] = None, user: dict = Depends(inbox_staff)):
    """Everything the Pickup planning screen shows for one day (default: today)."""
    return services.day_overview(user["shop_id"], date)


@router.get("/planning/trucks")
def list_trucks(include_inactive: bool = False, user: dict = Depends(inbox_staff)):
    return {"trucks": ops_db.list_trucks(user["shop_id"], active_only=not include_inactive)}


@router.post("/planning/trucks", status_code=201)
def create_truck(body: TruckCreate, user: dict = Depends(owner_only)):
    return services.create_truck(user["shop_id"], body.code, body.label, body.capacity_kg, body.driver_id,
                                 body.vehicle_type)


@router.patch("/planning/trucks/{truck_id}")
def update_truck(truck_id: int, body: TruckUpdate, user: dict = Depends(owner_only)):
    return services.update_truck(user["shop_id"], truck_id, _set_fields(body))


# driver availability (dispatchers need this too: they handle sick days and day-offs)
@router.get("/planning/availability")
def list_availability(user: dict = Depends(inbox_staff)):
    return {"drivers": services.list_availability(user["shop_id"])}


@router.put("/planning/availability/{driver_id}")
def set_availability(driver_id: int, body: AvailabilityIn, user: dict = Depends(inbox_staff)):
    return services.set_availability(user["shop_id"], driver_id, body.shift_start, body.shift_end, body.work_days)


@router.post("/planning/availability/{driver_id}/time-off", status_code=201)
def add_time_off(driver_id: int, body: TimeOffIn, user: dict = Depends(inbox_staff)):
    return services.add_time_off(user["shop_id"], driver_id, body.off_date, body.start_time, body.end_time, body.note)


@router.delete("/planning/time-off/{time_off_id}")
def remove_time_off(time_off_id: int, user: dict = Depends(inbox_staff)):
    services.remove_time_off(user["shop_id"], time_off_id)
    return {"ok": True}


# pickups
@router.post("/pickups", status_code=201)
def create_pickup(body: PickupCreate, user: dict = Depends(inbox_staff)):
    """Add a pickup by hand. It waits for price approval like any other request."""
    fields = _set_fields(body)
    items = fields.pop("items", [])
    return services.create_pickup(user["shop_id"], fields, items)


@router.post("/pickups/from-message/{message_id}", status_code=201)
def pickup_from_message(message_id: int, user: dict = Depends(inbox_staff)):
    """Turn an inquiry into a draft pickup (weights, rates and time are read from the text)."""
    pickup, created = services.create_from_message(user["shop_id"], message_id)
    return {"created": created, "pickup": pickup}


@router.get("/pickups")
def list_pickups(
    date: Optional[str] = None,
    status: Optional[Literal["pending_approval", "confirmed", "collected", "cancelled"]] = None,
    limit: int = Query(100, ge=1, le=200),
    user: dict = Depends(inbox_staff),
):
    day = services.check_date(date) if date else None
    return {"pickups": ops_db.list_pickups(user["shop_id"], date=day,
                                           statuses=(status,) if status else None, limit=limit)}


@router.get("/pickups/{pickup_id}")
def get_pickup(pickup_id: int, user: dict = Depends(inbox_staff)):
    return services.get_pickup(user["shop_id"], pickup_id)


@router.patch("/pickups/{pickup_id}")
def edit_pickup(pickup_id: int, body: PickupEdit, user: dict = Depends(inbox_staff)):
    fields = _set_fields(body)
    items = fields.pop("items", None)
    return services.edit_pickup(user["shop_id"], pickup_id, fields, items)


@router.get("/pickups/{pickup_id}/price-review")
def price_review(pickup_id: int, user: dict = Depends(inbox_staff)):
    """Requested rates next to what the surveyed junkshops pay (the 'Review requested prices' step)."""
    return services.price_review(user["shop_id"], pickup_id)


@router.get("/pickups/{pickup_id}/check")
def check_truck(
    pickup_id: int,
    truck_id: int,
    date: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    user: dict = Depends(inbox_staff),
):
    """Would this pickup fit on that truck at that time? (capacity and overlapping stops)"""
    return services.check_for_truck(user["shop_id"], pickup_id, truck_id, date, start, end)


@router.post("/pickups/{pickup_id}/suggest-driver")
def suggest_driver(pickup_id: int, body: SuggestRequest, user: dict = Depends(inbox_staff)):
    """Which driver and vehicle fit this load, date and time? (nothing is saved until approval)"""
    return services.suggest_driver(user["shop_id"], pickup_id, body.pickup_date, body.window_start,
                                   body.window_end, body.total_kg)


@router.post("/pickups/{pickup_id}/approve")
def approve_pickup(pickup_id: int, body: ApproveRequest, user: dict = Depends(inbox_staff)):
    rates = {r.item_id: r.approved_rate for r in body.rates}
    return services.approve(user["shop_id"], user, pickup_id, body.truck_id, body.pickup_date,
                            body.window_start, body.window_end, rates, body.force)

@router.post("/pickups/{pickup_id}/notify-driver")
def notify_driver(pickup_id: int, user: dict = Depends(inbox_staff)):
    """Email the assigned driver this pickup's details again."""
    return services.resend_driver_notice(user["shop_id"], pickup_id)

@router.post("/pickups/{pickup_id}/cancel")
def cancel_pickup(pickup_id: int, body: CancelRequest, user: dict = Depends(inbox_staff)):
    return services.cancel(user["shop_id"], pickup_id, body.reason)