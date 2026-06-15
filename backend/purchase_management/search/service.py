"""Search orchestration for purchase_management.

Mode routing: keyword | semantic | hybrid — same pattern as financial_management/search/service.py.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from sqlalchemy.orm import Session

from Models import User

from ..models import PurchaseOrder
from ..services import ensure_po_embeddings, _tenant_id
from .repository import search_purchase_orders_keyword, search_purchase_orders_semantic


class PurchaseOrderSearchHit(BaseModel):
    id: int
    company_id: int
    reference_number: str
    title: Optional[str]
    supplier_name: Optional[str]
    status: str
    approval_status: str
    currency_id: int
    base_currency_id: int
    created_by_user_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    match_source: str  # "text" | "semantic" | "text_fallback"

    class Config:
        from_attributes = True


def _build_hit_from_orm(po: PurchaseOrder, match_source: str = "text") -> PurchaseOrderSearchHit:
    return PurchaseOrderSearchHit(
        id=po.id,
        company_id=po.company_id,
        reference_number=po.reference_number,
        title=po.title,
        supplier_name=po.supplier_name,
        status=po.status,
        approval_status=po.approval_status,
        currency_id=po.currency_id,
        base_currency_id=po.base_currency_id,
        created_by_user_id=po.created_by_user_id,
        created_at=po.created_at,
        updated_at=po.updated_at,
        match_source=match_source,
    )


def _build_hit_from_row(row: Dict[str, Any], match_source: str = "semantic") -> PurchaseOrderSearchHit:
    return PurchaseOrderSearchHit(
        id=row["id"],
        company_id=row["company_id"],
        reference_number=row["reference_number"],
        title=row.get("title"),
        supplier_name=row.get("supplier_name"),
        status=row["status"],
        approval_status=row["approval_status"],
        currency_id=row["currency_id"],
        base_currency_id=row["base_currency_id"],
        created_by_user_id=row.get("created_by_user_id"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        match_source=match_source,
    )


def _merge_hits(
    primary: List[PurchaseOrderSearchHit],
    secondary: List[PurchaseOrderSearchHit],
    limit: int,
) -> List[PurchaseOrderSearchHit]:
    merged: List[PurchaseOrderSearchHit] = []
    seen: set[int] = set()
    for hit in list(primary) + list(secondary):
        if hit.id in seen:
            continue
        seen.add(hit.id)
        merged.append(hit)
        if len(merged) >= limit:
            break
    return merged


def search_purchase_order_hits(
    db: Session,
    current_user: User,
    query_text: str,
    mode: str = "hybrid",
    ids: Optional[List[int]] = None,
    limit: int = 20,
) -> List[PurchaseOrderSearchHit]:
    """Main search function. Mode: keyword | semantic | hybrid."""
    if mode == "semantic":
        mode = "vector"  # normalize alias

    company_id = _tenant_id(current_user)
    scoped_ids = list(dict.fromkeys(ids or []))

    semantic_hits: List[PurchaseOrderSearchHit] = []
    semantic_available = False

    if mode in {"vector", "hybrid"}:
        ensure_po_embeddings(db, current_user, po_ids=scoped_ids or None)
        try:
            rows = search_purchase_orders_semantic(
                db, query_text, company_id, ids=scoped_ids or None, limit=limit
            )
            semantic_hits = [_build_hit_from_row(row, "semantic") for row in rows]
            semantic_available = True
        except Exception:
            semantic_hits = []

    needs_text = (
        mode in {"keyword", "hybrid"}
        or (mode == "vector" and not semantic_available)
    )
    text_source = "text_fallback" if (mode == "vector" and not semantic_available) else "text"

    text_hits: List[PurchaseOrderSearchHit] = []
    if needs_text:
        pos = search_purchase_orders_keyword(
            db, query_text, company_id, ids=scoped_ids or None, limit=limit
        )
        text_hits = [_build_hit_from_orm(po, text_source) for po in pos]

    if mode == "keyword":
        return text_hits[:limit]
    if mode == "vector":
        return semantic_hits[:limit] if semantic_available else text_hits[:limit]
    return _merge_hits(semantic_hits, text_hits, limit)
