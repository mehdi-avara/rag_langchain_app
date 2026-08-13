from __future__ import annotations

import hashlib
import secrets
from datetime import (
    datetime,
    timedelta,
)

from fastapi import (
    HTTPException,
    status,
)
from sqlalchemy import (
    and_,
    or_,
)
from sqlalchemy.orm import Session

from Models.company import Company
from Models.rbac import Role
from Models.user import User
from Models.user_invitation import (
    UserInvitation,
)
from core.admin_audit import (
    append_admin_audit,
)
from core.authorization import (
    GLOBAL_USER_ROLE_NAME,
    TENANT_ADMIN_ROLE_NAME,
)
from core.exceptions.error_codes import (
    INVALID_ROLE_IDS,
    USERNAME_ALREADY_EXISTS,
    USER_INVITATION_ALREADY_ACCEPTED,
    USER_INVITATION_ALREADY_EXISTS,
    USER_INVITATION_CONFIGURATION_ERROR,
    USER_INVITATION_EXPIRED,
    USER_INVITATION_INVALID,
    USER_INVITATION_NOT_FOUND,
    USER_INVITATION_REVOKED,
    USER_INVITATION_UNAVAILABLE,
)
from db.provision_company_defaults import (
    provision_company_defaults,
)
from settings import get_settings


settings = get_settings()

INVITATION_TOKEN_BYTES = 32
MIN_TOKEN_LENGTH = 32
MAX_TOKEN_LENGTH = 256


def _error(
    status_code: int,
    code: str,
    message: str,
) -> None:
    raise HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
        },
    )


def normalize_invitation_email(
    email: str,
) -> str:
    email = email.strip().lower()

    if (
        "@" not in email
        or "." not in email.split("@")[-1]
    ):
        _error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            USER_INVITATION_INVALID,
            "Invalid invitation email",
        )

    return email


def generate_invitation_token() -> str:
    return secrets.token_urlsafe(
        INVITATION_TOKEN_BYTES
    )


def hash_invitation_token(
    token: str,
) -> str:
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


def invitation_expiration(
    now: datetime | None = None,
) -> datetime:
    lifetime = int(
        settings.user_invitation_exp_hours
    )

    if (
        lifetime <= 0
        or lifetime > 24 * 30
    ):
        _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            USER_INVITATION_CONFIGURATION_ERROR,
            "Invitation lifetime is invalid",
        )

    now = (
        now
        or datetime.utcnow()
    )

    return (
        now
        + timedelta(hours=lifetime)
    )


def invitation_status(
    invitation: UserInvitation,
    *,
    now: datetime | None = None,
) -> str:
    if invitation.accepted_at is not None:
        return "accepted"

    if invitation.revoked_at is not None:
        return "revoked"

    now = (
        now
        or datetime.utcnow()
    )

    if invitation.expires_at <= now:
        return "expired"

    return "pending"


def invitation_role_ids(
    invitation: UserInvitation,
) -> list[int]:
    return sorted(
        {
            role.id
            for role in (
                getattr(
                    invitation,
                    "roles",
                    [],
                )
                or []
            )
        }
    )


def _role_scope_query(
    db: Session,
    company_id: int,
):
    return db.query(Role).filter(
        or_(
            and_(
                Role.company_id
                == company_id,
                Role.is_system.is_(False),
            ),
            and_(
                Role.company_id.is_(None),
                Role.is_system.is_(True),
                Role.name
                == GLOBAL_USER_ROLE_NAME,
            ),
        )
    )


def load_invitation_roles(
    db: Session,
    *,
    company_id: int,
    role_ids: list[int],
) -> list[Role]:
    if not role_ids:
        role = (
            db.query(Role)
            .filter(
                Role.company_id.is_(None),
                Role.name
                == GLOBAL_USER_ROLE_NAME,
                Role.is_system.is_(True),
                Role.is_active.is_(True),
            )
            .first()
        )

        if role is None:
            _error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                USER_INVITATION_CONFIGURATION_ERROR,
                "Default user role is unavailable",
            )

        return [
            role
        ]

    unique_role_ids = sorted(
        set(role_ids)
    )

    roles = (
        _role_scope_query(
            db,
            company_id,
        )
        .filter(
            Role.id.in_(
                unique_role_ids
            ),
            Role.is_active.is_(True),
        )
        .all()
    )

    if (
        len(roles)
        != len(unique_role_ids)
    ):
        _error(
            status.HTTP_400_BAD_REQUEST,
            INVALID_ROLE_IDS,
            "Invalid role_ids",
        )

    return roles


