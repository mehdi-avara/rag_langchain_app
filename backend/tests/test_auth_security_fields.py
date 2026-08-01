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
os.environ.setdefault(
    "default_password",
    "admin123456",
)
os.environ.setdefault(
    "default_firstname",
    "Admin",
)
os.environ.setdefault(
    "jwt_secret",
    "test-secret",
)
os.environ.setdefault(
    "openai_api_key",
    "test",
)
os.environ.setdefault(
    "jina_api_key",
    "test",
)
os.environ.setdefault(
    "AUTH_RATE_LIMIT_ENABLED",
    "false",
)

from Models import AuthSession, User
from deps import get_current_user
from routs import auth
from schemas.auth import (
    LoginRequest,
    RefreshRequest,
)


class FakeQuery:
    def __init__(
        self,
        db,
        model,
    ):
        self.db = db
        self.model = model

    def filter(
        self,
        *_args,
        **_kwargs,
    ):
        return self

    def with_for_update(self):
        return self

    def first(self):
        if self.model is User:
            return self.db.user

        if self.model is AuthSession:
            return (
                self.db.sessions[0]
                if self.db.sessions
                else None
            )

        return None


class FakeDB:
    def __init__(
        self,
        user,
    ):
        self.user = user
        self.sessions = []
        self.committed = False

    def query(
        self,
        model,
    ):
        return FakeQuery(
            self,
            model,
        )

    def add(
        self,
        obj,
    ):
        if isinstance(
            obj,
            AuthSession,
        ):
            self.sessions.append(obj)

    def flush(self):
        return None

    def commit(self):
        self.committed = True


def make_user(
    user_id=1,
    active=True,
    password="secret123",
    password_changed_at=None,
):
    return SimpleNamespace(
        id=user_id,
        company_id=1,
        username="user@example.com",
        pw_hash=bcrypt.hash(password),
        is_active=active,
        password_changed_at=password_changed_at,
        auth_token_version=0,
        roles=[],
    )


def issue_token_pair(
    db,
    user,
):
    session, refresh_jti = (
        auth.create_auth_session(
            db,
            user,
        )
    )

    access_token, refresh_token = (
        auth.create_token_pair(
            user,
            session_id=session.id,
            refresh_jti=refresh_jti,
        )
    )

    return (
        access_token,
        refresh_token,
    )


@pytest.mark.asyncio
async def test_inactive_user_cannot_login(
    monkeypatch,
):
    monkeypatch.setattr(
        auth,
        "enforce_login_rate_limit",
        lambda **_kwargs: None,
    )

    user = make_user(
        active=False,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        await auth.login(
            LoginRequest(
                username=user.username,
                password="secret123",
            ),
            db=FakeDB(user),
        )

    assert exc.value.status_code == 401
    assert (
        exc.value.detail["code"]
        == "AUTH_REQUIRED"
    )


@pytest.mark.asyncio
async def test_inactive_user_cannot_refresh(
    monkeypatch,
):
    monkeypatch.setattr(
        auth,
        "enforce_refresh_rate_limit",
        lambda **_kwargs: None,
    )

    user = make_user(
        active=False,
    )
    db = FakeDB(user)

    _, refresh_token = issue_token_pair(
        db,
        user,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        await auth.refresh_tokens(
            RefreshRequest(
                refresh_token=refresh_token
            ),
            db=db,
        )

    assert exc.value.status_code == 401
    assert (
        exc.value.detail["code"]
        == "AUTH_REQUIRED"
    )


@pytest.mark.asyncio
async def test_refresh_token_before_password_change_is_rejected(
    monkeypatch,
):
    monkeypatch.setattr(
        auth,
        "enforce_refresh_rate_limit",
        lambda **_kwargs: None,
    )

    user = make_user()
    db = FakeDB(user)

    _, refresh_token = issue_token_pair(
        db,
        user,
    )

    user.password_changed_at = (
        datetime.utcnow()
        + timedelta(seconds=5)
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        await auth.refresh_tokens(
            RefreshRequest(
                refresh_token=refresh_token
            ),
            db=db,
        )

    assert exc.value.status_code == 401
    assert (
        exc.value.detail["code"]
        == "INVALID_TOKEN"
    )


def test_access_token_before_password_change_is_rejected():
    user = make_user()
    db = FakeDB(user)

    access_token, _ = issue_token_pair(
        db,
        user,
    )

    user.password_changed_at = (
        datetime.utcnow()
        + timedelta(seconds=5)
    )

    credentials = SimpleNamespace(
        credentials=access_token
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        get_current_user(
            credentials=credentials,
            db=db,
        )

    assert exc.value.status_code == 401
    assert (
        exc.value.detail["code"]
        == "INVALID_TOKEN"
    )


def test_create_access_token_has_required_claims():
    user = make_user()
    db = FakeDB(user)

    access_token, _ = issue_token_pair(
        db,
        user,
    )

    payload = jwt.decode(
        access_token,
        auth.settings.jwt_secret,
        algorithms=["HS256"],
        audience=auth.settings.jwt_audience,
        issuer=auth.settings.jwt_issuer,
    )

    assert payload["type"] == "access"
    assert payload["sub"] == str(user.id)
    assert payload["company_id"] == user.company_id
    assert payload["ver"] == 0
    assert isinstance(
        payload["iat"],
        int,
    )
    assert len(payload["sid"]) == 32
    assert len(payload["jti"]) == 32
