from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from Models.user import User
from db.init_db import get_db
from deps import require_permission

from ..schemas import (
    QuotationResponseCreate,
    QuotationResponseItemCreate,
    QuotationResponseItemRead,
    QuotationResponseItemUpdate,
    QuotationResponseRead,
    QuotationResponseUpdate,
    RequestForQuotationCreate,
    RequestForQuotationRead,
    RequestForQuotationUpdate,
    RFQComparisonRead,
    RFQItemCreate,
    RFQItemRead,
    RFQItemUpdate,
    RFQSupplierCreate,
    RFQSupplierRead,
    WinningQuotationSelect,
)
from ..services import (
    add_quotation_response_item,
    add_rfq_item,
    add_rfq_supplier,
    create_quotation_response as create_quotation_response_service,
    create_rfq,
    delete_quotation_response as delete_quotation_response_service,
    delete_quotation_response_item as delete_quotation_response_item_service,
    delete_rfq,
    delete_rfq_item as delete_rfq_item_service,
    delete_rfq_supplier as delete_rfq_supplier_service,
    get_rfq_comparison,
    get_rfq_or_404,
    list_rfqs,
    search_rfqs,
    select_winning_quotation,
    transition_rfq,
    update_quotation_response,
    update_quotation_response_item,
    update_rfq,
    update_rfq_item,
)

router = APIRouter(tags=["rfq_management"])


@router.get("", response_model=List[RequestForQuotationRead])
def list_request_for_quotations(
    rfq_status: Optional[str] = Query(None, alias="status"),
    mr_id: Optional[int] = Query(None, gt=0),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rfq_management:read")),
):
    return list_rfqs(
        db=db,
        current_user=current_user,
        rfq_status=rfq_status,
        mr_id=mr_id,
        page=page,
        size=size,
    )


@router.get("/search", response_model=List[RequestForQuotationRead])
def search_request_for_quotations(
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rfq_management:search")),
):
    return search_rfqs(
        db=db,
        current_user=current_user,
        query_text=q,
        page=page,
        size=size,
    )


