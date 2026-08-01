import os
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
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
os.environ.setdefault("AUTH_RATE_LIMIT_ENABLED", "false")

from Models import AuthSession, User
from core.auth_sessions import (
    create_auth_session,
    hash_refresh_jti,
)
from core.auth_tokens import (
    create_token_pair,
    decode_token,
)
from deps import AuthContext, get_current_user
from routs import auth, rbac, users
from schemas.auth import LoginRequest, RefreshRequest
from schemas.users import (
    AdminUserPasswordReset,
    ChangePasswordIn,
)


class FakeQuery:
    def __init__(self, db, model):
        self.db = db
        self.model = model

    def filter(self, *_args, **_kwargs):
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

    def all(self):
        if self.model is AuthSession:
            return list(self.db.sessions)

        if self.model is User:
            return (
                [self.db.user]
                if self.db.user is not None
                else []
            )

        return []


class FakeDB:
    def __init__(self, user=None):
        self.user = user
        self.sessions = []
        self.commit_count = 0

    def query(self, model):
        return FakeQuery(self, model)

    def add(self, obj):
        if isinstance(obj, AuthSession):
            self.sessions.append(obj)

    def flush(self):
        return None

    def commit(self):
        self.commit_count += 1

    def refresh(self, _obj):
        return None


def make_user(
    *,
    user_id=1,
    company_id=1,
    username="user@example.com",
    password="StrongPass123",
    active=True,
):
    return SimpleNamespace(
        id=user_id,
        company_id=company_id,
        username=username,
        pw_hash=bcrypt.hash(password),
        is_active=active,
        password_changed_at=None,
        auth_token_version=0,
        roles=[],
        role="user",
        First_name="Test",
        Last_name="User",
        created_at=datetime.utcnow(),
        deactivated_at=None,
        notification_token=None,
        image_path=None,
        profile_asset_id=None,
    )


def issue_token_pair(db, user):
    session, refresh_jti = create_auth_session(
        db,
        user,
    )

    access_token, refresh_token = create_token_pair(
        user,
        session_id=session.id,
        refresh_jti=refresh_jti,
    )

    return session, access_token, refresh_token


@pytest.mark.asyncio
async def test_login_creates_persistent_auth_session(
    monkeypatch,
):
    monkeypatch.setattr(
        auth,
        "enforce_login_rate_limit",
        lambda **_kwargs: None,
    )

    user = make_user()
    db = FakeDB(user)

    response = await auth.login(
        LoginRequest(
            username=user.username,
            password="StrongPass123",
        ),
        db=db,
    )

    assert len(db.sessions) == 1
    assert db.commit_count == 1

    session = db.sessions[0]

    access_payload = decode_token(
        response.access_token,
        expected_type="access",
    )
    refresh_payload = decode_token(
        response.refresh_token,
        expected_type="refresh",
    )

    assert access_payload["sid"] == session.id
    assert refresh_payload["sid"] == session.id
    assert access_payload["sub"] == str(user.id)
    assert refresh_payload["sub"] == str(user.id)
    assert access_payload["ver"] == 0
    assert refresh_payload["ver"] == 0


@pytest.mark.asyncio
async def test_refresh_rotates_jti_and_reuse_revokes_session(
    monkeypatch,
):
    monkeypatch.setattr(
        auth,
        "enforce_refresh_rate_limit",
        lambda **_kwargs: None,
    )

    user = make_user()
    db = FakeDB(user)

    session, _, old_refresh_token = issue_token_pair(
        db,
        user,
    )

    old_payload = decode_token(
        old_refresh_token,
        expected_type="refresh",
    )
    old_jti = old_payload["jti"]

    response = await auth.refresh_tokens(
        RefreshRequest(
            refresh_token=old_refresh_token,
        ),
        db=db,
    )

    new_payload = decode_token(
        response.refresh_token,
        expected_type="refresh",
    )

    assert new_payload["sid"] == session.id
    assert new_payload["jti"] != old_jti
    assert (
        session.refresh_jti_hash
        == hash_refresh_jti(new_payload["jti"])
    )
    assert session.revoked_at is None

    with pytest.raises(HTTPException) as exc:
        await auth.refresh_tokens(
            RefreshRequest(
                refresh_token=old_refresh_token,
            ),
            db=db,
        )

    assert exc.value.status_code == 401
    assert (
        exc.value.detail["code"]
        == "REFRESH_TOKEN_REUSED"
    )
    assert session.revoked_at is not None
    assert (
        session.revoked_reason
        == "refresh_reuse_detected"
    )


