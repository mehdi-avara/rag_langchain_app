from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from passlib.hash import bcrypt
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from Models.company import Company
from Models.user import User
from Models.rbac import Role, Permission
from Models.auth_session import AuthSession
from Models.admin_audit import AdminAuditLog
from core.authorization import (
    GLOBAL_ADMIN_ROLE_NAME,
    GLOBAL_USER_ROLE_NAME,
    TENANT_ADMIN_ROLE_NAME,
    is_company_admin,
    is_tenant_permission_name,
)
from core.admin_audit import append_admin_audit
from core.admin_summary import build_admin_summary
from core.user_invitations import (
    admin_invitation_payload,
    create_user_invitation,
    invitation_role_ids,
    list_user_invitations,
    reissue_user_invitation,
    revoke_user_invitation,
)
from core.auth_sessions import (
    revoke_auth_session,
    revoke_user_authentication,
)
from db.init_db import get_db
from db.provision_company_defaults import provision_company_defaults
from deps import get_current_user, require_permission
from schemas.admin_audit import AdminAuditLogOut
from schemas.admin_summary import AdminSummaryOut
from schemas.user_invitations import (
    AdminUserInvitationActionOut,
    AdminUserInvitationCreate,
    AdminUserInvitationOut,
    AdminUserInvitationTokenOut,
    InvitationStatus,
)
from schemas.users import (
    AdminAuthSessionActionOut,
    AdminAuthSessionOut,
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
    AUTH_SESSION_NOT_FOUND,
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
    USER_INVITATION_ALREADY_EXISTS,
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


@router.get(
    "/admin-summary",
    response_model=AdminSummaryOut,
)
def get_admin_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "admin:summary:read"
        )
    ),
):
    company_id = _require_company_id(
        current_user
    )

    company = (
        db.query(Company)
        .filter(
            Company.id
            == company_id
        )
        .first()
    )

    if company is None:
        _error(
            status.HTTP_404_NOT_FOUND,
            COMPANY_REQUIRED,
            "Company not found",
        )

    summary = build_admin_summary(
        db,
        company_id=company_id,
        company_name=company.name,
    )

    return AdminSummaryOut(
        **summary
    )


