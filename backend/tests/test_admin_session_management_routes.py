import inspect
import os
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault(
    "POSTGRES_DB",
    "test",
)
os.environ.setdefault(
    "POSTGRES_USER",
    "test",
)
os.environ.setdefault(
    "POSTGRES_PASSWORD",
    "test",
)
os.environ.setdefault(
    "POSTGRES_IP",
    "localhost",
)
os.environ.setdefault(
    "default_username",
    "admin",
)
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

from Models import AuthSession, User
from core.authorization import (
    is_tenant_permission_name,
)
from core.auth_sessions import (
    revoke_all_auth_sessions,
)
from db import seed_rbac
from routs import rbac
from schemas.users import (
    AdminAuthSessionActionOut,
    AdminAuthSessionOut,
)


class FakeQuery:
    def __init__(
        self,
        db,
        model,
    ):
        self.db = db
        self.model = model
        self._offset = 0
        self._limit = None

    def filter(
        self,
        *_args,
        **_kwargs,
    ):
        return self

    def order_by(
        self,
        *_args,
        **_kwargs,
    ):
        return self

    def offset(
        self,
        value,
    ):
        self._offset = value
        return self

    def limit(
        self,
        value,
    ):
        self._limit = value
        return self

    def first(self):
        if self.model is User:
            return self.db.user

        if self.model is AuthSession:
            if self.db.first_session is not None:
                return self.db.first_session

            return (
                self.db.sessions[0]
                if self.db.sessions
                else None
            )

        return None

    def all(self):
        if self.model is AuthSession:
            values = list(
                self.db.sessions
            )

        elif self.model is User:
            values = (
                [self.db.user]
                if self.db.user is not None
                else []
            )

        else:
            values = []

        start = self._offset

        if self._limit is None:
            return values[start:]

        return values[
            start:start + self._limit
        ]


class FakeDB:
    def __init__(
        self,
        *,
        user=None,
        sessions=None,
        first_session=None,
    ):
        self.user = user
        self.sessions = list(
            sessions or []
        )
        self.first_session = (
            first_session
        )
        self.commit_count = 0
        self.added = []

    def add(
        self,
        value,
    ):
        self.added.append(
            value
        )

    def query(
        self,
        model,
    ):
        return FakeQuery(
            self,
            model,
        )

    def commit(self):
        self.commit_count += 1


def make_user(
    *,
    user_id=2,
    company_id=7,
):
    return SimpleNamespace(
        id=user_id,
        company_id=company_id,
        auth_token_version=0,
    )


def make_session(
    session_id,
    *,
    user_id=2,
    company_id=7,
    revoked_at=None,
    expires_at=None,
):
    now = datetime.utcnow()

    return AuthSession(
        id=session_id,
        user_id=user_id,
        company_id=company_id,
        token_version=0,
        refresh_jti_hash=(
            "a" * 64
        ),
        created_at=now,
        last_rotated_at=now,
        last_used_at=None,
        expires_at=(
            expires_at
            or (
                now
                + timedelta(days=7)
            )
        ),
        revoked_at=revoked_at,
        revoked_reason=(
            "existing_revocation"
            if revoked_at
            else None
        ),
    )


def test_session_output_contract_excludes_refresh_secret():
    fields = set(
        AdminAuthSessionOut.model_fields
    )

    assert "refresh_jti_hash" not in fields

    assert fields == {
        "id",
        "user_id",
        "company_id",
        "token_version",
        "created_at",
        "last_rotated_at",
        "last_used_at",
        "expires_at",
        "revoked_at",
        "revoked_reason",
        "is_revoked",
        "is_expired",
    }


def test_session_permissions_are_tenant_scoped():
    assert (
        is_tenant_permission_name(
            "users:sessions:read"
        )
        is True
    )

    assert (
        is_tenant_permission_name(
            "users:sessions:manage"
        )
        is True
    )

    for name in {
        "assistant:debug",
        "developer_docs:read",
        "llm:update",
    }:
        assert (
            is_tenant_permission_name(
                name
            )
            is False
        )


def test_seed_declares_session_permissions():
    source = inspect.getsource(
        seed_rbac.seed
    )

    assert (
        '"users:sessions:read"'
        in source
    )

    assert (
        '"users:sessions:manage"'
        in source
    )


def test_list_user_sessions_is_safe():
    target = make_user()

    first = make_session(
        "a" * 32
    )

    second = make_session(
        "b" * 32,
        revoked_at=datetime.utcnow(),
    )

    db = FakeDB(
        user=target,
        sessions=[
            first,
            second,
        ],
    )

    result = (
        rbac.list_company_user_sessions(
            user_id=target.id,
            revoked=None,
            offset=0,
            limit=None,
            db=db,
            current_user=make_user(
                user_id=1
            ),
        )
    )

    assert len(result) == 2

    assert all(
        isinstance(
            item,
            AdminAuthSessionOut,
        )
        for item in result
    )

    assert result[0].id == first.id
    assert result[0].is_revoked is False
    assert result[0].is_expired is False

    assert result[1].id == second.id
    assert result[1].is_revoked is True

    assert not hasattr(
        result[0],
        "refresh_jti_hash",
    )