def validate_assigned_invitation_roles(
    db: Session,
    invitation: UserInvitation,
) -> list[Role]:
    role_ids = invitation_role_ids(
        invitation
    )

    if (
        len(role_ids)
        != int(
            invitation.role_count
            or 0
        )
    ):
        _error(
            status.HTTP_409_CONFLICT,
            INVALID_ROLE_IDS,
            "Invitation roles are no longer valid",
        )

    roles = load_invitation_roles(
        db,
        company_id=invitation.company_id,
        role_ids=role_ids,
    )

    if (
        len(roles)
        != invitation.role_count
    ):
        _error(
            status.HTTP_409_CONFLICT,
            INVALID_ROLE_IDS,
            "Invitation roles are no longer valid",
        )

    return roles


def _legacy_role_from_roles(
    roles: list[Role],
) -> str:
    if any(
        role.name
        == TENANT_ADMIN_ROLE_NAME
        and role.is_active
        for role in roles
    ):
        return TENANT_ADMIN_ROLE_NAME

    return GLOBAL_USER_ROLE_NAME


def _validate_raw_token(
    token: str,
) -> str:
    if not isinstance(
        token,
        str,
    ):
        _error(
            status.HTTP_404_NOT_FOUND,
            USER_INVITATION_NOT_FOUND,
            "Invitation not found",
        )

    token = token.strip()

    if not (
        MIN_TOKEN_LENGTH
        <= len(token)
        <= MAX_TOKEN_LENGTH
    ):
        _error(
            status.HTTP_404_NOT_FOUND,
            USER_INVITATION_NOT_FOUND,
            "Invitation not found",
        )

    return token


def get_invitation_by_token(
    db: Session,
    *,
    token: str,
    lock: bool = False,
) -> UserInvitation:
    token = _validate_raw_token(
        token
    )

    query = (
        db.query(UserInvitation)
        .filter(
            UserInvitation.token_hash
            == hash_invitation_token(
                token
            )
        )
    )

    if lock:
        query = query.with_for_update()

    invitation = query.first()

    if invitation is None:
        _error(
            status.HTTP_404_NOT_FOUND,
            USER_INVITATION_NOT_FOUND,
            "Invitation not found",
        )

    return invitation


def get_company_invitation(
    db: Session,
    *,
    invitation_id: int,
    company_id: int,
    lock: bool = False,
) -> UserInvitation:
    query = (
        db.query(UserInvitation)
        .filter(
            UserInvitation.id
            == invitation_id,
            UserInvitation.company_id
            == company_id,
        )
    )

    if lock:
        query = query.with_for_update()

    invitation = query.first()

    if (
        invitation is None
        or invitation.company_id
        != company_id
    ):
        _error(
            status.HTTP_404_NOT_FOUND,
            USER_INVITATION_NOT_FOUND,
            "Invitation not found",
        )

    return invitation


def create_user_invitation(
    db: Session,
    *,
    company_id: int,
    invited_by_user_id: int,
    email: str,
    first_name: str,
    last_name: str | None,
    role_ids: list[int],
) -> tuple[
    UserInvitation,
    str,
]:
    email = normalize_invitation_email(
        email
    )

    existing_user = (
        db.query(User)
        .filter(
            User.username == email
        )
        .first()
    )

    if existing_user is not None:
        _error(
            status.HTTP_409_CONFLICT,
            USERNAME_ALREADY_EXISTS,
            "Username already exists",
        )

    existing_invitation = (
        db.query(UserInvitation)
        .filter(
            UserInvitation.company_id
            == company_id,
            UserInvitation.email
            == email,
            UserInvitation.accepted_at.is_(
                None
            ),
            UserInvitation.revoked_at.is_(
                None
            ),
        )
        .first()
    )

    if existing_invitation is not None:
        _error(
            status.HTTP_409_CONFLICT,
            USER_INVITATION_ALREADY_EXISTS,
            (
                "An open invitation already exists; "
                "reissue the existing invitation"
            ),
        )

    roles = load_invitation_roles(
        db,
        company_id=company_id,
        role_ids=role_ids,
    )

    raw_token = (
        generate_invitation_token()
    )

    invitation = UserInvitation(
        company_id=company_id,
        email=email,
        first_name=first_name.strip(),
        last_name=(
            last_name.strip()
            if last_name
            else None
        ),
        token_hash=hash_invitation_token(
            raw_token
        ),
        role_count=len(roles),
        expires_at=invitation_expiration(),
        invited_by_user_id=(
            invited_by_user_id
        ),
    )

    invitation.roles = roles

    db.add(invitation)
    db.flush()

    return (
        invitation,
        raw_token,
    )


