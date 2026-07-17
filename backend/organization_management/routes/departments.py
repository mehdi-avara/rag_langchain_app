from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from Models import User
from db.init_db import get_db
from deps import require_permission

from ..schemas import (
    OrganizationDepartmentCreate,
    OrganizationDepartmentRead,
    OrganizationDepartmentUpdate,
)
from ..services import (
    create_department,
    deactivate_department,
    get_department_or_404,
    list_departments,
    update_department,
)

router = APIRouter(prefix="/departments")


@router.post(
    "",
    response_model=OrganizationDepartmentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_organization_department(
    payload: OrganizationDepartmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("organization:departments:manage")
    ),
):
    return create_department(
        db,
        current_user,
        payload.model_dump(),
    )


@router.get(
    "",
    response_model=list[OrganizationDepartmentRead],
)
def list_organization_departments(
    is_active: Optional[bool] = Query(None),
    parent_department_id: Optional[int] = Query(None, gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("organization:departments:read")
    ),
):
    return list_departments(
        db,
        current_user,
        is_active=is_active,
        parent_department_id=parent_department_id,
    )


@router.get(
    "/{department_id}",
    response_model=OrganizationDepartmentRead,
)
def get_organization_department(
    department_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("organization:departments:read")
    ),
):
    return get_department_or_404(
        db,
        current_user,
        department_id,
    )


@router.patch(
    "/{department_id}",
    response_model=OrganizationDepartmentRead,
)
def patch_organization_department(
    department_id: int,
    payload: OrganizationDepartmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("organization:departments:manage")
    ),
):
    return update_department(
        db,
        current_user,
        department_id,
        payload.model_dump(exclude_unset=True),
    )


@router.delete(
    "/{department_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_organization_department(
    department_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("organization:departments:manage")
    ),
):
    deactivate_department(
        db,
        current_user,
        department_id,
    )