@router.get(
    "/audit-logs",
    response_model=list[AdminAuditLogOut],
)
def list_admin_audit_logs(
    action: Annotated[
        str | None,
        Query(max_length=80),
    ] = None,
    actor_user_id: Annotated[
        int | None,
        Query(ge=1),
    ] = None,
    target_type: Annotated[
        str | None,
        Query(max_length=40),
    ] = None,
    target_id: Annotated[
        str | None,
        Query(max_length=64),
    ] = None,
    created_from: Annotated[
        datetime | None,
        Query(),
    ] = None,
    created_to: Annotated[
        datetime | None,
        Query(),
    ] = None,
    offset: Annotated[
        int,
        Query(ge=0),
    ] = 0,
    limit: Annotated[
        int,
        Query(ge=1, le=200),
    ] = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "admin:audit:read"
        )
    ),
):
    company_id = _require_company_id(
        current_user
    )

    if (
        created_from is not None
        and created_to is not None
        and created_from > created_to
    ):
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail={
                "code": (
                    "ADMIN_AUDIT_INVALID_DATE_RANGE"
                ),
                "message": (
                    "created_from must be before "
                    "or equal to created_to"
                ),
            },
        )

    query = db.query(
        AdminAuditLog
    ).filter(
        AdminAuditLog.company_id
        == company_id
    )

    if action:
        query = query.filter(
            AdminAuditLog.action
            == action.strip()
        )

    if actor_user_id is not None:
        query = query.filter(
            AdminAuditLog.actor_user_id
            == actor_user_id
        )

    if target_type:
        query = query.filter(
            AdminAuditLog.target_type
            == target_type.strip()
        )

    if target_id:
        query = query.filter(
            AdminAuditLog.target_id
            == target_id.strip()
        )

    if created_from is not None:
        query = query.filter(
            AdminAuditLog.created_at
            >= created_from
        )

    if created_to is not None:
        query = query.filter(
            AdminAuditLog.created_at
            <= created_to
        )

    logs = (
        query.order_by(
            AdminAuditLog.created_at.desc(),
            AdminAuditLog.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        audit
        for audit in logs
        if audit.company_id
        == company_id
    ]


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
    db.flush()

    append_admin_audit(
        db,
        company_id=company_id,
        actor_user_id=current_user.id,
        action="role.created",
        target_type="role",
        target_id=role.id,
        details={
            "name": role.name,
            "description": role.description,
            "is_active": role.is_active,
            "permission_ids": sorted(
                permission.id
                for permission
                in role.permissions
            ),
        },
    )

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

    before_state = {
        "name": role.name,
        "description": role.description,
        "is_active": role.is_active,
        "permission_ids": sorted(
            permission.id
            for permission
            in role.permissions
        ),
    }

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

    after_state = {
        "name": role.name,
        "description": role.description,
        "is_active": role.is_active,
        "permission_ids": sorted(
            permission.id
            for permission
            in role.permissions
        ),
    }

    if before_state != after_state:
        append_admin_audit(
            db,
            company_id=company_id,
            actor_user_id=current_user.id,
            action="role.updated",
            target_type="role",
            target_id=role.id,
            details={
                "before": before_state,
                "after": after_state,
            },
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

    audit_details = {
        "name": role.name,
        "description": role.description,
        "is_active": role.is_active,
        "permission_ids": sorted(
            permission.id
            for permission
            in role.permissions
        ),
    }

    db.delete(role)

    append_admin_audit(
        db,
        company_id=company_id,
        actor_user_id=current_user.id,
        action="role.deleted",
        target_type="role",
        target_id=role.id,
        details=audit_details,
    )

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


def _get_user_auth_session_or_404(
    db: Session,
    *,
    session_id: str,
    user: User,
    company_id: int,
) -> AuthSession:
    session = (
        db.query(AuthSession)
        .filter(
            AuthSession.id == session_id,
            AuthSession.user_id == user.id,
            AuthSession.company_id == company_id,
        )
        .first()
    )

    if (
        session is None
        or session.user_id != user.id
        or session.company_id != company_id
    ):
        _error(
            status.HTTP_404_NOT_FOUND,
            AUTH_SESSION_NOT_FOUND,
            "Authentication session not found",
        )

    return session


def _admin_auth_session_out(
    session: AuthSession,
) -> AdminAuthSessionOut:
    now = datetime.utcnow()

    return AdminAuthSessionOut(
        id=session.id,
        user_id=session.user_id,
        company_id=session.company_id,
        token_version=session.token_version,
        created_at=session.created_at,
        last_rotated_at=session.last_rotated_at,
        last_used_at=session.last_used_at,
        expires_at=session.expires_at,
        revoked_at=session.revoked_at,
        revoked_reason=session.revoked_reason,
        is_revoked=(
            session.revoked_at is not None
        ),
        is_expired=(
            session.expires_at <= now
        ),
    )


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
    "/invitations",
    response_model=list[
        AdminUserInvitationOut
    ],
)
def list_company_user_invitations(
    search: Annotated[
        str | None,
        Query(max_length=255),
    ] = None,
    invitation_status: Annotated[
        InvitationStatus | None,
        Query(alias="status"),
    ] = None,
    offset: Annotated[
        int,
        Query(ge=0),
    ] = 0,
    limit: Annotated[
        int,
        Query(ge=1, le=200),
    ] = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "users:invitations:read"
        )
    ),
):
    company_id = _require_company_id(
        current_user
    )

    invitations = (
        list_user_invitations(
            db,
            company_id=company_id,
            search=search,
            status_filter=(
                invitation_status
            ),
            offset=offset,
            limit=limit,
        )
    )

    return [
        AdminUserInvitationOut(
            **admin_invitation_payload(
                invitation
            )
        )
        for invitation in invitations
        if invitation.company_id
        == company_id
    ]


@router.post(
    "/invitations",
    response_model=(
        AdminUserInvitationTokenOut
    ),
    status_code=status.HTTP_201_CREATED,
)
def create_company_user_invitation(
    payload: AdminUserInvitationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "users:invitations:manage"
        )
    ),
):
    company_id = _require_company_id(
        current_user
    )

    try:
        invitation, raw_token = (
            create_user_invitation(
                db,
                company_id=company_id,
                invited_by_user_id=(
                    current_user.id
                ),
                email=payload.email,
                first_name=(
                    payload.first_name
                ),
                last_name=(
                    payload.last_name
                ),
                role_ids=(
                    payload.role_ids
                ),
            )
        )

        append_admin_audit(
            db,
            company_id=company_id,
            actor_user_id=(
                current_user.id
            ),
            action="user.invited",
            target_type=(
                "user_invitation"
            ),
            target_id=invitation.id,
            details={
                "email": (
                    invitation.email
                ),
                "role_ids": (
                    invitation_role_ids(
                        invitation
                    )
                ),
                "expires_at": (
                    invitation.expires_at.isoformat()
                ),
            },
        )

        db.commit()
        db.refresh(invitation)

    except IntegrityError as exc:
        db.rollback()

        _error(
            status.HTTP_409_CONFLICT,
            USER_INVITATION_ALREADY_EXISTS,
            "Invitation conflicts with an existing record",
        )

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise

    return AdminUserInvitationTokenOut(
        **admin_invitation_payload(
            invitation
        ),
        invitation_token=raw_token,
    )


