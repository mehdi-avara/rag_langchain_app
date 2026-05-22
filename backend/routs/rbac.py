from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from passlib.hash import bcrypt
from sqlalchemy import or_
from sqlalchemy.orm import Session

from Models.user import User
from Models.rbac import Role, Permission
from db.init_db import get_db
from deps import require_permission
from schemas.users import (
    AdminUserCreate,
    AdminUserOut,
    AdminUserPasswordReset,
    AdminUserRolesUpdate,
    AdminUserUpdate,
    PermissionCreate,
    PermissionOut,
    RoleCreate,
    RoleUpdate,
    RoleOut,
)


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


def _role_scope_query(db: Session, company_id: int):
    return db.query(Role).filter(
        or_(
            Role.is_system.is_(True),
            Role.company_id == company_id,
        )
    )


def _get_visible_role_or_404(db: Session, role_id: int, company_id: int) -> Role:
    role = _role_scope_query(db, company_id).filter(Role.id == role_id).first()

    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )

    return role


def _active_users_with_role(role: Role) -> list[User]:
    return [
        user
        for user in getattr(role, "users", []) or []
        if getattr(user, "is_active", True) is not False
    ]


def _ensure_role_has_no_active_users(role: Role) -> None:
    active_users = _active_users_with_role(role)

    if active_users:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot modify a role assigned to active users",
        )


@router.get("/roles", response_model=list[RoleOut])
def list_roles(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("roles:read")),
):
    company_id = _require_company_id(current_user)
    return _role_scope_query(db, company_id).order_by(Role.is_system.desc(), Role.id.asc()).all()


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
def create_role(
    data: RoleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("roles:create")),
):
    company_id = _require_company_id(current_user)
    name = data.name.strip()

    existing = _role_scope_query(db, company_id).filter(Role.name == name).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role already exists",
        )

    role = Role(
        company_id=company_id,
        name=name,
        description=data.description,
        is_active=data.is_active,
        is_system=False,
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
    company_id = _require_company_id(current_user)
    role = _get_visible_role_or_404(db, role_id, company_id)

    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System roles cannot be updated",
        )

    if data.name is not None:
        existing = _role_scope_query(db, company_id).filter(Role.name == data.name, Role.id != role_id).first()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Role already exists",
            )

        role.name = data.name

    if data.description is not None:
        role.description = data.description

    if data.is_active is not None:
        if data.is_active is False:
            _ensure_role_has_no_active_users(role)
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
    company_id = _require_company_id(current_user)
    role = _get_visible_role_or_404(db, role_id, company_id)

    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System roles cannot be deleted",
        )

    _ensure_role_has_no_active_users(role)

    db.delete(role)
    db.commit()

    return {"message": "Role deleted"}

def _require_company_id(current_user: User) -> int:
    if current_user.company_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has no company")
    return current_user.company_id


def _user_permission_names(user: User) -> list[str]:
    return sorted(
        {
            permission.name
            for role in user.roles
            if role.is_active
            for permission in role.permissions
        }
    )


def _admin_user_out(user: User) -> AdminUserOut:
    return AdminUserOut(
        id=user.id,
        company_id=user.company_id,
        username=user.username,
        First_name=user.First_name,
        Last_name=user.Last_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        deactivated_at=user.deactivated_at,
        password_changed_at=user.password_changed_at,
        notification_token=user.notification_token,
        image_path=user.image_path,
        profile_asset_id=user.profile_asset_id,
        roles=user.roles,
        permissions=_user_permission_names(user),
    )


def _get_company_user_or_404(db: Session, user_id: int, company_id: int) -> User:
    user = db.query(User).filter(
        User.id == user_id,
        User.company_id == company_id,
    ).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return user


def _load_roles_or_400(db: Session, role_ids: list[int], company_id: int) -> list[Role]:
    if not role_ids:
        role = db.query(Role).filter(
            Role.name == "user",
            Role.is_system.is_(True),
            Role.is_active.is_(True),
        ).first()
        return [role] if role else []

    unique_role_ids = sorted(set(role_ids))
    roles = _role_scope_query(db, company_id).filter(
        Role.id.in_(unique_role_ids),
        Role.is_active.is_(True),
    ).all()

    if len(roles) != len(unique_role_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role_ids")

    return roles


def _legacy_role_from_roles(roles: list[Role]) -> str:
    return "admin" if any(role.name == "admin" and role.is_active for role in roles) else "user"


def _is_active_admin(user: User) -> bool:
    if user.is_active is False:
        return False

    return user.role == "admin" or any(
        role.name == "admin" and role.is_active for role in user.roles
    )


def _active_admin_count(db: Session, company_id: int) -> int:
    users = db.query(User).filter(
        User.company_id == company_id,
        User.is_active.is_(True),
    ).all()

    return sum(1 for user in users if _is_active_admin(user))


def _ensure_not_last_active_admin(db: Session, user: User) -> None:
    if not _is_active_admin(user):
        return

    if _active_admin_count(db, user.company_id) <= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot modify the last active admin of the company",
        )


