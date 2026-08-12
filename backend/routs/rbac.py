from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from passlib.hash import bcrypt
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from Models.company import Company
from Models.user import User
from Models.rbac import Role, Permission
from core.authorization import (
    GLOBAL_ADMIN_ROLE_NAME,
    GLOBAL_USER_ROLE_NAME,
    TENANT_ADMIN_ROLE_NAME,
    is_company_admin,
    is_tenant_permission_name,
)
from core.auth_sessions import revoke_user_authentication
from db.init_db import get_db
from db.provision_company_defaults import provision_company_defaults
from deps import get_current_user, require_permission
from schemas.users import (
    AdminUserCreate,
    AdminUserListOut,
    AdminUserOut,
    AdminUserPasswordReset,
    AdminUserRolesUpdate,
    AdminUserUpdate,
    CurrentUserAccessOut,
    PermissionOut,
    RoleCreate,
    RoleUpdate,
    RoleOut,
)


from core.exceptions.error_codes import (
    COMPANY_REQUIRED,
    INVALID_PERMISSION_IDS,
    INVALID_ROLE_IDS,
    LAST_ADMIN_PROTECTED,
    ROLE_ALREADY_EXISTS,
    ROLE_IN_USE,
    ROLE_NOT_FOUND,
    SELF_ACTION_FORBIDDEN,
    SYSTEM_ROLE_PROTECTED,
    USER_NOT_FOUND,
    USERNAME_ALREADY_EXISTS,
)

router = APIRouter()

RESERVED_ROLE_NAMES = frozenset(
    {
        GLOBAL_ADMIN_ROLE_NAME.casefold(),
        GLOBAL_USER_ROLE_NAME.casefold(),
        TENANT_ADMIN_ROLE_NAME.casefold(),
    }
)


def _error(status_code: int, code: str, message: str, details=None) -> None:
    raise HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "details": details,
        },
    )


def _ensure_custom_role_name_allowed(
    name: str,
) -> None:
    if name.strip().casefold() in RESERVED_ROLE_NAMES:
        _error(
            status.HTTP_403_FORBIDDEN,
            SYSTEM_ROLE_PROTECTED,
            "Reserved role name cannot be used",
        )


def _is_reserved_company_admin_role(
    role: Role,
) -> bool:
    return (
        getattr(role, "name", "").casefold()
        == TENANT_ADMIN_ROLE_NAME.casefold()
        and getattr(role, "company_id", None)
        is not None
        and getattr(role, "is_system", False)
        is False
    )


@router.get("/permissions", response_model=list[PermissionOut])
def list_permissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("permissions:read")),
):
    return [
        permission
        for permission in (
            db.query(Permission)
            .order_by(Permission.id.asc())
            .all()
        )
        if is_tenant_permission_name(
            permission.name
        )
    ]


def _load_tenant_permissions_or_400(
    db: Session,
    permission_ids: list[int],
) -> list[Permission]:
    if not permission_ids:
        return []

    unique_permission_ids = sorted(
        set(permission_ids)
    )

    permissions = (
        db.query(Permission)
        .filter(
            Permission.id.in_(
                unique_permission_ids
            )
        )
        .all()
    )

    if (
        len(permissions)
        != len(unique_permission_ids)
        or any(
            not is_tenant_permission_name(
                permission.name
            )
            for permission in permissions
        )
    ):
        _error(
            status.HTTP_400_BAD_REQUEST,
            INVALID_PERMISSION_IDS,
            "Invalid permission_ids",
        )

    return permissions


def _role_scope_query(db: Session, company_id: int):
    return db.query(Role).filter(
        or_(
            and_(
                Role.company_id == company_id,
                Role.is_system.is_(False),
            ),
            and_(
                Role.company_id.is_(None),
                Role.is_system.is_(True),
                Role.name == GLOBAL_USER_ROLE_NAME,
            ),
        )
    )


def _get_visible_role_or_404(db: Session, role_id: int, company_id: int) -> Role:
    role = _role_scope_query(db, company_id).filter(Role.id == role_id).first()

    if not role:
        _error(status.HTTP_404_NOT_FOUND, ROLE_NOT_FOUND, "Role not found")

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
        _error(
            status.HTTP_409_CONFLICT,
            ROLE_IN_USE,
            "Cannot modify a role assigned to active users",
        )


