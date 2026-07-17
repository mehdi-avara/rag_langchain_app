from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from Models import User
from db.init_db import get_db
from deps import require_permission

from ..schemas import (
    OrganizationPositionCreate,
    OrganizationPositionRead,
    OrganizationPositionUpdate,
)
from ..services import (
    create_position,
    deactivate_position,
    get_position_or_404,
    list_positions,
    update_position,
)

router = APIRouter(prefix="/positions")


@router.post(
    "",
    response_model=OrganizationPositionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_organization_position(
    payload: OrganizationPositionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("organization:positions:manage")
    ),
):
    return create_position(
        db,
        current_user,
        payload.model_dump(),
    )


@router.get(
    "",
    response_model=list[OrganizationPositionRead],
)
def list_organization_positions(
    department_id: Optional[int] = Query(None, gt=0),
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("organization:positions:read")
    ),
):
    return list_positions(
        db,
        current_user,
        department_id=department_id,
        is_active=is_active,
    )


@router.get(
    "/{position_id}",
    response_model=OrganizationPositionRead,
)
def get_organization_position(
    position_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("organization:positions:read")
    ),
):
    return get_position_or_404(
        db,
        current_user,
        position_id,
    )


@router.patch(
    "/{position_id}",
    response_model=OrganizationPositionRead,
)
def patch_organization_position(
    position_id: int,
    payload: OrganizationPositionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("organization:positions:manage")
    ),
):
    return update_position(
        db,
        current_user,
        position_id,
        payload.model_dump(exclude_unset=True),
    )


@router.delete(
    "/{position_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_organization_position(
    position_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("organization:positions:manage")
    ),
):
    deactivate_position(
        db,
        current_user,
        position_id,
    )
