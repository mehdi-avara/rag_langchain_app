import os
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from jose import JWTError

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
    "S3_ACCESS_KEY_ID",
    "test",
)
os.environ.setdefault(
    "S3_SECRET_ACCESS_KEY",
    "test",
)

from core import auth_rate_limit
from core.auth_sessions import (
    bump_user_auth_token_version,
    create_auth_session,
    hash_refresh_jti,
    revoke_auth_session,
)
from core.auth_tokens import (
    create_token_pair,
    decode_token,
    is_token_stale_for_user,
)


class FakeDB:
    def __init__(self):
        self.added = []
        self.flushed = False

    def add(self, value):
        self.added.append(value)

    def flush(self):
        self.flushed = True


def make_user():
    return SimpleNamespace(
        id=7,
        company_id=3,
        auth_token_version=0,
        password_changed_at=None,
    )


def test_session_and_token_pair_contract():
    db = FakeDB()
    user = make_user()

    session, refresh_jti = (
        create_auth_session(
            db,
            user,
        )
    )

    access_token, refresh_token = (
        create_token_pair(
            user,
            session_id=session.id,
            refresh_jti=refresh_jti,
        )
    )

    access_payload = decode_token(
        access_token,
        expected_type="access",
    )
    refresh_payload = decode_token(
        refresh_token,
        expected_type="refresh",
    )

    assert db.flushed is True
    assert db.added == [session]

    assert access_payload["sub"] == "7"
    assert access_payload["company_id"] == 3
    assert access_payload["sid"] == session.id
    assert access_payload["ver"] == 0
    assert access_payload["type"] == "access"

    assert refresh_payload["sub"] == "7"
    assert refresh_payload["company_id"] == 3
    assert refresh_payload["sid"] == session.id
    assert refresh_payload["jti"] == refresh_jti
    assert refresh_payload["ver"] == 0
    assert refresh_payload["type"] == "refresh"

    assert (
        access_payload["jti"]
        != refresh_payload["jti"]
    )

    assert session.refresh_jti_hash == (
        hash_refresh_jti(
            refresh_jti
        )
    )


def test_access_token_cannot_be_decoded_as_refresh():
    db = FakeDB()
    user = make_user()

    session, refresh_jti = (
        create_auth_session(
            db,
            user,
        )
    )

    access_token, _ = create_token_pair(
        user,
        session_id=session.id,
        refresh_jti=refresh_jti,
    )

    with pytest.raises(JWTError):
        decode_token(
            access_token,
            expected_type="refresh",
        )


def test_token_version_can_be_bumped():
    user = make_user()

    assert (
        bump_user_auth_token_version(
            user
        )
        == 1
    )
    assert user.auth_token_version == 1

    assert (
        bump_user_auth_token_version(
            user
        )
        == 2
    )
    assert user.auth_token_version == 2


def test_session_revocation_is_idempotent():
    db = FakeDB()
    user = make_user()

    session, _ = create_auth_session(
        db,
        user,
    )

    assert revoke_auth_session(
        session,
        reason="logout",
    ) is True

    first_revoked_at = session.revoked_at

    assert revoke_auth_session(
        session,
        reason="logout",
    ) is False

    assert session.revoked_at == first_revoked_at
    assert session.revoked_reason == "logout"


def test_password_change_staleness_contract():
    user = make_user()
    user.password_changed_at = (
        datetime.utcnow()
        + timedelta(seconds=5)
    )

    payload = {
        "iat": int(
            datetime.utcnow().timestamp()
        )
    }

    assert (
        is_token_stale_for_user(
            payload,
            user,
        )
        is True
    )


def test_disabled_rate_limiter_does_not_use_redis(
    monkeypatch,
):
    monkeypatch.setattr(
        auth_rate_limit.settings,
        "auth_rate_limit_enabled",
        False,
    )

    auth_rate_limit.enforce_login_rate_limit(
        username="user@example.com"
    )


def test_invalid_rate_policy_fails_closed(
    monkeypatch,
):
    monkeypatch.setattr(
        auth_rate_limit.settings,
        "auth_rate_limit_enabled",
        True,
    )
    monkeypatch.setattr(
        auth_rate_limit.settings,
        "auth_login_rate_window_seconds",
        0,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        auth_rate_limit.enforce_login_rate_limit(
            username="user@example.com"
        )

    assert exc.value.status_code == 503
    assert (
        exc.value.detail["code"]
        == "AUTH_CONFIGURATION_ERROR"
    )


def test_migration_contract():
    migration = (
        Path(__file__)
        .resolve()
        .parents[1]
        / "alembic"
        / "versions"
        / (
            "24d1b2c3e4f5_"
            "add_auth_session_foundation.py"
        )
    )

    source = migration.read_text(
        encoding="utf-8",
    )

    assert (
        'revision: str = "24d1b2c3e4f5"'
        in source
    )
    assert (
        '"13c0a1b2d3e4"'
        in source
    )
    assert (
        '"auth_sessions"'
        in source
    )
    assert (
        '"auth_token_version"'
        in source
    )