@router.post(
    "/invitations/{invitation_id}/reissue",
    response_model=(
        AdminUserInvitationTokenOut
    ),
)
def reissue_company_user_invitation(
    invitation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "users:invitations:manage"
        )
    ),
):
    company_id = _require_company_id(
        current_user
    )

    try:
        invitation, raw_token = (
            reissue_user_invitation(
                db,
                invitation_id=(
                    invitation_id
                ),
                company_id=company_id,
            )
        )

        append_admin_audit(
            db,
            company_id=company_id,
            actor_user_id=(
                current_user.id
            ),
            action=(
                "user.invitation_reissued"
            ),
            target_type=(
                "user_invitation"
            ),
            target_id=invitation.id,
            details={
                "email": (
                    invitation.email
                ),
                "role_ids": (
                    invitation_role_ids(
                        invitation
                    )
                ),
                "expires_at": (
                    invitation.expires_at.isoformat()
                ),
            },
        )

        db.commit()
        db.refresh(invitation)

    except IntegrityError as exc:
        db.rollback()

        _error(
            status.HTTP_409_CONFLICT,
            USER_INVITATION_ALREADY_EXISTS,
            "Invitation reissue conflicts with an existing record",
        )

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise

    return AdminUserInvitationTokenOut(
        **admin_invitation_payload(
            invitation
        ),
        invitation_token=raw_token,
    )


