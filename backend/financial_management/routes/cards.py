from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from Models import User

from ..models import FinancialCard, FinancialReceipt
from ..schemas import FinancialCardCreate, FinancialCardOut, FinancialCardSearchRequest, FinancialCardUpdate
from ..search.service import search_card_hits
from ..services import card_to_out, get_card_or_404, normalize_card_number


router = APIRouter(prefix="/cards")


@router.post("", response_model=FinancialCardOut, status_code=status.HTTP_201_CREATED)
def create_card(
    payload: FinancialCardCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:cards:create")),
):
    card = FinancialCard(
        company_id=current_user.company_id,
        owner_id=current_user.id,
        title=payload.title,
        card_number=normalize_card_number(payload.card_number),
        bank_name=payload.bank_name,
        account_owner_name=payload.account_owner_name,
        description=payload.description,
        is_active=payload.is_active,
    )

    db.add(card)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Financial card already exists") from exc

    db.refresh(card)

    return card_to_out(card)


@router.get("", response_model=List[FinancialCardOut])
def list_cards(
    search: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(True),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:cards:read")),
):
    query = db.query(FinancialCard).filter(FinancialCard.company_id == current_user.company_id)

    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                FinancialCard.title.ilike(pattern),
                FinancialCard.card_number.ilike(pattern),
                FinancialCard.bank_name.ilike(pattern),
                FinancialCard.account_owner_name.ilike(pattern),
                FinancialCard.description.ilike(pattern),
            )
        )

    if is_active is not None:
        query = query.filter(FinancialCard.is_active == is_active)

    cards = (
        query
        .order_by(FinancialCard.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [card_to_out(card) for card in cards]



@router.post("/search", response_model=List[FinancialCardOut])
def search_cards(
    payload: FinancialCardSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:cards:read")),
):
    # Delegates to the module interface function (search/service.py) so search
    # logic lives in one place; offset/limit windowing is applied here, unchanged.
    rows = search_card_hits(
        db,
        current_user,
        payload.query,
        ids=payload.ids or None,
        is_active=payload.is_active,
        limit=payload.offset + payload.limit,
    )
    cards = rows[payload.offset:]
    return [card_to_out(card) for card in cards]


@router.get("/{card_id}", response_model=FinancialCardOut)
def get_card(
    card_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:cards:read")),
):
    return card_to_out(get_card_or_404(db, card_id, current_user))


@router.patch("/{card_id}", response_model=FinancialCardOut)
def update_card(
    card_id: int,
    payload: FinancialCardUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:cards:update")),
):
    card = get_card_or_404(db, card_id, current_user)
    data = payload.model_dump(exclude_unset=True)

    if "card_number" in data and data["card_number"] is not None:
        data["card_number"] = normalize_card_number(data["card_number"])

    for key, value in data.items():
        setattr(card, key, value)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Financial card already exists") from exc

    db.refresh(card)

    return card_to_out(card)


@router.delete("/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_card(
    card_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:cards:delete")),
):
    card = get_card_or_404(db, card_id, current_user)

    linked_receipt = (
        db.query(FinancialReceipt.id)
        .filter(
            FinancialReceipt.credit_card_id == card.id,
            FinancialReceipt.company_id == current_user.company_id,
        )
        .first()
    )

    if linked_receipt:
        card.is_active = False
        db.commit()
        return None

    db.delete(card)
    db.commit()

    return None