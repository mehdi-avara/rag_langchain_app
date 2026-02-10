from schemas.auth import LoginRequest, LoginResponse, RefreshRequest, RefreshResponse
from fastapi import APIRouter
from passlib.hash import bcrypt  
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException, status
from datetime import datetime, timedelta

from db.init_db import get_db
from Models import User
from jose import JWTError, jwt
from settings import get_settings

def create_access_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(hours=settings.jwt_exp_hours)
    to_encode = {"sub": str(user_id), "exp": expire, "type": "access"}
    return jwt.encode(to_encode, settings.jwt_secret, algorithm="HS256")

def create_refresh_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(days=1)
    to_encode = {"sub": str(user_id), "exp": expire, "type": "refresh"}
    return jwt.encode(to_encode, settings.jwt_secret, algorithm="HS256")


router = APIRouter()
settings = get_settings()

# Auth routes
@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, db: Session = Depends(get_db)):
    username = payload.username
    password = payload.password
    user = db.query(User).filter(User.username == username).first()
    if not user:  # In production, use proper password hashing
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    if not bcrypt.verify(password, user.pw_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    return {
        "access_token": create_access_token(user.id),
        "refresh_token": create_refresh_token(user.id),
    }


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_tokens(payload: RefreshRequest, db: Session = Depends(get_db)):
    try:
        token_data = jwt.decode(payload.refresh_token, settings.jwt_secret, algorithms=["HS256"])
        if token_data.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token type",
            )
        user_id: str = token_data.get("sub")
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

    return {
        "access_token": create_access_token(user.id),
        "refresh_token": create_refresh_token(user.id),
    }
