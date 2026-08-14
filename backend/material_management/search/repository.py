from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import String, cast, or_, text
from sqlalchemy.orm import Session

from components.embedding import JinaAPIEmbeddings

from ..models import Item, ItemCategory


def search_items_text(
    db: Session,
    query_text: str,
    company_id: int,
    item_ids: Optional[list[int]] = None,
    category_id: Optional[int] = None,
    item_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    model_ids: Optional[list[int]] = None,
    matching_model_ids: Optional[list[int]] = None,
    limit: int = 50,
) -> list[Item]:
    pattern = f"%{query_text}%"

    query = (
        db.query(Item)
        .join(ItemCategory, Item.category_id == ItemCategory.id)
        .filter(Item.company_id == company_id)
    )

    if item_ids is not None:
        if not item_ids:
            return []
        query = query.filter(Item.id.in_(item_ids))

    if category_id is not None:
        query = query.filter(Item.category_id == category_id)

    if item_type:
        query = query.filter(Item.item_type == item_type)

    if is_active is not None:
        query = query.filter(Item.is_active == is_active)

    if model_ids is not None:
        if not model_ids:
            return []
        query = query.filter(Item.model_id.in_(model_ids))

    text_conditions = [
        Item.item_code.ilike(pattern),
        Item.name.ilike(pattern),
        Item.description.ilike(pattern),
        Item.barcode.ilike(pattern),
        Item.qr_code.ilike(pattern),
        cast(Item.specs, String).ilike(pattern),
        ItemCategory.code.ilike(pattern),
        ItemCategory.name.ilike(pattern),
    ]
    if matching_model_ids:
        text_conditions.append(Item.model_id.in_(matching_model_ids))

    query = query.filter(or_(*text_conditions))

    return query.order_by(Item.name.asc(), Item.id.asc()).limit(limit).all()


def search_item_hits_semantic(
    db: Session,
    query_text: str,
    company_id: int,
    item_ids: Optional[list[int]] = None,
    category_id: Optional[int] = None,
    item_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    model_ids: Optional[list[int]] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    query_embedding = JinaAPIEmbeddings().embed_query(query_text)

    if not query_embedding:
        return []

    filters = [
        "company_id = :company_id",
        "description_embedding IS NOT NULL",
    ]
    params: dict[str, Any] = {
        "company_id": company_id,
        "query_vec": "[" + ",".join(map(str, query_embedding)) + "]",
        "limit": limit,
    }

    if item_ids is not None:
        if not item_ids:
            return []

        placeholders = ", ".join(f":item_id_{index}" for index in range(len(item_ids)))
        filters.append(f"id IN ({placeholders})")

        for index, item_id in enumerate(item_ids):
            params[f"item_id_{index}"] = item_id

    if category_id is not None:
        filters.append("category_id = :category_id")
        params["category_id"] = category_id

    if item_type:
        filters.append("item_type = :item_type")
        params["item_type"] = item_type

    if is_active is not None:
        filters.append("is_active = :is_active")
        params["is_active"] = is_active

    if model_ids is not None:
        if not model_ids:
            return []
        placeholders = ", ".join(
            f":model_id_{index}" for index in range(len(model_ids))
        )
        filters.append(f"model_id IN ({placeholders})")
        for index, model_id in enumerate(model_ids):
            params[f"model_id_{index}"] = model_id

    rows = db.execute(
        text(
            f"""
            SELECT
                id AS item_id,
                company_id,
                item_code,
                name,
                description,
                category_id,
                unit_id,
                model_id,
                item_type,
                is_active,
                is_critical,
                (1 - (description_embedding <=> (:query_vec)::vector)) AS similarity
            FROM items
            WHERE {" AND ".join(filters)}
            ORDER BY similarity DESC, name ASC, id ASC
            LIMIT :limit
            """
        ),
        params,
    ).fetchall()

    return [
        {
            "item_id": row.item_id,
            "company_id": row.company_id,
            "item_code": row.item_code,
            "name": row.name,
            "description": row.description,
            "category_id": row.category_id,
            "unit_id": row.unit_id,
            "model_id": row.model_id,
            "item_type": row.item_type,
            "is_active": row.is_active,
            "is_critical": row.is_critical,
            "similarity": float(row.similarity) if row.similarity is not None else None,
        }
        for row in rows
    ]
