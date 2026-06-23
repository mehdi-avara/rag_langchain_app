from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from Models.user import User
from db.init_db import get_db
from deps import require_permission

from .schemas import WarehouseSearchHit, WarehouseSearchRequest
from .service import search_warehouse_hits, validate_stock_scope

router = APIRouter()


@router.post("/search", response_model=list[WarehouseSearchHit])
def search_warehouse_stock(
    payload: WarehouseSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:search")
    ),
):
    stock_item_ids = validate_stock_scope(
        db,
        current_user,
        payload.ids,
    )

    return search_warehouse_hits(
        db=db,
        current_user=current_user,
        query_text=payload.query,
        mode=payload.mode,
        stock_item_ids=stock_item_ids,
        warehouse_id=payload.warehouse_id,
        storage_location_id=payload.storage_location_id,
        limit=payload.limit,
    )
