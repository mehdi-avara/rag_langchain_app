from __future__ import annotations

from collections.abc import Iterable, Sequence

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from Models.user import User
from material_management.search.service import search_item_hits

from ..models import StockItem
from ..services import search_stock_items, tenant_id
from .repository import search_stock_by_item_ids
from .schemas import WarehouseSearchHit


def validate_stock_scope(
    db: Session,
    current_user: User,
    stock_item_ids: Sequence[int],
) -> list[int]:
    ids = list(dict.fromkeys(stock_item_ids))

    if not ids:
        return []

    existing_ids = {
        row[0]
        for row in (
            db.query(StockItem.id)
            .filter(
                StockItem.company_id == tenant_id(current_user),
                StockItem.id.in_(ids),
            )
            .all()
        )
    }

    missing = [value for value in ids if value not in existing_ids]

    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stock item not found",
        )

    return ids


def _to_hit(row: dict, match_source: str) -> WarehouseSearchHit:
    return WarehouseSearchHit(
        stock_item_id=row["id"],
        company_id=row["company_id"],
        item_id=row["item_id"],
        item_code=row["item_code"],
        item_name=row["item_name"],
        unit_code=row["unit_code"],
        warehouse_id=row["warehouse_id"],
        warehouse_code=row["warehouse_code"],
        warehouse_name=row["warehouse_name"],
        storage_location_id=row["storage_location_id"],
        storage_location_code=row["storage_location_code"],
        storage_location_name=row["storage_location_name"],
        quantity_on_hand=row["quantity_on_hand"],
        quantity_reserved=row["quantity_reserved"],
        quantity_available=row["quantity_available"],
        unit_cost=row["unit_cost"],
        unit_cost_base=row["unit_cost_base"],
        inventory_value_base=row["inventory_value_base"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        match_source=match_source,
    )


def _merge_hits(
    primary: Iterable[WarehouseSearchHit],
    secondary: Iterable[WarehouseSearchHit],
    limit: int,
) -> list[WarehouseSearchHit]:
    result: list[WarehouseSearchHit] = []
    seen: set[int] = set()

    for hit in list(primary) + list(secondary):
        if hit.stock_item_id in seen:
            continue

        seen.add(hit.stock_item_id)
        result.append(hit)

        if len(result) >= limit:
            break

    return result


def _semantic_item_ids(
    db: Session,
    current_user: User,
    query_text: str,
    limit: int,
) -> tuple[list[int], str]:
    try:
        item_hits = search_item_hits(
            db=db,
            current_user=current_user,
            query_text=query_text,
            mode="vector",
            limit=limit,
        )
    except Exception:
        return [], "item_text_fallback"

    item_ids = [
        hit.item_id
        for hit in item_hits
        if getattr(hit, "item_id", None) is not None
    ]

    source = (
        "semantic_item"
        if any(
            getattr(hit, "match_source", None) == "semantic"
            for hit in item_hits
        )
        else "item_text_fallback"
    )

    return item_ids, source


def search_warehouse_hits(
    db: Session,
    current_user: User,
    query_text: str,
    mode: str,
    stock_item_ids: Sequence[int] | None = None,
    warehouse_id: int | None = None,
    storage_location_id: int | None = None,
    limit: int = 20,
) -> list[WarehouseSearchHit]:
    scoped_ids = list(dict.fromkeys(stock_item_ids or []))
    semantic_hits: list[WarehouseSearchHit] = []

    if mode in {"vector", "hybrid"}:
        item_ids, source = _semantic_item_ids(
            db=db,
            current_user=current_user,
            query_text=query_text,
            limit=limit,
        )

        semantic_hits = [
            _to_hit(row, source)
            for row in search_stock_by_item_ids(
                db=db,
                current_user=current_user,
                item_ids=item_ids,
                warehouse_id=warehouse_id,
                storage_location_id=storage_location_id,
                limit=limit,
            )
            if not scoped_ids or row["id"] in scoped_ids
        ]

    keyword_hits: list[WarehouseSearchHit] = []

    if mode in {"keyword", "hybrid"} or (
        mode == "vector" and not semantic_hits
    ):
        source = "text_fallback" if mode == "vector" else "keyword"

        keyword_hits = [
            _to_hit(row, source)
            for row in search_stock_items(
                db=db,
                current_user=current_user,
                query_text=query_text,
                warehouse_id=warehouse_id,
                storage_location_id=storage_location_id,
                limit=limit,
                offset=0,
            )
            if not scoped_ids or row["id"] in scoped_ids
        ]

    if mode == "keyword":
        return keyword_hits[:limit]

    if mode == "vector":
        return semantic_hits[:limit] or keyword_hits[:limit]

    return _merge_hits(semantic_hits, keyword_hits, limit)
