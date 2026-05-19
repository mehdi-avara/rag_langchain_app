from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from Models import User
from db.init_db import get_db
from deps import require_permission

from ..models import BuyingProcess
from ..schemas import BuyingProcessCreate, BuyingProcessListOut, BuyingProcessOut, BuyingProcessUpdate
from ..services import calculate_buying_summary, ensure_process_editable, get_buying_process_or_404, require_company


router = APIRouter(prefix="/processes")


@router.post("", response_model=BuyingProcessOut, status_code=status.HTTP_201_CREATED)
def create_buying_process(
    payload: BuyingProcessCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("buying_management:create")),
):
    process = BuyingProcess(
        company_id=require_company(current_user),
        owner_id=current_user.id,
        title=payload.title,
        supplier_name=payload.supplier_name,
        status=payload.status.value,
        currency=payload.currency,
        base_currency=payload.base_currency,
        exchange_rate_to_base=payload.exchange_rate_to_base,
        purchase_date=payload.purchase_date,
        description=payload.description,
        affects_warehouse=payload.affects_warehouse,
    )
    db.add(process)
    db.commit()
    db.refresh(process)
    return process


@router.get("", response_model=List[BuyingProcessListOut])
def list_buying_processes(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("buying_management:read")),
):
    query = db.query(BuyingProcess).filter(BuyingProcess.company_id == require_company(current_user))
    if status_filter:
        query = query.filter(BuyingProcess.status == status_filter)

    processes = query.order_by(BuyingProcess.purchase_date.desc(), BuyingProcess.created_at.desc()).offset(offset).limit(limit).all()
    output = []
    for process in processes:
        summary = calculate_buying_summary(db, process)
        output.append(
            BuyingProcessListOut(
                id=process.id,
                company_id=process.company_id,
                owner_id=process.owner_id,
                title=process.title,
                supplier_name=process.supplier_name,
                status=process.status,
                currency=process.currency,
                base_currency=process.base_currency,
                exchange_rate_to_base=process.exchange_rate_to_base,
                purchase_date=process.purchase_date,
                description=process.description,
                affects_warehouse=process.affects_warehouse,
                warehouse_applied_at=process.warehouse_applied_at,
                created_at=process.created_at,
                updated_at=process.updated_at,
                item_count=len(summary.items),
                total_quantity=summary.total_quantity,
                grand_total_base=summary.grand_total_base,
            )
        )
    return output


@router.get("/{process_id}", response_model=BuyingProcessOut)
def get_buying_process(
    process_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("buying_management:read")),
):
    return get_buying_process_or_404(db, process_id, current_user)


@router.put("/{process_id}", response_model=BuyingProcessOut)
def update_buying_process(
    process_id: int,
    payload: BuyingProcessUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("buying_management:update")),
):
    process = get_buying_process_or_404(db, process_id, current_user)
    data = payload.model_dump(exclude_unset=True)
    financial_fields = {"currency", "base_currency", "exchange_rate_to_base", "purchase_date", "affects_warehouse"}
    if process.warehouse_applied_at is not None and financial_fields.intersection(data):
        ensure_process_editable(process)

    nullable_fields = {"supplier_name", "description"}
    for key, value in data.items():
        if value is None and key not in nullable_fields:
            continue
        if key == "status" and value is not None:
            value = value.value
        setattr(process, key, value)

    db.commit()
    db.refresh(process)
    return process


@router.delete("/{process_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_buying_process(
    process_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("buying_management:delete")),
):
    process = get_buying_process_or_404(db, process_id, current_user)
    if process.warehouse_applied_at is not None:
        raise HTTPException(status_code=409, detail="Cannot delete after warehouse was applied")

    db.delete(process)
    db.commit()
    return None
