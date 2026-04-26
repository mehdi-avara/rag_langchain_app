from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError
from sqlalchemy.orm import Session

from Models import User
from db.init_db import get_db
from settings import get_settings


settings = get_settings()
security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        token = credentials.credentials
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        user_id = payload.get("sub")
        token_type = payload.get("type")

        if user_id is None or token_type != "access":
            raise credentials_exception

    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    except JWTError:
        raise credentials_exception

    try:
        user_id_int = int(user_id)
    except ValueError:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id_int).first()

    if user is None:
        raise credentials_exception

    return user


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