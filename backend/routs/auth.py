import re

from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError
from passlib.hash import bcrypt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from Models import User, Company, Permission, Role
from core.authorization import (
    TENANT_ADMIN_ROLE_NAME,
    is_tenant_permission_name,
)
from core.exceptions.error_codes import (
    AUTH_REQUIRED,
    INVALID_TOKEN,
    REGISTRATION_CONFIGURATION_ERROR,
    REGISTRATION_CONFLICT,
    REGISTRATION_DISABLED,
    USER_NOT_FOUND,
)
from db.init_db import get_db
from db.provision_company_defaults import provision_company_defaults
from core.auth_rate_limit import (
    enforce_login_rate_limit,
    enforce_refresh_rate_limit,
)
from core.auth_sessions import (
    create_auth_session,
    revoke_auth_session,
    revoke_user_authentication,
    rotate_refresh_session,
)
from core.auth_tokens import (
    create_token_pair,
    decode_token,
    is_token_stale_for_user,
)
from core.registration_security import enforce_registration_rate_limit
from deps import (
    AuthContext,
    get_current_auth_context,
    get_current_user,
    require_permission,
)
from schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    RegisterRequest,
    RegisterResponse,
    RefreshRequest,
    RefreshResponse,
    CurrentUserOut,
)
from settings import get_settings


router = APIRouter()
settings = get_settings()


def _error_detail(code: str, message: str):
    return {
        "code": code,
        "message": message,
    }

def _ensure_user_can_authenticate(
    user: User,
    token_data: dict | None = None,
) -> None:
    if getattr(user, "is_active", True) is False:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_error_detail(
                AUTH_REQUIRED,
                "User is inactive",
            ),
        )

    if (
        token_data is not None
        and is_token_stale_for_user(
            token_data,
            user,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_error_detail(
                INVALID_TOKEN,
                "Token is no longer valid",
            ),
        )



def _get_or_create_company_admin_role(
    db: Session,
    *,
    company_id: int,
) -> Role:
    role = (
        db.query(Role)
        .filter(
            Role.company_id == company_id,
            Role.name == TENANT_ADMIN_ROLE_NAME,
        )
        .first()
    )

    if role is None:
        role = Role(
            company_id=company_id,
            name=TENANT_ADMIN_ROLE_NAME,
            description=(
                "Company administrator role without "
                "platform-global or RBAC mutation access"
            ),
            is_active=True,
            is_system=False,
        )
        db.add(role)

    role.company_id = company_id
    role.is_active = True
    role.is_system = False

    allowed_permissions = sorted(
        (
            permission
            for permission in db.query(Permission).all()
            if is_tenant_permission_name(
                permission.name
            )
        ),
        key=lambda permission: permission.name,
    )

    if not allowed_permissions:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_error_detail(
                REGISTRATION_CONFIGURATION_ERROR,
                "Tenant administrator permissions are unavailable",
            ),
        )

    role.permissions = allowed_permissions

    db.flush()

    if (
        role.company_id != company_id
        or role.is_system is not False
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_error_detail(
                REGISTRATION_CONFIGURATION_ERROR,
                "Tenant administrator role scope is invalid",
            ),
        )

    return role


def _slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "company"


