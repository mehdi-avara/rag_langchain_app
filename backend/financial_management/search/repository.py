from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import String, cast, or_, text
from sqlalchemy.orm import Session

from components.embedding import JinaAPIEmbeddings

from ..models import FinancialCard, FinancialReceipt


def _embedding_client() -> JinaAPIEmbeddings:
    return JinaAPIEmbeddings()


def search_financial_receipts_text(
    db: Session,
    query_text: str,
    company_id: int,
    receipt_ids: Optional[List[int]] = None,
    limit: int = 50,
) -> List[FinancialReceipt]:
    pattern = f"%{query_text}%"

    query = (
        db.query(FinancialReceipt)
        .join(FinancialCard, FinancialCard.id == FinancialReceipt.credit_card_id)
        .filter(
            FinancialReceipt.company_id == company_id,
            FinancialCard.company_id == company_id,
        )
    )

    if receipt_ids is not None:
        if not receipt_ids:
            return []
        query = query.filter(FinancialReceipt.id.in_(receipt_ids))

    query = query.filter(
        or_(
            FinancialReceipt.description.ilike(pattern),
            FinancialReceipt.tracking_number.ilike(pattern),
            FinancialReceipt.counterparty_name.ilike(pattern),
            FinancialCard.title.ilike(pattern),
            FinancialCard.card_number.ilike(pattern),
            FinancialCard.bank_name.ilike(pattern),
            cast(FinancialReceipt.amount, String).ilike(pattern),
        )
    )

    return (
        query
        .order_by(FinancialReceipt.receipt_date.desc(), FinancialReceipt.created_at.desc())
        .limit(limit)
        .all()
    )


def search_financial_receipt_hits_semantic(
    db: Session,
    query_text: str,
    company_id: int,
    receipt_ids: Optional[List[int]] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    query_embedding = _embedding_client().embed_query(query_text)

    if not query_embedding:
        return []

    embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"

    filters = [
        "r.company_id = :company_id",
        "c.company_id = :company_id",
        "r.description_embedding IS NOT NULL",
    ]

    params: Dict[str, Any] = {
        "query_vec": embedding_str,
        "company_id": company_id,
        "limit": limit,
    }

    if receipt_ids is not None:
        if not receipt_ids:
            return []

        placeholders = ", ".join(f":receipt_id_{i}" for i in range(len(receipt_ids)))
        filters.append(f"r.id IN ({placeholders})")

        for i, receipt_id in enumerate(receipt_ids):
            params[f"receipt_id_{i}"] = receipt_id

    where_clause = " AND ".join(filters)

    sql = text(
        f"""
        SELECT
            r.id AS receipt_id,
            r.company_id AS company_id,
            r.description AS description,
            r.tracking_number AS tracking_number,
            r.amount AS amount,
            r.direction AS direction,
            r.counterparty_name AS counterparty_name,
            r.receipt_date AS receipt_date,
            r.created_at AS "createdAt",
            r.owner_id AS owner_id,
            r.credit_card_id AS credit_card_id,
            c.title AS card_title,
            c.card_number AS card_number,
            (1 - (r.description_embedding <=> (:query_vec)::vector)) AS similarity
        FROM financial_receipts r
        JOIN financial_cards c ON c.id = r.credit_card_id
        WHERE {where_clause}
        ORDER BY similarity DESC, r.receipt_date DESC, r.created_at DESC
        LIMIT :limit
        """
    )

    rows = db.execute(sql, params).fetchall()

    return [
        {
            "receipt_id": row.receipt_id,
            "company_id": row.company_id,
            "description": row.description,
            "tracking_number": row.tracking_number,
            "amount": row.amount,
            "direction": row.direction,
            "counterparty_name": row.counterparty_name,
            "receipt_date": row.receipt_date,
            "createdAt": row.createdAt,
            "owner_id": row.owner_id,
            "credit_card_id": row.credit_card_id,
            "card_title": row.card_title,
            "card_number": row.card_number,
        }
        for row in rows
    ]

