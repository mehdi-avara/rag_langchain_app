from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.orm import Session

from Models.user import User

from ..services import search_stock_items


def search_stock_by_item_ids(
    db: Session,
    current_user: User,
    item_ids: Sequence[int],
    warehouse_id: int | None,
    storage_location_id: int | None,
    limit: int,
) -> list[dict]:
    if not item_ids:
        return []

    return search_stock_items(
        db=db,
        current_user=current_user,
        query_text="",
        item_ids=list(item_ids),
        warehouse_id=warehouse_id,
        storage_location_id=storage_location_id,
        limit=limit,
        offset=0,
    )
