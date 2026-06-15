"""Search route for purchase_management.

POST /purchase/orders/search
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from Models import User

from .service import PurchaseOrderSearchHit, search_purchase_order_hits

router = APIRouter()


class PurchaseOrderSearchRequest(BaseModel):
    query: str
    ids: List[int] = []
    mode: str = "hybrid"  # keyword | semantic | hybrid
    limit: int = 20


@router.post(
    "/purchase/orders/search",
    response_model=List[PurchaseOrderSearchHit],
    summary="Search purchase orders (keyword / semantic / hybrid)",
    tags=["purchase_management"],
)
def search_purchase_orders(
    payload: PurchaseOrderSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("purchase_management:orders:search")),
):
    return search_purchase_order_hits(
        db=db,
        current_user=current_user,
        query_text=payload.query,
        mode=payload.mode,
        ids=payload.ids or None,
        limit=payload.limit,
    )
