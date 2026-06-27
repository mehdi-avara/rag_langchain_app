from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from Models import User

from ..schemas import FinancialReceiptAskRequest, FinancialReceiptAskResponse
from ..services import answer_receipts_question, get_receipt_or_404


router = APIRouter(prefix="/receipts")


@router.post("/ask", response_model=FinancialReceiptAskResponse, status_code=status.HTTP_200_OK)
async def ask_receipts(
    payload: FinancialReceiptAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:receipts:ask")),
):
    return await answer_receipts_question(
        db,
        current_user,
        question=payload.question,
        mode=payload.mode,
        receipt_ids=payload.receipt_ids,
    )


@router.post("/{receipt_id}/ask", response_model=FinancialReceiptAskResponse, status_code=status.HTTP_200_OK)
async def ask_single_receipt(
    receipt_id: int,
    payload: FinancialReceiptAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:receipts:ask")),
):
    get_receipt_or_404(db, receipt_id, current_user)

    scoped_payload = FinancialReceiptAskRequest(
        question=payload.question,
        mode=payload.mode,
        receipt_ids=[receipt_id],
    )

    return await ask_receipts(scoped_payload, db=db, current_user=current_user)