def test_list_sessions_honors_revoked_filter_defensively():
    target = make_user()

    active = make_session(
        "a" * 32
    )

    revoked = make_session(
        "b" * 32,
        revoked_at=datetime.utcnow(),
    )

    db = FakeDB(
        user=target,
        sessions=[
            active,
            revoked,
        ],
    )

    result = (
        rbac.list_company_user_sessions(
            user_id=target.id,
            revoked=False,
            offset=0,
            limit=None,
            db=db,
            current_user=make_user(
                user_id=1
            ),
        )
    )

    assert [
        item.id
        for item in result
    ] == [
        active.id
    ]


def test_missing_target_user_is_hidden():
    db = FakeDB(
        user=None
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        rbac.list_company_user_sessions(
            user_id=99,
            revoked=None,
            offset=0,
            limit=None,
            db=db,
            current_user=make_user(
                user_id=1
            ),
        )

    assert exc.value.status_code == 404
    assert (
        exc.value.detail["code"]
        == "USER_NOT_FOUND"
    )


def test_foreign_session_is_not_revealed():
    target = make_user(
        user_id=2,
        company_id=7,
    )

    foreign_session = make_session(
        "c" * 32,
        user_id=2,
        company_id=8,
    )

    db = FakeDB(
        user=target,
        sessions=[
            foreign_session
        ],
        first_session=foreign_session,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        rbac.revoke_company_user_session(
            user_id=target.id,
            session_id=foreign_session.id,
            db=db,
            current_user=make_user(
                user_id=1,
                company_id=7,
            ),
        )

    assert exc.value.status_code == 404
    assert (
        exc.value.detail["code"]
        == "AUTH_SESSION_NOT_FOUND"
    )

    assert (
        foreign_session.revoked_at
        is None
    )

    assert db.commit_count == 0


def test_single_session_revoke_is_idempotent_and_isolated():
    target = make_user()

    selected = make_session(
        "a" * 32
    )

    other = make_session(
        "b" * 32
    )

    db = FakeDB(
        user=target,
        sessions=[
            selected,
            other,
        ],
        first_session=selected,
    )

    result = (
        rbac.revoke_company_user_session(
            user_id=target.id,
            session_id=selected.id,
            db=db,
            current_user=make_user(
                user_id=1
            ),
        )
    )

    assert isinstance(
        result,
        AdminAuthSessionActionOut,
    )

    assert result.success is True
    assert result.revoked_sessions == 1

    assert selected.revoked_at is not None
    assert (
        selected.revoked_reason
        == "admin_session_revoked"
    )

    assert other.revoked_at is None

    assert (
        target.auth_token_version
        == 0
    )

    second = (
        rbac.revoke_company_user_session(
            user_id=target.id,
            session_id=selected.id,
            db=db,
            current_user=make_user(
                user_id=1
            ),
        )
    )

    assert second.success is True
    assert second.revoked_sessions == 0

    assert (
        target.auth_token_version
        == 0
    )

    assert db.commit_count == 2


def test_revoke_all_sessions_invalidates_all_authentication():
    target = make_user()

    first = make_session(
        "a" * 32
    )

    second = make_session(
        "b" * 32
    )

    db = FakeDB(
        user=target,
        sessions=[
            first,
            second,
        ],
    )

    result = (
        rbac.revoke_all_company_user_sessions(
            user_id=target.id,
            db=db,
            current_user=make_user(
                user_id=1
            ),
        )
    )

    assert result.success is True
    assert result.revoked_sessions == 2

    assert (
        target.auth_token_version
        == 1
    )

    assert first.revoked_at is not None
    assert second.revoked_at is not None

    assert (
        first.revoked_reason
        == "admin_sessions_revoked_all"
    )

    assert (
        second.revoked_reason
        == "admin_sessions_revoked_all"
    )

    assert db.commit_count == 1


def test_session_routes_use_distinct_permissions():
    source = (
        inspect.getsource(
            rbac.list_company_user_sessions
        )
        + inspect.getsource(
            rbac.revoke_company_user_session
        )
        + inspect.getsource(
            rbac.revoke_all_company_user_sessions
        )
    )

    assert (
        "users:sessions:read"
        in source
    )

    assert (
        source.count(
            "users:sessions:manage"
        )
        == 2
    )



def test_revoke_all_service_has_tenant_boundary():
    source = inspect.getsource(
        revoke_all_auth_sessions
    )

    assert (
        "AuthSession.company_id"
        in source
    )

    assert (
        "user.company_id"
        in source
    )

    assert (
        "session.company_id"
        in source
    )