def test_logout_revokes_only_current_session():
    user = make_user()
    db = FakeDB(user)

    session, access_token, _ = issue_token_pair(
        db,
        user,
    )

    payload = decode_token(
        access_token,
        expected_type="access",
    )

    context = AuthContext(
        user=user,
        session=session,
        payload=payload,
    )

    response = auth.logout(
        auth_context=context,
        db=db,
    )

    assert response.success is True
    assert response.revoked_sessions == 1
    assert session.revoked_at is not None
    assert session.revoked_reason == "user_logout"

    second_response = auth.logout(
        auth_context=context,
        db=db,
    )

    assert second_response.revoked_sessions == 0


def test_logout_all_revokes_sessions_and_bumps_version():
    user = make_user()
    db = FakeDB(user)

    first_session, _, _ = issue_token_pair(
        db,
        user,
    )
    second_session, _, _ = issue_token_pair(
        db,
        user,
    )

    response = auth.logout_all(
        current_user=user,
        db=db,
    )

    assert response.success is True
    assert response.revoked_sessions == 2
    assert user.auth_token_version == 1

    assert first_session.revoked_at is not None
    assert second_session.revoked_at is not None

    assert first_session.revoked_reason == "user_logout_all"
    assert second_session.revoked_reason == "user_logout_all"


def test_access_validation_rejects_revoked_session():
    user = make_user()
    db = FakeDB(user)

    session, access_token, _ = issue_token_pair(
        db,
        user,
    )

    credentials = SimpleNamespace(
        credentials=access_token,
    )

    resolved_user = get_current_user(
        credentials=credentials,
        db=db,
    )

    assert resolved_user is user

    session.revoked_at = datetime.utcnow()
    session.revoked_reason = "test_revocation"

    with pytest.raises(HTTPException) as exc:
        get_current_user(
            credentials=credentials,
            db=db,
        )

    assert exc.value.status_code == 401
    assert (
        exc.value.detail["code"]
        == "AUTH_SESSION_REVOKED"
    )


def test_change_password_revokes_all_sessions():
    user = make_user()
    db = FakeDB(user)

    session, _, _ = issue_token_pair(
        db,
        user,
    )

    response = users.change_password(
        payload=ChangePasswordIn(
            current_password="StrongPass123",
            new_password="NewStrongPass456",
        ),
        current_user=user,
        db=db,
    )

    assert response.success is True
    assert bcrypt.verify(
        "NewStrongPass456",
        user.pw_hash,
    )
    assert user.password_changed_at is not None
    assert user.auth_token_version == 1
    assert session.revoked_at is not None
    assert session.revoked_reason == "password_changed"


def test_admin_password_reset_revokes_all_sessions(
    monkeypatch,
):
    target = make_user(
        user_id=2,
        username="target@example.com",
    )
    admin = make_user(
        user_id=1,
        username="admin@example.com",
    )
    db = FakeDB(target)

    session, _, _ = issue_token_pair(
        db,
        target,
    )

    monkeypatch.setattr(
        rbac,
        "_admin_user_out",
        lambda user: SimpleNamespace(
            id=user.id,
        ),
    )

    result = rbac.reset_company_user_password(
        user_id=target.id,
        payload=AdminUserPasswordReset(
            new_password="ResetStrongPass789",
        ),
        db=db,
        current_user=admin,
    )

    assert result.id == target.id
    assert target.password_changed_at is not None
    assert target.auth_token_version == 1
    assert session.revoked_at is not None
    assert (
        session.revoked_reason
        == "admin_password_reset"
    )


def test_deactivation_revokes_all_sessions(
    monkeypatch,
):
    target = make_user(
        user_id=2,
        username="target@example.com",
    )
    admin = make_user(
        user_id=1,
        username="admin@example.com",
    )
    db = FakeDB(target)

    session, _, _ = issue_token_pair(
        db,
        target,
    )

    monkeypatch.setattr(
        rbac,
        "_ensure_not_last_active_admin",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        rbac,
        "_admin_user_out",
        lambda user: SimpleNamespace(
            id=user.id,
        ),
    )

    result = rbac.deactivate_company_user(
        user_id=target.id,
        db=db,
        current_user=admin,
    )

    assert result.id == target.id
    assert target.is_active is False
    assert target.deactivated_at is not None
    assert target.auth_token_version == 1
    assert session.revoked_at is not None
    assert session.revoked_reason == "user_deactivated"