@router.get("/users", response_model=list[AdminUserOut])
def list_company_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users:read")),
):
    company_id = _require_company_id(current_user)
    users = (
        db.query(User)
        .filter(User.company_id == company_id)
        .order_by(User.id.asc())
        .all()
    )
    return [_admin_user_out(user) for user in users]


@router.post("/users", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED)
def create_company_user(
    payload: AdminUserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users:create")),
):
    company_id = _require_company_id(current_user)
    username = payload.username.strip().lower()

    existing = db.query(User).filter(User.username == username).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

    roles = _load_roles_or_400(db, payload.role_ids, company_id)

    user = User(
        company_id=company_id,
        username=username,
        First_name=payload.First_name.strip(),
        Last_name=payload.Last_name.strip() if payload.Last_name else None,
        pw_hash=bcrypt.hash(payload.password),
        role=_legacy_role_from_roles(roles),
        is_active=True,
    )
    user.roles = roles

    db.add(user)
    db.commit()
    db.refresh(user)

    return _admin_user_out(user)


@router.get("/users/{user_id}", response_model=AdminUserOut)
def get_company_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users:read")),
):
    company_id = _require_company_id(current_user)
    user = _get_company_user_or_404(db, user_id, company_id)
    return _admin_user_out(user)


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def update_company_user(
    user_id: int,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users:update")),
):
    company_id = _require_company_id(current_user)
    user = _get_company_user_or_404(db, user_id, company_id)

    if payload.username and payload.username.strip().lower() != user.username:
        username = payload.username.strip().lower()
        existing = db.query(User).filter(User.username == username, User.id != user.id).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
        user.username = username

    if payload.First_name is not None:
        user.First_name = payload.First_name.strip()

    if payload.Last_name is not None:
        user.Last_name = payload.Last_name.strip() if payload.Last_name else None

    if payload.notification_token is not None:
        user.notification_token = payload.notification_token

    if payload.role_ids is not None:
        if user.id == current_user.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot change your own roles")

        _ensure_not_last_active_admin(db, user)
        roles = _load_roles_or_400(db, payload.role_ids, company_id)
        user.roles = roles
        user.role = _legacy_role_from_roles(roles)

    db.commit()
    db.refresh(user)

    return _admin_user_out(user)


@router.put("/users/{user_id}/roles", response_model=AdminUserOut)
def update_company_user_roles(
    user_id: int,
    payload: AdminUserRolesUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users:update")),
):
    company_id = _require_company_id(current_user)
    user = _get_company_user_or_404(db, user_id, company_id)

    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot change your own roles")

    _ensure_not_last_active_admin(db, user)

    roles = _load_roles_or_400(db, payload.role_ids, company_id)
    user.roles = roles
    user.role = _legacy_role_from_roles(roles)

    db.commit()
    db.refresh(user)

    return _admin_user_out(user)


@router.post("/users/{user_id}/activate", response_model=AdminUserOut)
def activate_company_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users:update")),
):
    company_id = _require_company_id(current_user)
    user = _get_company_user_or_404(db, user_id, company_id)

    user.is_active = True
    user.deactivated_at = None

    db.commit()
    db.refresh(user)

    return _admin_user_out(user)


@router.post("/users/{user_id}/deactivate", response_model=AdminUserOut)
def deactivate_company_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users:update")),
):
    company_id = _require_company_id(current_user)
    user = _get_company_user_or_404(db, user_id, company_id)

    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot deactivate your own account")

    _ensure_not_last_active_admin(db, user)

    user.is_active = False
    user.deactivated_at = datetime.utcnow()

    db.commit()
    db.refresh(user)

    return _admin_user_out(user)


@router.post("/users/{user_id}/reset-password", response_model=AdminUserOut)
def reset_company_user_password(
    user_id: int,
    payload: AdminUserPasswordReset,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users:update")),
):
    company_id = _require_company_id(current_user)
    user = _get_company_user_or_404(db, user_id, company_id)

    user.pw_hash = bcrypt.hash(payload.new_password)
    user.password_changed_at = datetime.utcnow()

    db.commit()
    db.refresh(user)

    return _admin_user_out(user)
