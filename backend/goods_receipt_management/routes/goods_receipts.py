from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from Models.user import User
from db.init_db import get_db
from deps import require_permission

from ..models import GoodsReceiptStatus
from ..schemas import (
    GoodsReceiptCreate,
    GoodsReceiptItemCreate,
    GoodsReceiptItemRead,
    GoodsReceiptItemUpdate,
    GoodsReceiptRead,
    GoodsReceiptUpdate,
)
from ..services import (
    add_goods_receipt_item,
    create_goods_receipt,
    delete_goods_receipt,
    delete_goods_receipt_item,
    get_goods_receipt_or_404,
    list_goods_receipts,
    post_goods_receipt,
    search_goods_receipts,
    update_goods_receipt,
    update_goods_receipt_item,
)

router = APIRouter(tags=["goods_receipt_management"])


@router.get("", response_model=List[GoodsReceiptRead])
def list_goods_receipt_notes(
    grn_status: Optional[GoodsReceiptStatus] = Query(None, alias="status"),
    purchase_order_id: Optional[int] = Query(None, gt=0),
    purchase_phase_id: Optional[int] = Query(None, gt=0),
    receipt_date_from: Optional[date] = Query(None),
    receipt_date_to: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("goods_receipt_management:read")
    ),
):
    return list_goods_receipts(
        db=db,
        current_user=current_user,
        goods_receipt_status=grn_status.value if grn_status else None,
        purchase_order_id=purchase_order_id,
        purchase_phase_id=purchase_phase_id,
        receipt_date_from=receipt_date_from,
        receipt_date_to=receipt_date_to,
        page=page,
        size=size,
    )


@router.get("/search", response_model=List[GoodsReceiptRead])
def search_goods_receipt_notes(
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("goods_receipt_management:search")
    ),
):
    return search_goods_receipts(
        db=db,
        current_user=current_user,
        query_text=q,
        page=page,
        size=size,
    )


@router.post(
    "",
    response_model=GoodsReceiptRead,
    status_code=status.HTTP_201_CREATED,
)
def create_goods_receipt_note(
    payload: GoodsReceiptCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("goods_receipt_management:create")
    ),
):
    return create_goods_receipt(
        db=db,
        current_user=current_user,
        data=payload.model_dump(),
    )


@router.get("/{goods_receipt_id}", response_model=GoodsReceiptRead)
def get_goods_receipt_note(
    goods_receipt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("goods_receipt_management:read")
    ),
):
    return get_goods_receipt_or_404(
        db=db,
        current_user=current_user,
        goods_receipt_id=goods_receipt_id,
    )


@router.patch("/{goods_receipt_id}", response_model=GoodsReceiptRead)
def patch_goods_receipt_note(
    goods_receipt_id: int,
    payload: GoodsReceiptUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("goods_receipt_management:update")
    ),
):
    return update_goods_receipt(
        db=db,
        current_user=current_user,
        goods_receipt_id=goods_receipt_id,
        data=payload.model_dump(exclude_unset=True),
    )


@router.delete(
    "/{goods_receipt_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_goods_receipt_note(
    goods_receipt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("goods_receipt_management:update")
    ),
):
    delete_goods_receipt(
        db=db,
        current_user=current_user,
        goods_receipt_id=goods_receipt_id,
    )


@router.post(
    "/{goods_receipt_id}/items",
    response_model=GoodsReceiptItemRead,
    status_code=status.HTTP_201_CREATED,
)
def create_goods_receipt_note_item(
    goods_receipt_id: int,
    payload: GoodsReceiptItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("goods_receipt_management:update")
    ),
):
    return add_goods_receipt_item(
        db=db,
        current_user=current_user,
        goods_receipt_id=goods_receipt_id,
        data=payload.model_dump(),
    )


@router.patch(
    "/{goods_receipt_id}/items/{goods_receipt_item_id}",
    response_model=GoodsReceiptItemRead,
)
def patch_goods_receipt_note_item(
    goods_receipt_id: int,
    goods_receipt_item_id: int,
    payload: GoodsReceiptItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("goods_receipt_management:update")
    ),
):
    return update_goods_receipt_item(
        db=db,
        current_user=current_user,
        goods_receipt_id=goods_receipt_id,
        goods_receipt_item_id=goods_receipt_item_id,
        data=payload.model_dump(exclude_unset=True),
    )


@router.delete(
    "/{goods_receipt_id}/items/{goods_receipt_item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_goods_receipt_note_item(
    goods_receipt_id: int,
    goods_receipt_item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("goods_receipt_management:update")
    ),
):
    delete_goods_receipt_item(
        db=db,
        current_user=current_user,
        goods_receipt_id=goods_receipt_id,
        goods_receipt_item_id=goods_receipt_item_id,
    )


@router.post(
    "/{goods_receipt_id}/post",
    response_model=GoodsReceiptRead,
)
def post_goods_receipt_note(
    goods_receipt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("goods_receipt_management:approve")
    ),
):
    return post_goods_receipt(
        db=db,
        current_user=current_user,
        goods_receipt_id=goods_receipt_id,
    )
