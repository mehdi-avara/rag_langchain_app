from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from Models import User

from ..schemas import SupplierSearchHit, SupplierSearchRequest
from .service import search_supplier_hits, validate_supplier_scope

router = APIRouter(prefix="/suppliers")


@router.post("/search", response_model=list[SupplierSearchHit])
def search_suppliers(
    payload: SupplierSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("supplier_management:search")),
):
    supplier_ids = validate_supplier_scope(db, current_user, payload.ids)

    return search_supplier_hits(
        db=db,
        current_user=current_user,
        query_text=payload.query,
        mode=payload.mode,
        supplier_ids=supplier_ids,
        supplier_status=payload.status.value if payload.status else None,
        supplier_type=payload.supplier_type.value if payload.supplier_type else None,
        limit=payload.limit,
    )