@router.post(
    "",
    response_model=RequestForQuotationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_request_for_quotation(
    payload: RequestForQuotationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rfq_management:create")),
):
    return create_rfq(
        db=db,
        current_user=current_user,
        data=payload.model_dump(),
    )


@router.get("/{rfq_id}", response_model=RequestForQuotationRead)
def get_request_for_quotation(
    rfq_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rfq_management:read")),
):
    return get_rfq_or_404(
        db=db,
        current_user=current_user,
        rfq_id=rfq_id,
    )


@router.patch("/{rfq_id}", response_model=RequestForQuotationRead)
def patch_request_for_quotation(
    rfq_id: int,
    payload: RequestForQuotationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rfq_management:update")),
):
    return update_rfq(
        db=db,
        current_user=current_user,
        rfq_id=rfq_id,
        data=payload.model_dump(exclude_unset=True),
    )


@router.delete("/{rfq_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_request_for_quotation(
    rfq_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rfq_management:delete")),
):
    delete_rfq(
        db=db,
        current_user=current_user,
        rfq_id=rfq_id,
    )


@router.post("/{rfq_id}/send", response_model=RequestForQuotationRead)
def send_request_for_quotation(
    rfq_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rfq_management:update")),
):
    return transition_rfq(
        db=db,
        current_user=current_user,
        rfq_id=rfq_id,
        action="send",
    )


@router.post("/{rfq_id}/close", response_model=RequestForQuotationRead)
def close_request_for_quotation(
    rfq_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rfq_management:update")),
):
    return transition_rfq(
        db=db,
        current_user=current_user,
        rfq_id=rfq_id,
        action="close",
    )


@router.post("/{rfq_id}/cancel", response_model=RequestForQuotationRead)
def cancel_request_for_quotation(
    rfq_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rfq_management:update")),
):
    return transition_rfq(
        db=db,
        current_user=current_user,
        rfq_id=rfq_id,
        action="cancel",
    )


@router.post("/{rfq_id}/suppliers", response_model=RFQSupplierRead, status_code=201)
def create_rfq_supplier(
    rfq_id: int,
    payload: RFQSupplierCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rfq_management:update")),
):
    return add_rfq_supplier(
        db=db,
        current_user=current_user,
        rfq_id=rfq_id,
        supplier_id=payload.supplier_id,
    )


@router.delete("/{rfq_id}/suppliers/{supplier_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rfq_supplier(
    rfq_id: int,
    supplier_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rfq_management:update")),
):
    delete_rfq_supplier_service(
        db=db,
        current_user=current_user,
        rfq_id=rfq_id,
        supplier_id=supplier_id,
    )


@router.post("/{rfq_id}/items", response_model=RFQItemRead, status_code=201)
def create_rfq_item(
    rfq_id: int,
    payload: RFQItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rfq_management:update")),
):
    return add_rfq_item(
        db=db,
        current_user=current_user,
        rfq_id=rfq_id,
        data=payload.model_dump(),
    )


@router.patch("/{rfq_id}/items/{rfq_item_id}", response_model=RFQItemRead)
def patch_rfq_item(
    rfq_id: int,
    rfq_item_id: int,
    payload: RFQItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rfq_management:update")),
):
    return update_rfq_item(
        db=db,
        current_user=current_user,
        rfq_id=rfq_id,
        rfq_item_id=rfq_item_id,
        data=payload.model_dump(exclude_unset=True),
    )


@router.delete("/{rfq_id}/items/{rfq_item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rfq_item(
    rfq_id: int,
    rfq_item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rfq_management:update")),
):
    delete_rfq_item_service(
        db=db,
        current_user=current_user,
        rfq_id=rfq_id,
        rfq_item_id=rfq_item_id,
    )


@router.get("/{rfq_id}/responses", response_model=List[QuotationResponseRead])
def list_quotation_responses(
    rfq_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rfq_management:read")),
):
    rfq = get_rfq_or_404(
        db=db,
        current_user=current_user,
        rfq_id=rfq_id,
    )
    return rfq.responses


@router.post("/{rfq_id}/responses", response_model=QuotationResponseRead, status_code=201)
def create_quotation_response(
    rfq_id: int,
    payload: QuotationResponseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rfq_management:update")),
):
    return create_quotation_response_service(
        db=db,
        current_user=current_user,
        rfq_id=rfq_id,
        data=payload.model_dump(),
    )


@router.patch("/{rfq_id}/responses/{quotation_response_id}", response_model=QuotationResponseRead)
def patch_quotation_response(
    rfq_id: int,
    quotation_response_id: int,
    payload: QuotationResponseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rfq_management:update")),
):
    return update_quotation_response(
        db=db,
        current_user=current_user,
        rfq_id=rfq_id,
        quotation_response_id=quotation_response_id,
        data=payload.model_dump(exclude_unset=True),
    )


@router.delete(
    "/{rfq_id}/responses/{quotation_response_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_quotation_response(
    rfq_id: int,
    quotation_response_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rfq_management:update")),
):
    delete_quotation_response_service(
        db=db,
        current_user=current_user,
        rfq_id=rfq_id,
        quotation_response_id=quotation_response_id,
    )


@router.post(
    "/{rfq_id}/responses/{quotation_response_id}/items",
    response_model=QuotationResponseItemRead,
    status_code=201,
)
def create_quotation_response_item(
    rfq_id: int,
    quotation_response_id: int,
    payload: QuotationResponseItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rfq_management:update")),
):
    return add_quotation_response_item(
        db=db,
        current_user=current_user,
        rfq_id=rfq_id,
        quotation_response_id=quotation_response_id,
        data=payload.model_dump(),
    )


@router.patch(
    "/{rfq_id}/responses/{quotation_response_id}/items/{quotation_response_item_id}",
    response_model=QuotationResponseItemRead,
)
def patch_quotation_response_item(
    rfq_id: int,
    quotation_response_id: int,
    quotation_response_item_id: int,
    payload: QuotationResponseItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rfq_management:update")),
):
    return update_quotation_response_item(
        db=db,
        current_user=current_user,
        rfq_id=rfq_id,
        quotation_response_id=quotation_response_id,
        quotation_response_item_id=quotation_response_item_id,
        data=payload.model_dump(exclude_unset=True),
    )


@router.delete(
    "/{rfq_id}/responses/{quotation_response_id}/items/{quotation_response_item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_quotation_response_item(
    rfq_id: int,
    quotation_response_id: int,
    quotation_response_item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rfq_management:update")),
):
    delete_quotation_response_item_service(
        db=db,
        current_user=current_user,
        rfq_id=rfq_id,
        quotation_response_id=quotation_response_id,
        quotation_response_item_id=quotation_response_item_id,
    )


@router.get("/{rfq_id}/comparison", response_model=RFQComparisonRead)
def get_request_for_quotation_comparison(
    rfq_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rfq_management:read")),
):
    return get_rfq_comparison(
        db=db,
        current_user=current_user,
        rfq_id=rfq_id,
    )


@router.post("/{rfq_id}/select-winner", response_model=RequestForQuotationRead)
def select_rfq_winner(
    rfq_id: int,
    payload: WinningQuotationSelect,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rfq_management:approve")),
):
    return select_winning_quotation(
        db=db,
        current_user=current_user,
        rfq_id=rfq_id,
        quotation_response_id=payload.quotation_response_id,
    )
