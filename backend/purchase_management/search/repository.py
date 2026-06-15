"""Raw SQL search queries for purchase_management.

Follows the same pattern as financial_management/search/repository.py.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from components.embedding import JinaAPIEmbeddings

from ..models import PurchaseOrder


def search_purchase_orders_keyword(
    db: Session,
    query_text: str,
    company_id: int,
    ids: Optional[List[int]] = None,
    limit: int = 20,
) -> List[PurchaseOrder]:
    """ILIKE search across all meaningful text fields."""
    pattern = f"%{query_text}%"
    q = db.query(PurchaseOrder).filter(PurchaseOrder.company_id == company_id)

    if ids is not None:
        if not ids:
            return []
        q = q.filter(PurchaseOrder.id.in_(ids))

    q = q.filter(
        or_(
            PurchaseOrder.reference_number.ilike(pattern),
            PurchaseOrder.supplier_name.ilike(pattern),
            PurchaseOrder.title.ilike(pattern),
            PurchaseOrder.description.ilike(pattern),
        )
    )
    return q.order_by(PurchaseOrder.created_at.desc()).limit(limit).all()


def search_purchase_orders_semantic(
    db: Session,
    query_text: str,
    company_id: int,
    ids: Optional[List[int]] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """pgvector cosine similarity search on description_embedding."""
    embedding = JinaAPIEmbeddings().embed_query(query_text)
    if not embedding:
        return []

    embedding_str = "[" + ",".join(map(str, embedding)) + "]"

    filters = [
        "po.company_id = :company_id",
        "po.description_embedding IS NOT NULL",
    ]
    params: Dict[str, Any] = {
        "query_vec": embedding_str,
        "company_id": company_id,
        "limit": limit,
    }

    if ids is not None:
        if not ids:
            return []
        placeholders = ", ".join(f":po_id_{i}" for i in range(len(ids)))
        filters.append(f"po.id IN ({placeholders})")
        for i, po_id in enumerate(ids):
            params[f"po_id_{i}"] = po_id

    where_clause = " AND ".join(filters)

    sql = text(f"""
        SELECT
            po.id,
            po.company_id,
            po.reference_number,
            po.title,
            po.supplier_name,
            po.status,
            po.approval_status,
            po.currency_id,
            po.base_currency_id,
            po.created_by_user_id,
            po.created_at,
            po.updated_at,
            (1 - (po.description_embedding <=> (:query_vec)::vector)) AS similarity
        FROM purchase_orders po
        WHERE {where_clause}
        ORDER BY similarity DESC, po.created_at DESC
        LIMIT :limit
    """)

    rows = db.execute(sql, params).fetchall()
    return [dict(row._mapping) for row in rows]
