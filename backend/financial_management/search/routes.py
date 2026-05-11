from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from Models import User

from ..schemas import (
    FinancialReceiptOut,
    FinancialReceiptSemanticHit,
    FinancialReceiptSemanticSearchRequest,
    FinancialReceiptSearchRequest,
    FinancialReceiptTextSearchRequest,
)
from .service import list_text_receipts, search_receipt_hits, validate_receipt_scope


router = APIRouter(prefix="/receipts")


@router.post("/filter", response_model=List[FinancialReceiptOut], status_code=status.HTTP_200_OK)
def filter_receipts(
    payload: FinancialReceiptTextSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:search")),
):
    validated_ids = validate_receipt_scope(db, current_user, payload.ids)

    return list_text_receipts(
        db=db,
        current_user=current_user,
        query_text=payload.query,
        receipt_ids=validated_ids,
        limit=payload.limit,
    )


@router.post("/search", response_model=List[FinancialReceiptSemanticHit], status_code=status.HTTP_200_OK)
def search_receipts(
    payload: FinancialReceiptSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:search")),
):
    validated_ids = validate_receipt_scope(db, current_user, payload.ids)

    return search_receipt_hits(
        db=db,
        current_user=current_user,
        query_text=payload.query,
        mode=payload.mode,
        receipt_ids=validated_ids,
        limit=payload.limit,
    )


@router.post("/semantic-search", response_model=List[FinancialReceiptSemanticHit], status_code=status.HTTP_200_OK)
def semantic_search_receipts(
    payload: FinancialReceiptSemanticSearchRequest,
    top_k: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:search")),
):
    delegated_payload = FinancialReceiptSearchRequest(
        query=payload.query,
        ids=payload.ids,
        mode="vector",
        limit=top_k,
    )

    return search_receipts(payload=delegated_payload, db=db, current_user=current_user)

