from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from Models.user import User
from db.init_db import get_db
from deps import require_permission

from ..models import MaterialRequisitionPriority
from ..schemas import (
    MaterialRequisitionCreate,
    MaterialRequisitionItemCreate,
    MaterialRequisitionItemRead,
    MaterialRequisitionItemUpdate,
    MaterialRequisitionRead,
    MaterialRequisitionStatusHistoryRead,
    MaterialRequisitionUpdate,
    RequisitionApprovalAction,
)
from ..services import (
    add_requisition_item,
    create_requisition,
    delete_requisition,
    delete_requisition_item,
    get_requisition_or_404,
    list_approval_inbox,
    list_requisitions,
    list_status_history,
    search_requisitions,
    transition_requisition,
    update_requisition,
    update_requisition_item,
)

router = APIRouter(tags=["requisition_management"])


@router.get("", response_model=List[MaterialRequisitionRead])
def list_material_requisitions(
    mr_status: Optional[str] = Query(None, alias="status"),
    priority: Optional[MaterialRequisitionPriority] = Query(None),
    requested_by_user_id: Optional[int] = Query(None, gt=0),
    department_id: Optional[int] = Query(None, gt=0),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("requisition_management:read")
    ),
):
    return list_requisitions(
        db=db,
        current_user=current_user,
        requisition_status=mr_status,
        priority=priority,
        requested_by_user_id=requested_by_user_id,
        department_id=department_id,
        page=page,
        size=size,
    )


@router.get("/search", response_model=List[MaterialRequisitionRead])
def search_material_requisitions(
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("requisition_management:search")
    ),
):
    return search_requisitions(
        db=db,
        current_user=current_user,
        query_text=q,
        page=page,
        size=size,
    )


@router.get(
    "/approval-inbox",
    response_model=List[MaterialRequisitionRead],
)
def material_requisition_approval_inbox(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("requisition_management:approve")
    ),
):
    return list_approval_inbox(
        db=db,
        current_user=current_user,
        page=page,
        size=size,
    )


@router.post(
    "",
    response_model=MaterialRequisitionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_material_requisition(
    payload: MaterialRequisitionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("requisition_management:create")
    ),
):
    return create_requisition(
        db=db,
        current_user=current_user,
        data=payload.model_dump(),
    )


@router.get(
    "/{requisition_id}",
    response_model=MaterialRequisitionRead,
)
def get_material_requisition(
    requisition_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("requisition_management:read")
    ),
):
    return get_requisition_or_404(
        db=db,
        current_user=current_user,
        requisition_id=requisition_id,
    )


@router.patch(
    "/{requisition_id}",
    response_model=MaterialRequisitionRead,
)
def patch_material_requisition(
    requisition_id: int,
    payload: MaterialRequisitionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("requisition_management:update")
    ),
):
    return update_requisition(
        db=db,
        current_user=current_user,
        requisition_id=requisition_id,
        data=payload.model_dump(exclude_unset=True),
    )


@router.delete(
    "/{requisition_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_material_requisition(
    requisition_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("requisition_management:delete")
    ),
):
    delete_requisition(
        db=db,
        current_user=current_user,
        requisition_id=requisition_id,
    )


@router.post(
    "/{requisition_id}/submit",
    response_model=MaterialRequisitionRead,
)
def submit_material_requisition(
    requisition_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("requisition_management:update")
    ),
):
    return transition_requisition(
        db=db,
        current_user=current_user,
        requisition_id=requisition_id,
        action="submit",
    )


@router.post(
    "/{requisition_id}/approval",
    response_model=MaterialRequisitionRead,
)
def process_material_requisition_approval(
    requisition_id: int,
    payload: RequisitionApprovalAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("requisition_management:approve")
    ),
):
    return transition_requisition(
        db=db,
        current_user=current_user,
        requisition_id=requisition_id,
        action=payload.action,
        note=payload.note,
    )


@router.get(
    "/{requisition_id}/history",
    response_model=List[MaterialRequisitionStatusHistoryRead],
)
def get_material_requisition_history(
    requisition_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("requisition_management:read")
    ),
):
    return list_status_history(
        db=db,
        current_user=current_user,
        requisition_id=requisition_id,
    )


@router.post(
    "/{requisition_id}/items",
    response_model=MaterialRequisitionItemRead,
    status_code=status.HTTP_201_CREATED,
)
def create_material_requisition_item(
    requisition_id: int,
    payload: MaterialRequisitionItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("requisition_management:update")
    ),
):
    return add_requisition_item(
        db=db,
        current_user=current_user,
        requisition_id=requisition_id,
        data=payload.model_dump(),
    )


@router.patch(
    "/{requisition_id}/items/{requisition_item_id}",
    response_model=MaterialRequisitionItemRead,
)
def patch_material_requisition_item(
    requisition_id: int,
    requisition_item_id: int,
    payload: MaterialRequisitionItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("requisition_management:update")
    ),
):
    return update_requisition_item(
        db=db,
        current_user=current_user,
        requisition_id=requisition_id,
        requisition_item_id=requisition_item_id,
        data=payload.model_dump(exclude_unset=True),
    )


@router.delete(
    "/{requisition_id}/items/{requisition_item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_material_requisition_item(
    requisition_id: int,
    requisition_item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("requisition_management:update")
    ),
):
    delete_requisition_item(
        db=db,
        current_user=current_user,
        requisition_id=requisition_id,
        requisition_item_id=requisition_item_id,
    )