def reissue_user_invitation(
    db: Session,
    *,
    invitation_id: int,
    company_id: int,
) -> tuple[
    UserInvitation,
    str,
]:
    invitation = get_company_invitation(
        db,
        invitation_id=invitation_id,
        company_id=company_id,
        lock=True,
    )

    state = invitation_status(
        invitation
    )

    if state == "accepted":
        _error(
            status.HTTP_409_CONFLICT,
            USER_INVITATION_ALREADY_ACCEPTED,
            "Invitation has already been accepted",
        )

    if state == "revoked":
        _error(
            status.HTTP_409_CONFLICT,
            USER_INVITATION_REVOKED,
            "Revoked invitation cannot be reissued",
        )

    validate_assigned_invitation_roles(
        db,
        invitation,
    )

    existing_user = (
        db.query(User)
        .filter(
            User.username
            == invitation.email
        )
        .first()
    )

    if existing_user is not None:
        _error(
            status.HTTP_409_CONFLICT,
            USERNAME_ALREADY_EXISTS,
            "Username already exists",
        )

    raw_token = (
        generate_invitation_token()
    )

    invitation.token_hash = (
        hash_invitation_token(
            raw_token
        )
    )

    invitation.expires_at = (
        invitation_expiration()
    )

    db.flush()

    return (
        invitation,
        raw_token,
    )


def revoke_user_invitation(
    db: Session,
    *,
    invitation_id: int,
    company_id: int,
) -> tuple[
    UserInvitation,
    bool,
]:
    invitation = get_company_invitation(
        db,
        invitation_id=invitation_id,
        company_id=company_id,
        lock=True,
    )

    state = invitation_status(
        invitation
    )

    if state == "accepted":
        _error(
            status.HTTP_409_CONFLICT,
            USER_INVITATION_ALREADY_ACCEPTED,
            "Accepted invitation cannot be revoked",
        )

    if state == "revoked":
        return (
            invitation,
            False,
        )

    invitation.revoked_at = (
        datetime.utcnow()
    )

    db.flush()

    return (
        invitation,
        True,
    )


