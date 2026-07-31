from datetime import datetime, timedelta
import re

from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError, jwt
from passlib.hash import bcrypt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from Models import User, Company, Permission, Role
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
from core.registration_security import enforce_registration_rate_limit
from deps import require_permission
from schemas.auth import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    RefreshRequest,
    RefreshResponse,
    CurrentUserOut,
)
from settings import get_settings


router = APIRouter()
settings = get_settings()


def _token_iat() -> datetime:
    return datetime.utcnow()


def create_access_token(user: User) -> str:
    issued_at = _token_iat()
    expire = issued_at + timedelta(hours=settings.jwt_exp_hours)
    payload = {
        "sub": str(user.id),
        "company_id": user.company_id,
        "iat": int(issued_at.timestamp()),
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def create_refresh_token(user: User) -> str:
    issued_at = _token_iat()
    expire = issued_at + timedelta(days=1)
    payload = {
        "sub": str(user.id),
        "company_id": user.company_id,
        "iat": int(issued_at.timestamp()),
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def _error_detail(code: str, message: str):
    return {
        "code": code,
        "message": message,
    }


def _is_token_stale_for_user(token_data: dict, user: User) -> bool:
    password_changed_at = getattr(user, "password_changed_at", None)
    if password_changed_at is None:
        return False

    token_iat = token_data.get("iat")
    if token_iat is None:
        return True

    try:
        token_iat = int(token_iat)
    except (TypeError, ValueError):
        return True

    return token_iat < int(password_changed_at.timestamp())


def _ensure_user_can_authenticate(user: User, token_data: dict | None = None) -> None:
    if getattr(user, "is_active", True) is False:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_error_detail(AUTH_REQUIRED, "User is inactive"),
        )

    if token_data is not None and _is_token_stale_for_user(token_data, user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_error_detail(INVALID_TOKEN, "Token is no longer valid"),
        )



TENANT_ADMIN_ROLE_NAME = "company_admin"

_TENANT_ADMIN_PERMISSION_PREFIXES = (
    "assistant:",
    "business_management:",
    "chat:",
    "comments:",
    "company:",
    "documents:",
    "financial_management:",
    "goods_receipt_management:",
    "material_management:",
    "models:",
    "organization:",
    "profile:",
    "property_management:",
    "purchase_management:",
    "requisition_management:",
    "rfq_management:",
    "stt:",
    "supplier_management:",
    "tags:",
    "warehouse_management:",
    "workflow:",
)

_TENANT_ADMIN_PERMISSION_NAMES = frozenset(
    {
        "currencies:read",
        "exchange_rates:read",
        "permissions:read",
        "roles:read",
        "users:read",
    }
)


def _is_tenant_admin_permission(
    permission_name: str,
) -> bool:
    if permission_name in _TENANT_ADMIN_PERMISSION_NAMES:
        return True

    return permission_name.startswith(
        _TENANT_ADMIN_PERMISSION_PREFIXES
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
            if _is_tenant_admin_permission(
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
        access_token=create_access_token(
            user
        ),
        refresh_token=create_refresh_token(
            user
        ),
    )


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_error_detail(AUTH_REQUIRED, "Incorrect username or password"),
        )

    if not bcrypt.verify(payload.password, user.pw_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_error_detail(AUTH_REQUIRED, "Incorrect username or password"),
        )

    _ensure_user_can_authenticate(user)

    return LoginResponse(
        access_token=create_access_token(user),
        refresh_token=create_refresh_token(user),
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_tokens(payload: RefreshRequest, db: Session = Depends(get_db)):
    try:
        token_data = jwt.decode(
            payload.refresh_token,
            settings.jwt_secret,
            algorithms=["HS256"],
        )

        if token_data.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=_error_detail(INVALID_TOKEN, "Invalid refresh token type"),
            )

        user_id = token_data.get("sub")

        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=_error_detail(INVALID_TOKEN, "Invalid refresh token"),
            )

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_error_detail(INVALID_TOKEN, "Invalid refresh token"),
        )

    user = db.query(User).filter(User.id == int(user_id)).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_error_detail(USER_NOT_FOUND, "User not found"),
        )

    _ensure_user_can_authenticate(user, token_data)

    return RefreshResponse(
        access_token=create_access_token(user),
        refresh_token=create_refresh_token(user),
    )


@router.get("/me", response_model=CurrentUserOut)
def me(
    current_user: User = Depends(require_permission("profile:read")),
):
    return current_user
