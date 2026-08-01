from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)
from jose import JWTError
from jose.exceptions import ExpiredSignatureError
from sqlalchemy.orm import Session

from Models import AuthSession, User
from core.auth_sessions import (
    validate_access_session,
)
from core.auth_tokens import (
    decode_token,
    is_token_stale_for_user,
)
from core.exceptions.error_codes import (
    AUTH_REQUIRED,
    INVALID_TOKEN,
    PLATFORM_PERMISSION_REQUIRED,
)
from db.init_db import get_db
from settings import get_settings


settings = get_settings()
security = HTTPBearer()


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: AuthSession
    payload: dict


def _credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={
            "WWW-Authenticate": "Bearer",
        },
    )


def _resolve_auth_context(
    *,
    credentials: HTTPAuthorizationCredentials,
    db: Session,
) -> AuthContext:
    try:
        payload = decode_token(
            credentials.credentials,
            expected_type="access",
        )
    except ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={
                "WWW-Authenticate": "Bearer",
            },
        ) from exc
    except JWTError as exc:
        raise _credentials_exception() from exc

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise _credentials_exception() from exc

    user = (
        db.query(User)
        .filter(
            User.id == user_id
        )
        .first()
    )

    if user is None:
        raise _credentials_exception()

    if getattr(user, "is_active", True) is False:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": AUTH_REQUIRED,
                "message": "User is inactive",
            },
            headers={
                "WWW-Authenticate": "Bearer",
            },
        )

    if is_token_stale_for_user(
        payload,
        user,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": INVALID_TOKEN,
                "message": "Token is no longer valid",
            },
            headers={
                "WWW-Authenticate": "Bearer",
            },
        )

    session = validate_access_session(
        db,
        user,
        payload,
    )

    return AuthContext(
        user=user,
        session=session,
        payload=payload,
    )


def get_current_auth_context(
    credentials: HTTPAuthorizationCredentials = Depends(
        security
    ),
    db: Session = Depends(get_db),
) -> AuthContext:
    return _resolve_auth_context(
        credentials=credentials,
        db=db,
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(
        security
    ),
    db: Session = Depends(get_db),
) -> User:
    return _resolve_auth_context(
        credentials=credentials,
        db=db,
    ).user


def get_user_permissions(current_user: User) -> set[str]:
    return {
        permission.name
        for role in current_user.roles
        if role.is_active
        for permission in role.permissions
    }


def require_permission(permission_name: str):
    def checker(current_user: User = Depends(get_current_user)) -> User:
        permissions = get_user_permissions(current_user)

        if permission_name not in permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied",
            )

        return current_user

    return checker


def get_platform_permissions(
    current_user: User,
) -> set[str]:
    return {
        permission.name
        for role in current_user.roles
        if role.is_active
        and role.is_system is True
        and role.company_id is None
        for permission in role.permissions
    }


def require_platform_permission(
    permission_name: str,
):
    def checker(
        current_user: User = Depends(
            get_current_user
        ),
    ) -> User:
        permissions = get_platform_permissions(
            current_user
        )

        if permission_name not in permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": PLATFORM_PERMISSION_REQUIRED,
                    "message": (
                        "Platform-level permission is required"
                    ),
                },
            )

        return current_user

    return checker


def require_permissions(*permission_names: str):
    def checker(current_user: User = Depends(get_current_user)) -> User:
        permissions = get_user_permissions(current_user)

        missing_permissions = [
            permission_name
            for permission_name in permission_names
            if permission_name not in permissions
        ]

        if missing_permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied",
            )

        return current_user

    return checker


def require_role(role_name: str):
    def checker(current_user: User = Depends(get_current_user)) -> User:
        roles = {role.name for role in current_user.roles if role.is_active}

        if role_name not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Role denied",
            )

        return current_user

    return checker