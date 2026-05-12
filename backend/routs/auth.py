from datetime import datetime, timedelta
import re

from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError, jwt
from passlib.hash import bcrypt
from sqlalchemy.orm import Session

from Models import User, Company, Role
from db.init_db import get_db
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


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.username == payload.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    email_prefix = payload.email.split("@")[0]
    company_name = payload.company_name.strip() if payload.company_name else f"{email_prefix} workspace"
    first_name = payload.first_name.strip() if payload.first_name else email_prefix
    last_name = payload.last_name.strip() if payload.last_name else None

    company = Company(
        name=company_name,
        slug=_unique_company_slug(db, company_name),
        is_active=True,
    )

    db.add(company)
    db.flush()

    user = User(
        company_id=company.id,
        username=payload.email,
        First_name=first_name,
        Last_name=last_name,
        pw_hash=bcrypt.hash(payload.password),
        role="admin",
    )

    admin_role = db.query(Role).filter(Role.name == "admin", Role.is_active.is_(True)).first()
    if admin_role:
        user.roles.append(admin_role)

    db.add(user)
    db.commit()
    db.refresh(user)

    return RegisterResponse(
        access_token=create_access_token(user),
        refresh_token=create_refresh_token(user),
    )


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