def _unique_company_slug(db: Session, base: str) -> str:
    slug = _slugify(base)
    candidate = slug
    counter = 1

    while db.query(Company).filter(Company.slug == candidate).first():
        counter += 1
        candidate = f"{slug}-{counter}"

    return candidate


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
):
    if settings.self_registration_mode != "open":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_error_detail(
                REGISTRATION_DISABLED,
                "Public registration is disabled",
            ),
        )

    enforce_registration_rate_limit(
        email=payload.email,
    )

    transaction_started = False

    try:
        existing_user = (
            db.query(User)
            .filter(
                User.username == payload.email
            )
            .first()
        )

        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_error_detail(
                    REGISTRATION_CONFLICT,
                    "An account with this email already exists",
                ),
            )

        email_prefix = payload.email.split("@")[0]
        company_name = (
            payload.company_name.strip()
            if payload.company_name
            else f"{email_prefix} workspace"
        )
        first_name = (
            payload.first_name.strip()
            if payload.first_name
            else email_prefix
        )
        last_name = (
            payload.last_name.strip()
            if payload.last_name
            else None
        )

        company = Company(
            name=company_name,
            slug=_unique_company_slug(
                db,
                company_name,
            ),
            is_active=True,
        )

        db.add(company)
        transaction_started = True
        db.flush()

        company_admin_role = (
            _get_or_create_company_admin_role(
                db,
                company_id=company.id,
            )
        )

        user = User(
            company_id=company.id,
            username=payload.email,
            First_name=first_name,
            Last_name=last_name,
            pw_hash=bcrypt.hash(
                payload.password
            ),
            role=TENANT_ADMIN_ROLE_NAME,
        )

        user.roles.append(
            company_admin_role
        )

        db.add(user)
        db.flush()

        provision_company_defaults(
            db,
            company,
            created_by_user_id=user.id,
        )

        auth_session, refresh_jti = (
            create_auth_session(
                db,
                user,
            )
        )

        access_token, refresh_token = (
            create_token_pair(
                user,
                session_id=auth_session.id,
                refresh_jti=refresh_jti,
            )
        )

        db.commit()
        db.refresh(user)

    except IntegrityError as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error_detail(
                REGISTRATION_CONFLICT,
                "Registration conflicts with an existing record",
            ),
        ) from exc

    except HTTPException:
        if transaction_started:
            db.rollback()
        raise

    except Exception:
        if transaction_started:
            db.rollback()
        raise

    return RegisterResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post(
    "/login",
    response_model=LoginResponse,
)
async def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
):
    enforce_login_rate_limit(
        username=payload.username,
    )

    user = (
        db.query(User)
        .filter(
            User.username == payload.username
        )
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_error_detail(
                AUTH_REQUIRED,
                "Incorrect username or password",
            ),
        )

    if not bcrypt.verify(
        payload.password,
        user.pw_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_error_detail(
                AUTH_REQUIRED,
                "Incorrect username or password",
            ),
        )

    _ensure_user_can_authenticate(user)

    auth_session, refresh_jti = (
        create_auth_session(
            db,
            user,
        )
    )

    access_token, refresh_token = (
        create_token_pair(
            user,
            session_id=auth_session.id,
            refresh_jti=refresh_jti,
        )
    )

    db.commit()

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post(
    "/refresh",
    response_model=RefreshResponse,
)
async def refresh_tokens(
    payload: RefreshRequest,
    db: Session = Depends(get_db),
):
    enforce_refresh_rate_limit(
        refresh_token=payload.refresh_token,
    )

    try:
        token_data = decode_token(
            payload.refresh_token,
            expected_type="refresh",
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_error_detail(
                INVALID_TOKEN,
                "Invalid refresh token",
            ),
            headers={
                "WWW-Authenticate": "Bearer",
            },
        ) from exc

    try:
        user_id = int(token_data["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_error_detail(
                INVALID_TOKEN,
                "Invalid refresh token",
            ),
            headers={
                "WWW-Authenticate": "Bearer",
            },
        ) from exc

    user = (
        db.query(User)
        .filter(
            User.id == user_id
        )
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_error_detail(
                USER_NOT_FOUND,
                "User not found",
            ),
            headers={
                "WWW-Authenticate": "Bearer",
            },
        )

    _ensure_user_can_authenticate(
        user,
        token_data,
    )

    auth_session, refresh_jti = (
        rotate_refresh_session(
            db,
            user,
            token_data,
        )
    )

    access_token, refresh_token = (
        create_token_pair(
            user,
            session_id=auth_session.id,
            refresh_jti=refresh_jti,
        )
    )

    db.commit()

    return RefreshResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post(
    "/logout",
    response_model=LogoutResponse,
)
def logout(
    auth_context: AuthContext = Depends(
        get_current_auth_context
    ),
    db: Session = Depends(get_db),
):
    revoked = revoke_auth_session(
        auth_context.session,
        reason="user_logout",
    )

    db.commit()

    return LogoutResponse(
        success=True,
        revoked_sessions=1 if revoked else 0,
    )


@router.post(
    "/logout-all",
    response_model=LogoutResponse,
)
def logout_all(
    current_user: User = Depends(
        get_current_user
    ),
    db: Session = Depends(get_db),
):
    revoked_count = revoke_user_authentication(
        db,
        current_user,
        reason="user_logout_all",
    )

    db.commit()

    return LogoutResponse(
        success=True,
        revoked_sessions=revoked_count,
    )


@router.get("/me", response_model=CurrentUserOut)
def me(
    current_user: User = Depends(require_permission("profile:read")),
):
    return current_user
