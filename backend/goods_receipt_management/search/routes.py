from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from Models.user import User
from db.init_db import get_db
from deps import require_permission

from .schemas import GoodsReceiptSearchHit, GoodsReceiptSearchRequest
from .service import (
    search_goods_receipt_hits,
    validate_goods_receipt_scope,
)

router = APIRouter()


@router.post("/search", response_model=list[GoodsReceiptSearchHit])
def search_goods_receipt_notes(
    payload: GoodsReceiptSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("goods_receipt_management:search")
    ),
):
    goods_receipt_ids = validate_goods_receipt_scope(
        db,
        current_user,
        payload.ids,
    )

    return search_goods_receipt_hits(
        db=db,
        current_user=current_user,
        query_text=payload.query,
        mode=payload.mode,
        goods_receipt_ids=goods_receipt_ids,
        limit=payload.limit,
    )
