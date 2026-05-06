from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from Models import User

from ..schemas import FinancialReceiptAskRequest, FinancialReceiptAskResponse, FinancialReceiptSearchRequest
from ..services import (
    generate_receipt_answer,
    get_receipt_or_404,
    parse_receipt_citations,
)
from ..search.routes import search_receipts


router = APIRouter(prefix="/receipts")


@router.post("/ask", response_model=FinancialReceiptAskResponse, status_code=status.HTTP_200_OK)
async def ask_receipts(
    payload: FinancialReceiptAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:ask")),
):
    for receipt_id in payload.receipt_ids:
        get_receipt_or_404(db, receipt_id, current_user)

    references = search_receipts(
        payload=FinancialReceiptSearchRequest(
            query=payload.question,
            ids=payload.receipt_ids,
            mode=payload.mode,
            limit=10,
        ),
        db=db,
        current_user=current_user,
    )
    answer = await generate_receipt_answer(payload.question, references)
    citations = parse_receipt_citations(answer)
    return FinancialReceiptAskResponse(
        answer=answer,
        citations=citations,
        used_receipt_ids=citations,
        references=references,
    )


@router.post("/{receipt_id}/ask", response_model=FinancialReceiptAskResponse, status_code=status.HTTP_200_OK)
async def ask_single_receipt(
    receipt_id: int,
    payload: FinancialReceiptAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:ask")),
):
    get_receipt_or_404(db, receipt_id, current_user)
    scoped_payload = FinancialReceiptAskRequest(
        question=payload.question,
        mode=payload.mode,
        receipt_ids=[receipt_id],
    )
    return await ask_receipts(scoped_payload, db=db, current_user=current_user)
