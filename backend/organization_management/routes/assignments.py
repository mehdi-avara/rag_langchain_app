from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from Models import User
from db.init_db import get_db
from deps import require_permission

from ..schemas import (
    OrganizationUserAssignmentCreate,
    OrganizationUserAssignmentRead,
    OrganizationUserAssignmentUpdate,
)
from ..services import (
    create_assignment,
    deactivate_assignment,
    get_assignment_or_404,
    list_assignments,
    update_assignment,
)

router = APIRouter()


@router.post(
    "/assignments",
    response_model=OrganizationUserAssignmentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_organization_assignment(
    payload: OrganizationUserAssignmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("organization:assignments:manage")
    ),
):
    return create_assignment(
        db,
        current_user,
        payload.model_dump(),
    )


@router.get(
    "/assignments",
    response_model=list[OrganizationUserAssignmentRead],
)
def list_organization_assignments(
    user_id: Optional[int] = Query(None, gt=0),
    department_id: Optional[int] = Query(None, gt=0),
    position_id: Optional[int] = Query(None, gt=0),
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("organization:assignments:read")
    ),
):
    return list_assignments(
        db,
        current_user,
        user_id=user_id,
        department_id=department_id,
        position_id=position_id,
        is_active=is_active,
    )


@router.get(
    "/assignments/{assignment_id}",
    response_model=OrganizationUserAssignmentRead,
)
def get_organization_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("organization:assignments:read")
    ),
):
    return get_assignment_or_404(
        db,
        current_user,
        assignment_id,
    )


@router.patch(
    "/assignments/{assignment_id}",
    response_model=OrganizationUserAssignmentRead,
)
def patch_organization_assignment(
    assignment_id: int,
    payload: OrganizationUserAssignmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("organization:assignments:manage")
    ),
):
    return update_assignment(
        db,
        current_user,
        assignment_id,
        payload.model_dump(exclude_unset=True),
    )


@router.delete(
    "/assignments/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_organization_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("organization:assignments:manage")
    ),
):
    deactivate_assignment(
        db,
        current_user,
        assignment_id,
    )


@router.get(
    "/users/{user_id}/assignments",
    response_model=list[OrganizationUserAssignmentRead],
)
def list_user_organization_assignments(
    user_id: int,
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("organization:assignments:read")
    ),
):
    return list_assignments(
        db,
        current_user,
        user_id=user_id,
        is_active=is_active,
    )


@router.get(
    "/me/assignments",
    response_model=list[OrganizationUserAssignmentRead],
)
def list_my_organization_assignments(
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("organization:assignments:read")
    ),
):
    return list_assignments(
        db,
        current_user,
        user_id=current_user.id,
        is_active=is_active,
    )
