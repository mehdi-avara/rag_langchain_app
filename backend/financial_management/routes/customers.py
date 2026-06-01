from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from Models import User

from ..models import FinancialCustomer, FinancialReceipt
from ..schemas import (
    FinancialCustomerCreate,
    FinancialCustomerOut,
    FinancialCustomerUpdate,
)
from ..services import customer_to_out, get_customer_or_404


router = APIRouter(prefix="/customers")


@router.post("", response_model=FinancialCustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: FinancialCustomerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:customers")),
):
    customer = FinancialCustomer(
        company_id=current_user.company_id,
        owner_id=current_user.id,
        name=payload.name,
        phone_number1=payload.phone_number1,
        phone_number2=payload.phone_number2,
        access_method=payload.access_method,
        email=payload.email,
        description=payload.description,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer_to_out(customer)


@router.get("", response_model=List[FinancialCustomerOut])
def list_customers(
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:customers")),
):
    query = db.query(FinancialCustomer).filter(FinancialCustomer.company_id == current_user.company_id)

    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                FinancialCustomer.name.ilike(pattern),
                FinancialCustomer.phone_number1.ilike(pattern),
                FinancialCustomer.phone_number2.ilike(pattern),
                FinancialCustomer.email.ilike(pattern),
                FinancialCustomer.description.ilike(pattern),
            )
        )

    customers = query.order_by(FinancialCustomer.created_at.desc()).offset(offset).limit(limit).all()
    return [customer_to_out(customer) for customer in customers]


@router.get("/{customer_id}", response_model=FinancialCustomerOut)
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:customers")),
):
    return customer_to_out(get_customer_or_404(db, customer_id, current_user))


@router.patch("/{customer_id}", response_model=FinancialCustomerOut)
def update_customer(
    customer_id: int,
    payload: FinancialCustomerUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:customers")),
):
    customer = get_customer_or_404(db, customer_id, current_user)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(customer, key, value)
    db.commit()
    db.refresh(customer)
    return customer_to_out(customer)


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:customers")),
):
    customer = get_customer_or_404(db, customer_id, current_user)

    linked_receipt = (
        db.query(FinancialReceipt.id)
        .filter(
            FinancialReceipt.customer_id == customer.id,
            FinancialReceipt.company_id == current_user.company_id,
        )
        .first()
    )
    if linked_receipt:
        raise HTTPException(status_code=409, detail="Cannot delete a customer that is linked to receipts")

    db.delete(customer)
    db.commit()
    return None
