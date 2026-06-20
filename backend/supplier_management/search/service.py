from __future__ import annotations

from typing import Iterable, Optional, Sequence

from sqlalchemy.orm import Session

from Models import User

from ..models import Supplier
from ..schemas import SupplierSearchHit
from ..services import (
    ensure_supplier_embeddings,
    get_supplier_or_404,
    tenant_id,
)
from .repository import (
    search_supplier_hits_semantic,
    search_suppliers_text,
)


def _supplier_to_text_hit(
    supplier: Supplier,
    match_source: str = "text",
) -> SupplierSearchHit:
    return SupplierSearchHit(
        supplier_id=supplier.id,
        company_id=supplier.company_id,
        code=supplier.code,
        name=supplier.name,
        supplier_type=supplier.supplier_type,
        status=supplier.status,
        country=supplier.country,
        city=supplier.city,
        notes=supplier.notes,
        match_source=match_source,
        similarity=None,
    )


def _supplier_to_semantic_hit(
    row: dict,
    match_source: str = "semantic",
) -> SupplierSearchHit:
    return SupplierSearchHit(
        supplier_id=row["supplier_id"],
        company_id=row["company_id"],
        code=row["code"],
        name=row["name"],
        supplier_type=row["supplier_type"],
        status=row["status"],
        country=row.get("country"),
        city=row.get("city"),
        notes=row.get("notes"),
        match_source=match_source,
        similarity=row.get("similarity"),
    )


def _merge_hits(
    primary_hits: Iterable[SupplierSearchHit],
    secondary_hits: Iterable[SupplierSearchHit],
    limit: int,
) -> list[SupplierSearchHit]:
    result: list[SupplierSearchHit] = []
    seen: set[int] = set()

    for hit in list(primary_hits) + list(secondary_hits):
        if hit.supplier_id in seen:
            continue

        seen.add(hit.supplier_id)
        result.append(hit)

        if len(result) >= limit:
            break

    return result


def validate_supplier_scope(
    db: Session,
    current_user: User,
    supplier_ids: Sequence[int],
) -> list[int]:
    validated: list[int] = []

    for supplier_id in list(dict.fromkeys(supplier_ids)):
        get_supplier_or_404(db, supplier_id, current_user)
        validated.append(supplier_id)

    return validated


def search_supplier_hits(
    db: Session,
    current_user: User,
    query_text: str,
    mode: str,
    supplier_ids: Optional[Sequence[int]] = None,
    supplier_status: Optional[str] = None,
    supplier_type: Optional[str] = None,
    limit: int = 20,
) -> list[SupplierSearchHit]:
    if mode == "semantic":
        mode = "vector"

    scoped_ids = list(dict.fromkeys(supplier_ids or []))
    company_id = tenant_id(current_user)

    semantic_hits: list[SupplierSearchHit] = []
    semantic_available = False

    if mode in {"vector", "hybrid"}:
        ensure_supplier_embeddings(
            db=db,
            current_user=current_user,
            supplier_ids=scoped_ids or None,
        )

        try:
            semantic_rows = search_supplier_hits_semantic(
                db=db,
                query_text=query_text,
                company_id=company_id,
                supplier_ids=scoped_ids or None,
                supplier_status=supplier_status,
                supplier_type=supplier_type,
                limit=limit,
            )
            semantic_hits = [
                _supplier_to_semantic_hit(row)
                for row in semantic_rows
            ]
            semantic_available = True
        except Exception:
            semantic_hits = []

    needs_text = (
        mode in {"keyword", "hybrid"}
        or (mode == "vector" and not semantic_available)
    )
    text_source = "text_fallback" if mode == "vector" and not semantic_available else "text"

    text_hits: list[SupplierSearchHit] = []

    if needs_text:
        text_rows = search_suppliers_text(
            db=db,
            query_text=query_text,
            company_id=company_id,
            supplier_ids=scoped_ids or None,
            supplier_status=supplier_status,
            supplier_type=supplier_type,
            limit=limit,
        )
        text_hits = [
            _supplier_to_text_hit(item, match_source=text_source)
            for item in text_rows
        ]

    if mode == "keyword":
        return text_hits[:limit]

    if mode == "vector":
        return semantic_hits[:limit] if semantic_available else text_hits[:limit]

    return _merge_hits(semantic_hits, text_hits, limit)
