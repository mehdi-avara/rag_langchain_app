import os
from datetime import datetime, timedelta
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

from deps import get_current_user
from routs import auth
from schemas.auth import LoginRequest, RefreshRequest


class FakeQuery:
    def __init__(self, user):
        self.user = user

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.user


class FakeDB:
    def __init__(self, user):
        self.user = user

    def query(self, _model):
        return FakeQuery(self.user)


def make_user(user_id=1, active=True, password="secret123", password_changed_at=None):
    return SimpleNamespace(
        id=user_id,
        company_id=1,
        username="user@example.com",
        pw_hash=bcrypt.hash(password),
        is_active=active,
        password_changed_at=password_changed_at,
        roles=[],
    )


@pytest.mark.asyncio
async def test_inactive_user_cannot_login():
    user = make_user(active=False)

    with pytest.raises(HTTPException) as exc:
        await auth.login(LoginRequest(username=user.username, password="secret123"), db=FakeDB(user))

    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "AUTH_REQUIRED"


@pytest.mark.asyncio
async def test_inactive_user_cannot_refresh():
    user = make_user(active=False)
    token = auth.create_refresh_token(user)

    with pytest.raises(HTTPException) as exc:
        await auth.refresh_tokens(RefreshRequest(refresh_token=token), db=FakeDB(user))

    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "AUTH_REQUIRED"


@pytest.mark.asyncio
async def test_refresh_token_before_password_change_is_rejected():
    user = make_user(password_changed_at=datetime.utcnow() + timedelta(seconds=5))
    token = auth.create_refresh_token(user)

    with pytest.raises(HTTPException) as exc:
        await auth.refresh_tokens(RefreshRequest(refresh_token=token), db=FakeDB(user))

    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "INVALID_TOKEN"


def test_access_token_before_password_change_is_rejected():
    user = make_user(password_changed_at=datetime.utcnow() + timedelta(seconds=5))
    token = auth.create_access_token(user)

    credentials = SimpleNamespace(credentials=token)

    with pytest.raises(HTTPException) as exc:
        get_current_user(credentials=credentials, db=FakeDB(user))

    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "INVALID_TOKEN"


def test_create_access_token_has_iat():
    user = make_user()
    token = auth.create_access_token(user)

    payload = jwt.decode(token, auth.settings.jwt_secret, algorithms=["HS256"])

    assert payload["type"] == "access"
    assert payload["sub"] == str(user.id)
    assert isinstance(payload["iat"], int)
