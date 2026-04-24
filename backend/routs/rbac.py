from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from Models.user import User
from Models.rbac import Role, Permission
from db.init_db import get_db
from deps import require_permission
from schemas.users import PermissionCreate, PermissionOut, RoleCreate, RoleUpdate, RoleOut


router = APIRouter()


@router.get("/permissions", response_model=list[PermissionOut])
def list_permissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("permissions:read")),
):
    return db.query(Permission).order_by(Permission.id.asc()).all()


@router.post("/permissions", response_model=PermissionOut, status_code=status.HTTP_201_CREATED)
def create_permission(
    data: PermissionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("permissions:create")),
):
    existing = db.query(Permission).filter(Permission.name == data.name).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Permission already exists",
        )

    permission = Permission(
        name=data.name,
        resource=data.resource,
        action=data.action,
        description=data.description,
    )

    db.add(permission)
    db.commit()
    db.refresh(permission)

    return permission


@router.put("/permissions/{permission_id}", response_model=PermissionOut)
def update_permission(
    permission_id: int,
    data: PermissionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("permissions:update")),
):
    permission = db.query(Permission).filter(Permission.id == permission_id).first()

    if not permission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permission not found",
        )

    existing = (
        db.query(Permission)
        .filter(Permission.name == data.name, Permission.id != permission_id)
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Permission already exists",
        )

    permission.name = data.name
    permission.resource = data.resource
    permission.action = data.action
    permission.description = data.description

    db.commit()
    db.refresh(permission)

    return permission


@router.delete("/permissions/{permission_id}")
def delete_permission(
    permission_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("permissions:delete")),
):
    permission = db.query(Permission).filter(Permission.id == permission_id).first()

    if not permission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permission not found",
        )

    db.delete(permission)
    db.commit()

    return {"message": "Permission deleted"}


@router.get("/roles", response_model=list[RoleOut])
def list_roles(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("roles:read")),
):
    return db.query(Role).order_by(Role.id.asc()).all()


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
def create_role(
    data: RoleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("roles:create")),
):
    existing = db.query(Role).filter(Role.name == data.name).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role already exists",
        )

    role = Role(
        name=data.name,
        description=data.description,
        is_active=data.is_active,
    )

    if data.permission_ids:
        permissions = db.query(Permission).filter(Permission.id.in_(data.permission_ids)).all()
        role.permissions = permissions

    db.add(role)
    db.commit()
    db.refresh(role)

    return role


@router.put("/roles/{role_id}", response_model=RoleOut)
def update_role(
    role_id: int,
    data: RoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("roles:update")),
):
    role = db.query(Role).filter(Role.id == role_id).first()

    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )

    if data.name is not None:
        existing = db.query(Role).filter(Role.name == data.name, Role.id != role_id).first()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Role already exists",
            )

        role.name = data.name

    if data.description is not None:
        role.description = data.description

    if data.is_active is not None:
        role.is_active = data.is_active

    if data.permission_ids is not None:
        permissions = db.query(Permission).filter(Permission.id.in_(data.permission_ids)).all()
        role.permissions = permissions

    db.commit()
    db.refresh(role)

    return role


@router.delete("/roles/{role_id}")
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("roles:delete")),
):
    role = db.query(Role).filter(Role.id == role_id).first()

    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )

    db.delete(role)
    db.commit()

    return {"message": "Role deleted"}