def list_user_invitations(
    db: Session,
    *,
    company_id: int,
    search: str | None,
    status_filter: str | None,
    offset: int,
    limit: int,
) -> list[UserInvitation]:
    now = datetime.utcnow()

    query = (
        db.query(UserInvitation)
        .filter(
            UserInvitation.company_id
            == company_id
        )
    )

    if search:
        pattern = (
            f"%{search.strip()}%"
        )

        query = query.filter(
            or_(
                UserInvitation.email.ilike(
                    pattern
                ),
                UserInvitation.first_name.ilike(
                    pattern
                ),
                UserInvitation.last_name.ilike(
                    pattern
                ),
            )
        )

    if status_filter == "pending":
        query = query.filter(
            UserInvitation.accepted_at.is_(
                None
            ),
            UserInvitation.revoked_at.is_(
                None
            ),
            UserInvitation.expires_at > now,
        )

    elif status_filter == "accepted":
        query = query.filter(
            UserInvitation.accepted_at.is_not(
                None
            )
        )

    elif status_filter == "revoked":
        query = query.filter(
            UserInvitation.revoked_at.is_not(
                None
            )
        )

    elif status_filter == "expired":
        query = query.filter(
            UserInvitation.accepted_at.is_(
                None
            ),
            UserInvitation.revoked_at.is_(
                None
            ),
            UserInvitation.expires_at
            <= now,
        )

    invitations = (
        query.order_by(
            UserInvitation.created_at.desc(),
            UserInvitation.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        invitation
        for invitation in invitations
        if invitation.company_id
        == company_id
    ]


def admin_invitation_payload(
    invitation: UserInvitation,
) -> dict:
    return {
        "id": invitation.id,
        "company_id": (
            invitation.company_id
        ),
        "email": invitation.email,
        "first_name": (
            invitation.first_name
        ),
        "last_name": (
            invitation.last_name
        ),
        "role_ids": (
            invitation_role_ids(
                invitation
            )
        ),
        "status": (
            invitation_status(
                invitation
            )
        ),
        "expires_at": (
            invitation.expires_at
        ),
        "accepted_at": (
            invitation.accepted_at
        ),
        "revoked_at": (
            invitation.revoked_at
        ),
        "invited_by_user_id": (
            invitation.invited_by_user_id
        ),
        "created_at": (
            invitation.created_at
        ),
        "updated_at": (
            invitation.updated_at
        ),
    }


def public_invitation_payload(
    db: Session,
    invitation: UserInvitation,
) -> dict:
    company = (
        db.query(Company)
        .filter(
            Company.id
            == invitation.company_id
        )
        .first()
    )

    if company is None:
        _error(
            status.HTTP_404_NOT_FOUND,
            USER_INVITATION_NOT_FOUND,
            "Invitation not found",
        )

    return {
        "company_id": company.id,
        "company_name": company.name,
        "email": invitation.email,
        "first_name": (
            invitation.first_name
        ),
        "last_name": (
            invitation.last_name
        ),
        "status": (
            invitation_status(
                invitation
            )
        ),
        "expires_at": (
            invitation.expires_at
        ),
    }


def accept_user_invitation(
    db: Session,
    *,
    token: str,
    password: str,
) -> User:
    invitation = get_invitation_by_token(
        db,
        token=token,
        lock=True,
    )

    state = invitation_status(
        invitation
    )

    if state == "accepted":
        _error(
            status.HTTP_409_CONFLICT,
            USER_INVITATION_ALREADY_ACCEPTED,
            "Invitation has already been accepted",
        )

    if state == "revoked":
        _error(
            status.HTTP_410_GONE,
            USER_INVITATION_REVOKED,
            "Invitation has been revoked",
        )

    if state == "expired":
        _error(
            status.HTTP_410_GONE,
            USER_INVITATION_EXPIRED,
            "Invitation has expired",
        )

    company = (
        db.query(Company)
        .filter(
            Company.id
            == invitation.company_id
        )
        .first()
    )

    if (
        company is None
        or getattr(
            company,
            "is_active",
            True,
        )
        is False
    ):
        _error(
            status.HTTP_403_FORBIDDEN,
            USER_INVITATION_UNAVAILABLE,
            "Invitation company is unavailable",
        )

    existing_user = (
        db.query(User)
        .filter(
            User.username
            == invitation.email
        )
        .first()
    )

    if existing_user is not None:
        _error(
            status.HTTP_409_CONFLICT,
            USERNAME_ALREADY_EXISTS,
            "Username already exists",
        )

    roles = (
        validate_assigned_invitation_roles(
            db,
            invitation,
        )
    )

    from passlib.hash import bcrypt

    user = User(
        company_id=invitation.company_id,
        username=invitation.email,
        First_name=invitation.first_name,
        Last_name=invitation.last_name,
        pw_hash=bcrypt.hash(
            password
        ),
        role=_legacy_role_from_roles(
            roles
        ),
        is_active=True,
    )

    user.roles = roles

    db.add(user)
    db.flush()

    provision_company_defaults(
        db,
        company,
        created_by_user_id=(
            invitation.invited_by_user_id
            or user.id
        ),
    )

    invitation.accepted_at = (
        datetime.utcnow()
    )

    append_admin_audit(
        db,
        company_id=invitation.company_id,
        actor_user_id=user.id,
        action=(
            "user.invitation_accepted"
        ),
        target_type="user",
        target_id=user.id,
        details={
            "invitation_id": (
                invitation.id
            ),
            "email": invitation.email,
            "role_ids": sorted(
                role.id
                for role in roles
            ),
            "invited_by_user_id": (
                invitation.invited_by_user_id
            ),
        },
    )

    db.flush()

    return user
