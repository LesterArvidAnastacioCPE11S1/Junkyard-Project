# price_routes.py - read-only access to the junkshop price survey.
from typing import Optional

from fastapi import APIRouter, Depends, Query

from backend.auth import any_user
from backend.errors import ApiError
from Prices import price_catalog as catalog

router = APIRouter()

@router.get("/prices/materials")
def list_materials(
    q: Optional[str] = Query(None, max_length=100, description="Search words, e.g. karton, bakal, PET"),
    category: Optional[str] = None,
    unit: Optional[str] = Query(None, pattern="^(kg|unit)$"),
    user: dict = Depends(any_user),
):
    """Price range per material. With `q` the best matches come first."""
    if q:
        found = catalog.search(q)
        found = [m for m in found if (not unit or m["unit"] == unit)
                 and (not category or m["category"].lower() == category.lower())]
        return {"materials": found}
    return {"materials": catalog.list_materials(category, unit)}


@router.get("/prices/materials/{key}")
def material_detail(key: str, unit: str = Query("kg", pattern="^(kg|unit)$"),
                    user: dict = Depends(any_user)):
    """One material with the price each surveyed shop pays."""
    found = catalog.stats(key, unit, detail=True)
    if found is None:
        raise ApiError(404, "Material not found in the price survey.")
    return found


@router.get("/prices/categories")
def categories(user: dict = Depends(any_user)):
    return {"categories": catalog.categories()}


@router.get("/prices/shops")
def surveyed_shops(user: dict = Depends(any_user)):
    return {"shops": catalog.shops()}


@router.get("/prices/compare")
def compare(material: str = Query(min_length=1, max_length=100),
            rate: float = Query(gt=0, le=100000),
            unit: str = Query("kg", pattern="^(kg|unit)$"),
            user: dict = Depends(any_user)):
    """Is a requested rate low / normal / high? `material` can be a key or everyday words."""
    key = material if catalog.stats(material, unit) else catalog.resolve(material)
    return catalog.compare(key, rate, unit)


@router.get("/prices/by-classifier")
def by_classifier(labels: list[str] = Query(default=[]), user: dict = Depends(any_user)):
    """Price lines for the labels the material classifier produced, e.g. ?labels=Plastic&labels=Paper"""
    return {"materials": catalog.for_classifier(labels)}