from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError, jwt
from passlib.hash import bcrypt
from sqlalchemy.orm import Session

from Models import User
from db.init_db import get_db
from deps import require_permission
from schemas.auth import LoginRequest, LoginResponse, RefreshRequest, RefreshResponse, CurrentUserOut
from settings import get_settings


router = APIRouter()
settings = get_settings()


def create_access_token(user: User) -> str:
    expire = datetime.utcnow() + timedelta(hours=settings.jwt_exp_hours)
    payload = {
        "sub": str(user.id),
        "company_id": user.company_id,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def create_refresh_token(user: User) -> str:
    expire = datetime.utcnow() + timedelta(days=1)
    payload = {
        "sub": str(user.id),
        "company_id": user.company_id,
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")




@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    if not bcrypt.verify(payload.password, user.pw_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

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
                detail="Invalid refresh token type",
            )

        user_id = token_data.get("sub")

        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    user = db.query(User).filter(User.id == int(user_id)).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return RefreshResponse(
        access_token=create_access_token(user),
        refresh_token=create_refresh_token(user),
    )



@router.get("/me", response_model=CurrentUserOut)
def me(
    current_user: User = Depends(require_permission("profile:read")),
):
    return current_user