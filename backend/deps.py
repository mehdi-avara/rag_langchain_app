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
    db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        token = credentials.credentials

        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])

        user_id: str = payload.get("sub")
        token_type: str = payload.get("type")
        if user_id is None:
            raise credentials_exception
        if token_type != "access":
            raise credentials_exception
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        print(f"❌ No user found with ID: {user_id}")
        raise credentials_exception

    print(f"✅ Authenticated user: {user.username}")
    return user
