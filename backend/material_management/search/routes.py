from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from Models import User
from db.init_db import get_db
from deps import require_permission

from ..schemas import ItemSearchHit, ItemSearchRequest
from .service import search_item_hits, validate_item_scope

router = APIRouter()


@router.post("/search", response_model=list[ItemSearchHit])
def search_items(
    payload: ItemSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("material_management:search")),
):
    item_ids = validate_item_scope(db, current_user, payload.ids)

    return search_item_hits(
        db=db,
        current_user=current_user,
        query_text=payload.query,
        mode=payload.mode,
        item_ids=item_ids,
        category_id=payload.category_id,
        item_type=payload.item_type.value if payload.item_type else None,
        is_active=payload.is_active,
        limit=payload.limit,
    )