@router.delete(
    "/invitations/{invitation_id}",
    response_model=(
        AdminUserInvitationActionOut
    ),
)
def revoke_company_user_invitation(
    invitation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "users:invitations:manage"
        )
    ),
):
    company_id = _require_company_id(
        current_user
    )

    try:
        invitation, changed = (
            revoke_user_invitation(
                db,
                invitation_id=(
                    invitation_id
                ),
                company_id=company_id,
            )
        )

        if changed:
            append_admin_audit(
                db,
                company_id=company_id,
                actor_user_id=(
                    current_user.id
                ),
                action=(
                    "user.invitation_revoked"
                ),
                target_type=(
                    "user_invitation"
                ),
                target_id=invitation.id,
                details={
                    "email": (
                        invitation.email
                    ),
                    "role_ids": (
                        invitation_role_ids(
                            invitation
                        )
                    ),
                },
            )

        db.commit()

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise

    return AdminUserInvitationActionOut(
        success=True,
        changed=changed,
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

    append_admin_audit(
        db,
        company_id=company_id,
        actor_user_id=current_user.id,
        action="user.created",
        target_type="user",
        target_id=user.id,
        details={
            "username": user.username,
            "first_name": user.First_name,
            "last_name": user.Last_name,
            "role_ids": sorted(
                role.id
                for role in user.roles
            ),
        },
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

    before_profile = {
        "username": user.username,
        "first_name": user.First_name,
        "last_name": user.Last_name,
    }

    before_role_ids = sorted(
        role.id
        for role in user.roles
    )

    notification_channel_changed = (
        payload.notification_token
        is not None
        and payload.notification_token
        != user.notification_token
    )

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

    after_profile = {
        "username": user.username,
        "first_name": user.First_name,
        "last_name": user.Last_name,
    }

    after_role_ids = sorted(
        role.id
        for role in user.roles
    )

    if before_profile != after_profile or notification_channel_changed:
        append_admin_audit(
            db,
            company_id=company_id,
            actor_user_id=current_user.id,
            action="user.updated",
            target_type="user",
            target_id=user.id,
            details={
                "before": before_profile,
                "after": after_profile,
                "notification_channel_changed": (
                    notification_channel_changed
                ),
            },
        )

    if before_role_ids != after_role_ids:
        append_admin_audit(
            db,
            company_id=company_id,
            actor_user_id=current_user.id,
            action="user.roles_updated",
            target_type="user",
            target_id=user.id,
            details={
                "before_role_ids": (
                    before_role_ids
                ),
                "after_role_ids": (
                    after_role_ids
                ),
            },
        )

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

    before_role_ids = sorted(
        role.id
        for role in user.roles
    )

    roles = _load_roles_or_400(db, payload.role_ids, company_id)
    user.roles = roles
    user.role = _legacy_role_from_roles(roles)

    after_role_ids = sorted(
        role.id
        for role in user.roles
    )

    if before_role_ids != after_role_ids:
        append_admin_audit(
            db,
            company_id=company_id,
            actor_user_id=current_user.id,
            action="user.roles_updated",
            target_type="user",
            target_id=user.id,
            details={
                "before_role_ids": (
                    before_role_ids
                ),
                "after_role_ids": (
                    after_role_ids
                ),
            },
        )

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

    was_active = user.is_active

    user.is_active = True
    user.deactivated_at = None

    _provision_defaults_for_user(
        db,
        user,
        created_by_user_id=current_user.id,
    )

    if not was_active:
        append_admin_audit(
            db,
            company_id=company_id,
            actor_user_id=current_user.id,
            action="user.activated",
            target_type="user",
            target_id=user.id,
            details={},
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

    was_active = user.is_active

    user.is_active = False
    user.deactivated_at = datetime.utcnow()

    revoked_sessions = (
        revoke_user_authentication(
            db,
            user,
            reason="user_deactivated",
        )
    )

    append_admin_audit(
        db,
        company_id=company_id,
        actor_user_id=current_user.id,
        action="user.deactivated",
        target_type="user",
        target_id=user.id,
        details={
            "was_active": was_active,
            "revoked_sessions": (
                revoked_sessions
            ),
        },
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

    revoked_sessions = (
        revoke_user_authentication(
            db,
            user,
            reason="admin_password_reset",
        )
    )

    append_admin_audit(
        db,
        company_id=company_id,
        actor_user_id=current_user.id,
        action="user.password_reset",
        target_type="user",
        target_id=user.id,
        details={
            "revoked_sessions": (
                revoked_sessions
            ),
        },
    )

    db.commit()
    db.refresh(user)

    return _admin_user_out(user)



@router.get(
    "/users/{user_id}/sessions",
    response_model=list[AdminAuthSessionOut],
)
def list_company_user_sessions(
    user_id: int,
    revoked: Annotated[
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
        require_permission(
            "users:sessions:read"
        )
    ),
):
    company_id = _require_company_id(
        current_user
    )

    user = _get_company_user_or_404(
        db,
        user_id,
        company_id,
    )

    query = db.query(
        AuthSession
    ).filter(
        AuthSession.user_id == user.id,
        AuthSession.company_id == company_id,
    )

    if revoked is True:
        query = query.filter(
            AuthSession.revoked_at.is_not(
                None
            )
        )

    elif revoked is False:
        query = query.filter(
            AuthSession.revoked_at.is_(
                None
            )
        )

    query = query.order_by(
        AuthSession.created_at.desc()
    )

    if offset:
        query = query.offset(
            offset
        )

    if limit is not None:
        query = query.limit(
            limit
        )

    return [
        _admin_auth_session_out(
            session
        )
        for session in query.all()
        if (
            session.user_id == user.id
            and session.company_id
            == company_id
            and (
                revoked is None
                or (
                    revoked
                    and session.revoked_at
                    is not None
                )
                or (
                    not revoked
                    and session.revoked_at
                    is None
                )
            )
        )
    ]


@router.delete(
    "/users/{user_id}/sessions/{session_id}",
    response_model=AdminAuthSessionActionOut,
)
def revoke_company_user_session(
    user_id: int,
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "users:sessions:manage"
        )
    ),
):
    company_id = _require_company_id(
        current_user
    )

    user = _get_company_user_or_404(
        db,
        user_id,
        company_id,
    )

    session = _get_user_auth_session_or_404(
        db,
        session_id=session_id,
        user=user,
        company_id=company_id,
    )

    revoked = revoke_auth_session(
        session,
        reason="admin_session_revoked",
    )

    append_admin_audit(
        db,
        company_id=company_id,
        actor_user_id=current_user.id,
        action="user.session_revoked",
        target_type="auth_session",
        target_id=session.id,
        details={
            "user_id": user.id,
            "revoked": revoked,
        },
    )

    db.commit()

    return AdminAuthSessionActionOut(
        success=True,
        revoked_sessions=(
            1 if revoked else 0
        ),
    )


@router.post(
    "/users/{user_id}/sessions/revoke-all",
    response_model=AdminAuthSessionActionOut,
)
def revoke_all_company_user_sessions(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "users:sessions:manage"
        )
    ),
):
    company_id = _require_company_id(
        current_user
    )

    user = _get_company_user_or_404(
        db,
        user_id,
        company_id,
    )

    revoked_count = (
        revoke_user_authentication(
            db,
            user,
            reason=(
                "admin_sessions_revoked_all"
            ),
        )
    )

    append_admin_audit(
        db,
        company_id=company_id,
        actor_user_id=current_user.id,
        action="user.sessions_revoked_all",
        target_type="user",
        target_id=user.id,
        details={
            "revoked_sessions": (
                revoked_count
            ),
        },
    )

    db.commit()

    return AdminAuthSessionActionOut(
        success=True,
        revoked_sessions=revoked_count,
    )


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