@router.get("/roles", response_model=list[RoleOut])
def list_roles(
    search: Annotated[
        str | None,
        Query(max_length=100),
    ] = None,
    is_active: Annotated[
        bool | None,
        Query(),
    ] = None,
    offset: Annotated[
        int,
        Query(ge=0),
    ] = 0,
    limit: Annotated[
        int | None,
        Query(ge=1, le=200),
    ] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("roles:read")
    ),
):
    company_id = _require_company_id(
        current_user
    )

    query = _role_scope_query(
        db,
        company_id,
    )

    if search is not None:
        search = search.strip()

        if search:
            pattern = f"%{search}%"

            query = query.filter(
                or_(
                    Role.name.ilike(pattern),
                    Role.description.ilike(
                        pattern
                    ),
                )
            )

    if is_active is not None:
        query = query.filter(
            Role.is_active.is_(is_active)
        )

    query = query.order_by(
        Role.is_system.desc(),
        Role.id.asc(),
    )

    if offset:
        query = query.offset(offset)

    if limit is not None:
        query = query.limit(limit)

    return query.all()


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
def create_role(
    data: RoleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("roles:create")),
):
    company_id = _require_company_id(current_user)
    name = data.name.strip()

    _ensure_custom_role_name_allowed(name)

    existing = _role_scope_query(db, company_id).filter(Role.name == name).first()

    if existing:
        _error(status.HTTP_400_BAD_REQUEST, ROLE_ALREADY_EXISTS, "Role already exists")

    role = Role(
        company_id=company_id,
        name=name,
        description=data.description,
        is_active=data.is_active,
        is_system=False,
    )

    role.permissions = (
        _load_tenant_permissions_or_400(
            db,
            data.permission_ids,
        )
    )

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

    if _is_reserved_company_admin_role(role):
        _error(
            status.HTTP_403_FORBIDDEN,
            SYSTEM_ROLE_PROTECTED,
            "Company administrator role is protected",
        )

    if data.name is not None:
        name = data.name.strip()

        _ensure_custom_role_name_allowed(name)

        existing = _role_scope_query(
            db,
            company_id,
        ).filter(
            Role.name == name,
            Role.id != role_id,
        ).first()

        if existing:
            _error(
                status.HTTP_400_BAD_REQUEST,
                ROLE_ALREADY_EXISTS,
                "Role already exists",
            )

        role.name = name

    if data.description is not None:
        role.description = data.description

    if data.is_active is not None:
        if data.is_active is False:
            _ensure_role_has_no_active_users(role)
        role.is_active = data.is_active

    if data.permission_ids is not None:
        role.permissions = (
            _load_tenant_permissions_or_400(
                db,
                data.permission_ids,
            )
        )

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

    if _is_reserved_company_admin_role(role):
        _error(
            status.HTTP_403_FORBIDDEN,
            SYSTEM_ROLE_PROTECTED,
            "Company administrator role is protected",
        )

    _ensure_role_has_no_active_users(role)

    db.delete(role)
    db.commit()

    return {"message": "Role deleted"}

def _require_company_id(current_user: User) -> int:
    if current_user.company_id is None:
        _error(status.HTTP_403_FORBIDDEN, COMPANY_REQUIRED, "User has no company")
    return current_user.company_id


def _user_role_names(user: User) -> list[str]:
    names = {
        role.name
        for role in getattr(user, "roles", []) or []
        if getattr(role, "is_active", True) is not False
    }

    legacy_role = getattr(user, "role", None)
    if legacy_role:
        names.add(legacy_role)

    return sorted(names)


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


def _admin_user_list_out(user: User) -> AdminUserListOut:
    return AdminUserListOut(
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
        roles=_user_role_names(user),
        permissions=_user_permission_names(user),
    )


def _get_company_user_or_404(db: Session, user_id: int, company_id: int) -> User:
    user = db.query(User).filter(
        User.id == user_id,
        User.company_id == company_id,
    ).first()

    if not user:
        _error(status.HTTP_404_NOT_FOUND, USER_NOT_FOUND, "User not found")

    return user


