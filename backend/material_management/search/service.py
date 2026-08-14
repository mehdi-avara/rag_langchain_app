from __future__ import annotations

from typing import Iterable, Optional, Sequence

from sqlalchemy.orm import Session

from Models import User

from ..models import Item
from ..schemas import ItemSearchHit
from ..services import (
    ensure_item_embeddings,
    get_item_or_404,
    item_model_summaries,
    resolve_material_model_ids,
    tenant_id,
)
from .repository import search_item_hits_semantic, search_items_text


def _item_to_text_hit(item: Item, match_source: str = "text") -> ItemSearchHit:
    return ItemSearchHit(
        item_id=item.id,
        company_id=item.company_id,
        item_code=item.item_code,
        name=item.name,
        description=item.description,
        category_id=item.category_id,
        unit_id=item.unit_id,
        model_id=item.model_id,
        item_type=item.item_type,
        is_active=item.is_active,
        is_critical=item.is_critical,
        match_source=match_source,
        similarity=None,
    )


def _item_to_semantic_hit(row: dict, match_source: str = "semantic") -> ItemSearchHit:
    return ItemSearchHit(
        item_id=row["item_id"],
        company_id=row["company_id"],
        item_code=row["item_code"],
        name=row["name"],
        description=row.get("description"),
        category_id=row["category_id"],
        unit_id=row["unit_id"],
        model_id=row.get("model_id"),
        item_type=row["item_type"],
        is_active=row["is_active"],
        is_critical=row["is_critical"],
        match_source=match_source,
        similarity=row.get("similarity"),
    )


def _merge_hits(
    primary_hits: Iterable[ItemSearchHit],
    secondary_hits: Iterable[ItemSearchHit],
    limit: int,
) -> list[ItemSearchHit]:
    output: list[ItemSearchHit] = []
    seen: set[int] = set()

    for hit in list(primary_hits) + list(secondary_hits):
        if hit.item_id in seen:
            continue
        seen.add(hit.item_id)
        output.append(hit)
        if len(output) >= limit:
            break

    return output


def _attach_model_summaries(
    db: Session,
    current_user: User,
    hits: Sequence[ItemSearchHit],
) -> list[ItemSearchHit]:
    model_map = item_model_summaries(
        db,
        current_user,
        [hit.model_id for hit in hits],
    )
    return [
        hit.model_copy(update={"model": model_map.get(hit.model_id)}) for hit in hits
    ]


def validate_item_scope(
    db: Session,
    current_user: User,
    item_ids: Sequence[int],
) -> list[int]:
    result: list[int] = []

    for item_id in list(dict.fromkeys(item_ids)):
        get_item_or_404(db, current_user, item_id)
        result.append(item_id)

    return result


def search_item_hits(
    db: Session,
    current_user: User,
    query_text: str,
    mode: str,
    item_ids: Optional[Sequence[int]] = None,
    category_id: Optional[int] = None,
    item_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    model_id: Optional[int] = None,
    model_name: Optional[str] = None,
    manufacturer: Optional[str] = None,
    model_type: Optional[str] = None,
    limit: int = 20,
) -> list[ItemSearchHit]:
    if mode == "semantic":
        mode = "vector"

    scoped_ids = list(dict.fromkeys(item_ids or []))
    company_id = tenant_id(current_user)
    filtered_model_ids = resolve_material_model_ids(
        db,
        current_user,
        model_id=model_id,
        model_name=model_name,
        manufacturer=manufacturer,
        model_type=model_type,
    )
    if filtered_model_ids is not None and not filtered_model_ids:
        return []
    matching_model_ids = (
        resolve_material_model_ids(
            db,
            current_user,
            query_text=query_text,
        )
        or []
    )

    semantic_hits: list[ItemSearchHit] = []
    semantic_available = False

    if mode in {"vector", "hybrid"}:
        ensure_item_embeddings(
            db=db,
            current_user=current_user,
            item_ids=scoped_ids or None,
        )

        try:
            semantic_rows = search_item_hits_semantic(
                db=db,
                query_text=query_text,
                company_id=company_id,
                item_ids=scoped_ids or None,
                category_id=category_id,
                item_type=item_type,
                is_active=is_active,
                model_ids=filtered_model_ids,
                limit=limit,
            )
            semantic_hits = [_item_to_semantic_hit(row) for row in semantic_rows]
            semantic_available = True
        except Exception:
            semantic_hits = []

    needs_text = (
        mode in {"keyword", "hybrid"}
        or bool(matching_model_ids)
        or (mode == "vector" and not semantic_available)
    )
    text_source = (
        "text_fallback" if mode == "vector" and not semantic_available else "text"
    )

    text_hits: list[ItemSearchHit] = []

    if needs_text:
        text_rows = search_items_text(
            db=db,
            query_text=query_text,
            company_id=company_id,
            item_ids=scoped_ids or None,
            category_id=category_id,
            item_type=item_type,
            is_active=is_active,
            model_ids=filtered_model_ids,
            matching_model_ids=matching_model_ids,
            limit=limit,
        )
        text_hits = [
            _item_to_text_hit(item, match_source=text_source) for item in text_rows
        ]

    if mode == "keyword":
        return _attach_model_summaries(db, current_user, text_hits[:limit])

    if mode == "vector":
        hits = (
            _merge_hits(semantic_hits, text_hits, limit)
            if semantic_available and matching_model_ids
            else semantic_hits[:limit] if semantic_available else text_hits[:limit]
        )
        return _attach_model_summaries(db, current_user, hits)

    return _attach_model_summaries(
        db,
        current_user,
        _merge_hits(semantic_hits, text_hits, limit),
    )
