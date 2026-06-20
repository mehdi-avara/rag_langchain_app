from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from components.embedding import JinaAPIEmbeddings

from ..models import Supplier, SupplierContact


def search_suppliers_text(
    db: Session,
    query_text: str,
    company_id: int,
    supplier_ids: Optional[list[int]] = None,
    supplier_status: Optional[str] = None,
    supplier_type: Optional[str] = None,
    limit: int = 50,
) -> list[Supplier]:
    pattern = f"%{query_text}%"

    query = (
        db.query(Supplier)
        .outerjoin(SupplierContact, SupplierContact.supplier_id == Supplier.id)
        .filter(Supplier.company_id == company_id)
    )

    if supplier_ids is not None:
        if not supplier_ids:
            return []
        query = query.filter(Supplier.id.in_(supplier_ids))

    if supplier_status:
        query = query.filter(Supplier.status == supplier_status)

    if supplier_type:
        query = query.filter(Supplier.supplier_type == supplier_type)

    query = query.filter(
        or_(
            Supplier.code.ilike(pattern),
            Supplier.name.ilike(pattern),
            Supplier.country.ilike(pattern),
            Supplier.city.ilike(pattern),
            Supplier.tax_id.ilike(pattern),
            Supplier.notes.ilike(pattern),
            SupplierContact.full_name.ilike(pattern),
            SupplierContact.job_title.ilike(pattern),
            SupplierContact.email.ilike(pattern),
            SupplierContact.phone.ilike(pattern),
        )
    )

    return (
        query.distinct()
        .order_by(Supplier.name.asc(), Supplier.id.asc())
        .limit(limit)
        .all()
    )


def search_supplier_hits_semantic(
    db: Session,
    query_text: str,
    company_id: int,
    supplier_ids: Optional[list[int]] = None,
    supplier_status: Optional[str] = None,
    supplier_type: Optional[str] = None,
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

    if supplier_ids is not None:
        if not supplier_ids:
            return []

        placeholders = ", ".join(f":supplier_id_{index}" for index in range(len(supplier_ids)))
        filters.append(f"id IN ({placeholders})")

        for index, supplier_id in enumerate(supplier_ids):
            params[f"supplier_id_{index}"] = supplier_id

    if supplier_status:
        filters.append("status = :supplier_status")
        params["supplier_status"] = supplier_status

    if supplier_type:
        filters.append("supplier_type = :supplier_type")
        params["supplier_type"] = supplier_type

    rows = db.execute(
        text(
            f"""
            SELECT
                id AS supplier_id,
                company_id,
                code,
                name,
                supplier_type,
                status,
                country,
                city,
                notes,
                (1 - (description_embedding <=> (:query_vec)::vector)) AS similarity
            FROM suppliers
            WHERE {" AND ".join(filters)}
            ORDER BY similarity DESC, name ASC, id ASC
            LIMIT :limit
            """
        ),
        params,
    ).fetchall()

    return [
        {
            "supplier_id": row.supplier_id,
            "company_id": row.company_id,
            "code": row.code,
            "name": row.name,
            "supplier_type": row.supplier_type,
            "status": row.status,
            "country": row.country,
            "city": row.city,
            "notes": row.notes,
            "similarity": float(row.similarity) if row.similarity is not None else None,
        }
        for row in rows
    ]