def _load_roles_or_400(db: Session, role_ids: list[int], company_id: int) -> list[Role]:
    if not role_ids:
        role = db.query(Role).filter(
            Role.name == GLOBAL_USER_ROLE_NAME,
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
        _error(status.HTTP_400_BAD_REQUEST, INVALID_ROLE_IDS, "Invalid role_ids")

    return roles


def _legacy_role_from_roles(roles: list[Role]) -> str:
    if any(
        role.name == TENANT_ADMIN_ROLE_NAME
        and role.is_active
        for role in roles
    ):
        return TENANT_ADMIN_ROLE_NAME

    return GLOBAL_USER_ROLE_NAME


def _is_active_admin(user: User) -> bool:
    if user.is_active is False:
        return False

    return is_company_admin(user)


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
        _error(
            status.HTTP_409_CONFLICT,
            LAST_ADMIN_PROTECTED,
            "Cannot modify the last active admin of the company",
        )


def _provision_defaults_for_user(
    db: Session,
    user: User,
    created_by_user_id: int,
) -> None:
    if user.company_id is None:
        return

    company = (
        db.query(Company)
        .filter(Company.id == user.company_id)
        .first()
    )

    if company is None:
        return

    provision_company_defaults(
        db,
        company,
        created_by_user_id=created_by_user_id,
    )


@router.get(
    "/users",
    response_model=list[AdminUserListOut],
)
def list_company_users(
    search: Annotated[
        str | None,
        Query(max_length=100),
    ] = None,
    is_active: Annotated[
        bool | None,
        Query(),
    ] = None,
    role_id: Annotated[
        int | None,
        Query(ge=1),
    ] = None,
    offset: Annotated[
        int,
        Query(ge=0),
    ] = 0,
    limit: Annotated[
        int | None,
        Query(ge=1, le=200),
    ] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("users:read")
    ),
):
    company_id = _require_company_id(
        current_user
    )

    query = db.query(User).filter(
        User.company_id == company_id
    )

    if search is not None:
        search = search.strip()

        if search:
            pattern = f"%{search}%"

            query = query.filter(
                or_(
                    User.username.ilike(
                        pattern
                    ),
                    User.First_name.ilike(
                        pattern
                    ),
                    User.Last_name.ilike(
                        pattern
                    ),
                )
            )

    if is_active is not None:
        query = query.filter(
            User.is_active.is_(is_active)
        )

    if role_id is not None:
        role = _get_visible_role_or_404(
            db,
            role_id,
            company_id,
        )

        query = query.filter(
            User.roles.any(
                Role.id == role.id
            )
        )

    query = query.order_by(
        User.id.asc()
    )

    if offset:
        query = query.offset(offset)

    if limit is not None:
        query = query.limit(limit)

    users = query.all()

    return [
        _admin_user_list_out(user)
        for user in users
    ]


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
        _error(status.HTTP_409_CONFLICT, USERNAME_ALREADY_EXISTS, "Username already exists")

    roles = _load_roles_or_400(db, payload.role_ids, company_id)

    user = User(
        company_id=company_id,
        username=username,
        First_name=payload.first_name.strip(),
        Last_name=payload.last_name.strip() if payload.last_name else None,
        pw_hash=bcrypt.hash(payload.password),
        role=_legacy_role_from_roles(roles),
        is_active=True,
    )
    user.roles = roles

    db.add(user)
    db.flush()

    _provision_defaults_for_user(
        db,
        user,
        created_by_user_id=current_user.id,
    )

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
            _error(status.HTTP_409_CONFLICT, USERNAME_ALREADY_EXISTS, "Username already exists")
        user.username = username

    if payload.first_name is not None:
        user.First_name = payload.first_name.strip()

    if payload.last_name is not None:
        user.Last_name = payload.last_name.strip() if payload.last_name else None

    if payload.notification_token is not None:
        user.notification_token = payload.notification_token

    if payload.role_ids is not None:
        if user.id == current_user.id:
            _error(
                status.HTTP_400_BAD_REQUEST,
                SELF_ACTION_FORBIDDEN,
                "Cannot change your own roles",
            )

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
    current_user: User = Depends(require_permission("users:roles:manage")),
):
    company_id = _require_company_id(current_user)
    user = _get_company_user_or_404(db, user_id, company_id)

    if user.id == current_user.id:
        _error(
            status.HTTP_400_BAD_REQUEST,
            SELF_ACTION_FORBIDDEN,
            "Cannot change your own roles",
        )

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
    current_user: User = Depends(require_permission("users:status:manage")),
):
    company_id = _require_company_id(current_user)
    user = _get_company_user_or_404(db, user_id, company_id)

    user.is_active = True
    user.deactivated_at = None

    _provision_defaults_for_user(
        db,
        user,
        created_by_user_id=current_user.id,
    )

    db.commit()
    db.refresh(user)

    return _admin_user_out(user)


@router.post("/users/{user_id}/deactivate", response_model=AdminUserOut)
def deactivate_company_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users:status:manage")),
):
    company_id = _require_company_id(current_user)
    user = _get_company_user_or_404(db, user_id, company_id)

    if user.id == current_user.id:
        _error(
            status.HTTP_400_BAD_REQUEST,
            SELF_ACTION_FORBIDDEN,
            "Cannot deactivate your own account",
        )

    _ensure_not_last_active_admin(db, user)

    user.is_active = False
    user.deactivated_at = datetime.utcnow()

    revoke_user_authentication(
        db,
        user,
        reason="user_deactivated",
    )

    db.commit()
    db.refresh(user)

    return _admin_user_out(user)


@router.post("/users/{user_id}/reset-password", response_model=AdminUserOut)
def reset_company_user_password(
    user_id: int,
    payload: AdminUserPasswordReset,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users:password:reset")),
):
    company_id = _require_company_id(current_user)
    user = _get_company_user_or_404(db, user_id, company_id)

    user.pw_hash = bcrypt.hash(payload.new_password)
    user.password_changed_at = datetime.utcnow()

    revoke_user_authentication(
        db,
        user,
        reason="admin_password_reset",
    )

    db.commit()
    db.refresh(user)

    return _admin_user_out(user)



def _current_user_role_names(user: User) -> list[str]:
    names = {
        role.name
        for role in getattr(user, "roles", []) or []
        if getattr(role, "is_active", True) is not False
    }

    legacy_role = getattr(user, "role", None)
    if legacy_role:
        names.add(legacy_role)

    return sorted(names)


@router.get("/me/access", response_model=CurrentUserAccessOut)
def get_current_user_access(
    current_user: User = Depends(get_current_user),
):
    roles = _user_role_names(current_user)
    permissions = _user_permission_names(current_user)

    return CurrentUserAccessOut(
        user_id=current_user.id,
        company_id=current_user.company_id,
        username=current_user.username,
        roles=roles,
        permissions=permissions,
        is_admin=is_company_admin(
            current_user
        ),
        is_active=getattr(current_user, "is_active", True) is not False,
    )
