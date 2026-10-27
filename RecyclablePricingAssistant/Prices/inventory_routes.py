# inventory_routes.py - the shop's price list: add items, change prices, start from the survey.
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.auth import inbox_staff
from Prices import inventory

router = APIRouter()


def _set_fields(model):
    """Only the fields the caller actually sent (so null can mean 'clear this')."""
    return (model.model_dump(exclude_unset=True) if hasattr(model, "model_dump")
            else model.dict(exclude_unset=True))


class ItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    category: Optional[str] = Field(default=None, max_length=60)
    unit: Literal["kg", "unit"] = "kg"
    buy_price: Optional[float] = Field(default=None, gt=0, le=100000)      # what we pay the customer
    sell_price: Optional[float] = Field(default=None, gt=0, le=100000)     # what we charge, if we sell it
    catalog_key: Optional[str] = Field(default="auto", max_length=60)      # survey link: "auto", a key, or empty for none
    aliases: Optional[str] = Field(default=None, max_length=300)           # "karton, carton"
    note: Optional[str] = Field(default=None, max_length=200)


class ItemUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    category: Optional[str] = Field(default=None, max_length=60)
    unit: Optional[Literal["kg", "unit"]] = None
    buy_price: Optional[float] = Field(default=None, gt=0, le=100000)
    sell_price: Optional[float] = Field(default=None, gt=0, le=100000)
    catalog_key: Optional[str] = Field(default=None, max_length=60)
    aliases: Optional[str] = Field(default=None, max_length=300)
    note: Optional[str] = Field(default=None, max_length=200)
    is_active: Optional[bool] = None


@router.get("/inventory/items")
def list_items(user: dict = Depends(inbox_staff)):
    return {"items": inventory.list_items(user["shop_id"])}


@router.post("/inventory/items")
def create_item(req: ItemCreate, user: dict = Depends(inbox_staff)):
    return inventory.create_item(user["shop_id"], user, _set_fields(req))


@router.patch("/inventory/items/{item_id}")
def update_item(item_id: int, req: ItemUpdate, user: dict = Depends(inbox_staff)):
    return inventory.update_item(user["shop_id"], user, item_id, _set_fields(req))


@router.delete("/inventory/items/{item_id}")
def delete_item(item_id: int, user: dict = Depends(inbox_staff)):
    return inventory.delete_item(user["shop_id"], item_id)


@router.get("/inventory/items/{item_id}/history")
def item_history(item_id: int, user: dict = Depends(inbox_staff)):
    return {"history": inventory.history(user["shop_id"], item_id)}


@router.post("/inventory/import-survey")
def import_survey(user: dict = Depends(inbox_staff)):
    """Add every surveyed material that is not on the list yet, priced at the survey average."""
    return inventory.import_survey(user["shop_id"], user)


@router.get("/inventory/match")
def match(text: str = Query(default="", max_length=2000),
          labels: list[str] = Query(default=[]),
          user: dict = Depends(inbox_staff)):
    """Price-list items a customer's message is asking about (for the reply draft)."""
    return inventory.match(user["shop_id"], text, labels)