"""Raw SQL search queries for purchase_management."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import or_, text
from sqlalchemy.orm import Session, selectinload

from components.embedding import JinaAPIEmbeddings

from ..models import PurchaseOrder


def search_purchase_orders_keyword(
    db: Session,
    query_text: str,
    company_id: int,
    ids: Optional[List[int]] = None,
    supplier_ids: Optional[List[int]] = None,
    limit: int = 20,
) -> List[PurchaseOrder]:
    pattern = f"%{query_text}%"

    query = (
        db.query(PurchaseOrder)
        .options(
            selectinload(PurchaseOrder.supplier)
        )
        .filter(
            PurchaseOrder.company_id == company_id
        )
    )

    if ids is not None:
        if not ids:
            return []

        query = query.filter(
            PurchaseOrder.id.in_(ids)
        )

    conditions = [
        PurchaseOrder.reference_number.ilike(
            pattern
        ),
        PurchaseOrder.title.ilike(pattern),
        PurchaseOrder.description.ilike(pattern),
    ]

    if supplier_ids:
        conditions.append(
            PurchaseOrder.supplier_id.in_(
                supplier_ids
            )
        )

    query = query.filter(or_(*conditions))

    return (
        query.order_by(
            PurchaseOrder.created_at.desc()
        )
        .limit(limit)
        .all()
    )


def search_purchase_orders_semantic(
    db: Session,
    query_text: str,
    company_id: int,
    ids: Optional[List[int]] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    embedding = (
        JinaAPIEmbeddings()
        .embed_query(query_text)
    )

    if not embedding:
        return []

    embedding_str = (
        "["
        + ",".join(
            map(str, embedding)
        )
        + "]"
    )

    filters = [
        "po.company_id = :company_id",
        (
            "po.description_embedding "
            "IS NOT NULL"
        ),
    ]

    params: Dict[str, Any] = {
        "query_vec": embedding_str,
        "company_id": company_id,
        "limit": limit,
    }

    if ids is not None:
        if not ids:
            return []

        placeholders = ", ".join(
            f":po_id_{index}"
            for index in range(len(ids))
        )

        filters.append(
            f"po.id IN ({placeholders})"
        )

        for index, po_id in enumerate(ids):
            params[
                f"po_id_{index}"
            ] = po_id

    where_clause = " AND ".join(filters)

    sql = text(
        f"""
        SELECT
            po.id,
            po.company_id,
            po.reference_number,
            po.title,
            po.supplier_id,
            po.status,
            po.approval_status,
            po.source_rfq_id,
            po.source_material_requisition_id,
            po.created_by_user_id,
            po.created_at,
            po.updated_at,
            (
                1 - (
                    po.description_embedding
                    <=> (:query_vec)::vector
                )
            ) AS similarity
        FROM purchase_orders AS po
        WHERE {where_clause}
        ORDER BY
            similarity DESC,
            po.created_at DESC
        LIMIT :limit
        """
    )

    rows = db.execute(
        sql,
        params,
    ).fetchall()

    return [
        dict(row._mapping)
        for row in rows
    ]
