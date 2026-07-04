import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from jose import jwt
from passlib.hash import bcrypt

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_IP", "localhost")
os.environ.setdefault("default_username", "admin")
os.environ.setdefault("default_password", "admin123456")
os.environ.setdefault("default_firstname", "Admin")
os.environ.setdefault("jwt_secret", "test-secret")
os.environ.setdefault("openai_api_key", "test")
os.environ.setdefault("jina_api_key", "test")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from Models import Company, Permission, Role, User
from deps import require_permission
from routs.auth import (
    create_access_token,
    create_refresh_token,
    login,
    refresh_tokens,
    register,
)
from schemas.auth import LoginRequest, RefreshRequest, RegisterRequest
from settings import get_settings


class FakeQuery:
    def __init__(self, db, model):
        self.db = db
        self.model = model

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        if self.model is User:
            return self.db.users[0] if self.db.users else None

        if self.model is Company:
            if self.db.company_slug_exists:
                return self.db.companies[0] if self.db.companies else Company(id=999, name="Existing", slug="existing")
            return None

        if self.model is Role:
            return self.db.roles[0] if self.db.roles else None

        return None

    def all(self):
        return []


class FakeDB:
    def __init__(self, users=None, companies=None, roles=None, company_slug_exists=False):
        self.users = users or []
        self.companies = companies or []
        self.roles = roles or []
        self.company_slug_exists = company_slug_exists
        self.added = []
        self.committed = False
        self.flushed = False
        self.refreshed = []

    def query(self, model):
        return FakeQuery(self, model)

    def add(self, obj):
        self.added.append(obj)

        if isinstance(obj, Company):
            self.companies.append(obj)

        if isinstance(obj, User):
            self.users.append(obj)

    def flush(self):
        self.flushed = True

        for index, company in enumerate(self.companies, start=1):
            if company.id is None:
                company.id = index

        for index, user in enumerate(self.users, start=1):
            if user.id is None:
                user.id = index

    def commit(self):
        self.committed = True

        for index, company in enumerate(self.companies, start=1):
            if company.id is None:
                company.id = index

        for index, user in enumerate(self.users, start=1):
            if user.id is None:
                user.id = index

    def refresh(self, obj):
        self.refreshed.append(obj)


def decode_token(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])


def make_user(
    user_id=1,
    company_id=1,
    username="user@example.com",
    password="StrongPass123",
    role="user",
    permissions=None,
):
    user = User(
        id=user_id,
        company_id=company_id,
        username=username,
        First_name="Test",
        Last_name="User",
        pw_hash=bcrypt.hash(password),
        role=role,
    )

    role_obj = Role(id=1, name=role, is_active=True)
    role_obj.permissions = [
        Permission(id=i + 1, name=permission, resource="test", action="read")
        for i, permission in enumerate(permissions or [])
    ]
    user.roles = [role_obj]

    return user


@pytest.mark.asyncio
async def test_register_creates_company_admin_user_and_tokens():
    admin_role = Role(id=1, name="admin", is_active=True)
    db = FakeDB(roles=[admin_role])

    response = await register(
        RegisterRequest(
            email="Owner@Example.com",
            password="StrongPass123",
            first_name="Owner",
            last_name="Main",
            company_name="Acme Company",
        ),
        db=db,
    )

    assert db.flushed is True
    assert db.committed is True
    assert len(db.companies) == 1
    assert len(db.users) == 1

    company = db.companies[0]
    user = db.users[0]

    assert company.name == "Acme Company"
    assert company.slug == "acme-company"
    assert company.is_active is True

    assert user.company_id == company.id
    assert user.username == "owner@example.com"
    assert user.First_name == "Owner"
    assert user.Last_name == "Main"
    assert user.role == "admin"
    assert user.roles == [admin_role]
    assert bcrypt.verify("StrongPass123", user.pw_hash)

    access_payload = decode_token(response.access_token)
    refresh_payload = decode_token(response.refresh_token)

    assert access_payload["sub"] == str(user.id)
    assert access_payload["company_id"] == company.id
    assert access_payload["type"] == "access"

    assert refresh_payload["sub"] == str(user.id)
    assert refresh_payload["company_id"] == company.id
    assert refresh_payload["type"] == "refresh"


@pytest.mark.asyncio
async def test_register_rejects_duplicate_email():
    existing_user = make_user(username="owner@example.com")
    db = FakeDB(users=[existing_user])

    with pytest.raises(HTTPException) as exc:
        await register(
            RegisterRequest(
                email="owner@example.com",
                password="StrongPass123",
                company_name="Acme Company",
            ),
            db=db,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Email already registered"


@pytest.mark.asyncio
async def test_login_returns_access_and_refresh_tokens():
    user = make_user(
        user_id=7,
        company_id=3,
        username="user@example.com",
        password="StrongPass123",
    )
    db = FakeDB(users=[user])

    response = await login(
        LoginRequest(username="user@example.com", password="StrongPass123"),
        db=db,
    )

    access_payload = decode_token(response.access_token)
    refresh_payload = decode_token(response.refresh_token)

    assert access_payload["sub"] == "7"
    assert access_payload["company_id"] == 3
    assert access_payload["type"] == "access"

    assert refresh_payload["sub"] == "7"
    assert refresh_payload["company_id"] == 3
    assert refresh_payload["type"] == "refresh"


@pytest.mark.asyncio
async def test_login_rejects_wrong_password():
    user = make_user(password="StrongPass123")
    db = FakeDB(users=[user])

    with pytest.raises(HTTPException) as exc:
        await login(
            LoginRequest(username="user@example.com", password="WrongPassword123"),
            db=db,
        )

    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "AUTH_REQUIRED"
    assert exc.value.detail["message"] == "Incorrect username or password"


@pytest.mark.asyncio
async def test_login_rejects_unknown_user():
    db = FakeDB(users=[])

    with pytest.raises(HTTPException) as exc:
        await login(
            LoginRequest(username="missing@example.com", password="StrongPass123"),
            db=db,
        )

    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "AUTH_REQUIRED"
    assert exc.value.detail["message"] == "Incorrect username or password"


@pytest.mark.asyncio
async def test_refresh_accepts_refresh_token_and_returns_new_tokens():
    user = make_user(user_id=9, company_id=4)
    db = FakeDB(users=[user])
    refresh_token = create_refresh_token(user)

    response = await refresh_tokens(
        RefreshRequest(refresh_token=refresh_token),
        db=db,
    )

    access_payload = decode_token(response.access_token)
    refresh_payload = decode_token(response.refresh_token)

    assert access_payload["sub"] == "9"
    assert access_payload["company_id"] == 4
    assert access_payload["type"] == "access"

    assert refresh_payload["sub"] == "9"
    assert refresh_payload["company_id"] == 4
    assert refresh_payload["type"] == "refresh"


@pytest.mark.asyncio
async def test_refresh_rejects_access_token():
    user = make_user(user_id=9, company_id=4)
    db = FakeDB(users=[user])
    access_token = create_access_token(user)

    with pytest.raises(HTTPException) as exc:
        await refresh_tokens(
            RefreshRequest(refresh_token=access_token),
            db=db,
        )

    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_refresh_rejects_invalid_token():
    db = FakeDB(users=[])

    with pytest.raises(HTTPException) as exc:
        await refresh_tokens(
            RefreshRequest(refresh_token="not-a-valid-token"),
            db=db,
        )

    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "INVALID_TOKEN"


def test_require_permission_allows_user_with_permission():
    user = make_user(permissions=["profile:read"])
    checker = require_permission("profile:read")

    assert checker(user) is user


def test_require_permission_rejects_user_without_permission():
    user = make_user(permissions=[])
    checker = require_permission("profile:read")

    with pytest.raises(HTTPException) as exc:
        checker(user)

    assert exc.value.status_code == 403
    assert exc.value.detail == "Permission denied"


def test_require_permission_ignores_inactive_roles():
    user = make_user(permissions=["profile:read"])
    user.roles[0].is_active = False

    checker = require_permission("profile:read")

    with pytest.raises(HTTPException) as exc:
        checker(user)

    assert exc.value.status_code == 403
    assert exc.value.detail == "Permission denied"
