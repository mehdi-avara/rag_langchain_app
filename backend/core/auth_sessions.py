from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from Models.auth_session import AuthSession
from core.auth_tokens import user_token_version
from core.exceptions.error_codes import (
    AUTH_SESSION_REVOKED,
    INVALID_TOKEN,
    REFRESH_TOKEN_REUSED,
)
from settings import get_settings


settings = get_settings()


def _error_detail(
    code: str,
    message: str,
) -> dict[str, str]:
    return {
        "code": code,
        "message": message,
    }


def _raise_invalid_session(
    message: str = "Authentication session is invalid",
    *,
    code: str = INVALID_TOKEN,
) -> None:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_error_detail(
            code,
            message,
        ),
        headers={
            "WWW-Authenticate": "Bearer",
        },
    )


def hash_refresh_jti(
    jti: str,
) -> str:
    return hashlib.sha256(
        jti.encode("utf-8")
    ).hexdigest()


def bump_user_auth_token_version(
    user,
) -> int:
    next_version = (
        user_token_version(user)
        + 1
    )

    user.auth_token_version = next_version

    return next_version


def create_auth_session(
    db: Session,
    user,
) -> tuple[AuthSession, str]:
    if getattr(user, "id", None) is None:
        raise RuntimeError(
            "User must be persisted before session creation"
        )

    if settings.jwt_refresh_exp_days <= 0:
        raise RuntimeError(
            "JWT refresh-token lifetime is invalid"
        )

    now = datetime.utcnow()
    refresh_jti = uuid4().hex

    session = AuthSession(
        id=uuid4().hex,
        user_id=user.id,
        company_id=user.company_id,
        token_version=user_token_version(
            user
        ),
        refresh_jti_hash=hash_refresh_jti(
            refresh_jti
        ),
        created_at=now,
        last_rotated_at=now,
        expires_at=(
            now
            + timedelta(
                days=settings.jwt_refresh_exp_days
            )
        ),
    )

    db.add(session)
    db.flush()

    return session, refresh_jti


def load_auth_session(
    db: Session,
    session_id: str,
    *,
    for_update: bool = False,
) -> AuthSession | None:
    query = db.query(
        AuthSession
    ).filter(
        AuthSession.id == session_id
    )

    if for_update:
        query = query.with_for_update()

    return query.first()


def validate_session_binding(
    session: AuthSession,
    user,
    payload: dict,
) -> None:
    now = datetime.utcnow()

    if session.revoked_at is not None:
        _raise_invalid_session(
            "Authentication session has been revoked",
            code=AUTH_SESSION_REVOKED,
        )

    if session.expires_at <= now:
        _raise_invalid_session(
            "Authentication session has expired"
        )

    if session.user_id != user.id:
        _raise_invalid_session()

    if session.company_id != user.company_id:
        _raise_invalid_session()

    if payload.get(
        "company_id"
    ) != user.company_id:
        _raise_invalid_session()

    try:
        payload_version = int(
            payload.get("ver")
        )
    except (TypeError, ValueError):
        _raise_invalid_session()
        return

    current_version = user_token_version(
        user
    )

    if payload_version != current_version:
        _raise_invalid_session(
            "Token version is no longer valid"
        )

    if session.token_version != current_version:
        _raise_invalid_session(
            "Authentication session version is invalid"
        )


def validate_access_session(
    db: Session,
    user,
    payload: dict,
) -> AuthSession:
    session_id = payload.get("sid")

    if not isinstance(
        session_id,
        str,
    ):
        _raise_invalid_session()

    session = load_auth_session(
        db,
        session_id,
    )

    if session is None:
        _raise_invalid_session()

    validate_session_binding(
        session,
        user,
        payload,
    )

    return session


def rotate_refresh_session(
    db: Session,
    user,
    payload: dict,
) -> tuple[AuthSession, str]:
    session_id = payload.get("sid")
    incoming_jti = payload.get("jti")

    if not isinstance(
        session_id,
        str,
    ):
        _raise_invalid_session()

    if not isinstance(
        incoming_jti,
        str,
    ):
        _raise_invalid_session()

    session = load_auth_session(
        db,
        session_id,
        for_update=True,
    )

    if session is None:
        _raise_invalid_session()

    validate_session_binding(
        session,
        user,
        payload,
    )

    incoming_hash = hash_refresh_jti(
        incoming_jti
    )

    if not hmac.compare_digest(
        incoming_hash,
        session.refresh_jti_hash,
    ):
        now = datetime.utcnow()

        session.revoked_at = now
        session.revoked_reason = (
            "refresh_reuse_detected"
        )
        session.last_used_at = now

        db.commit()

        _raise_invalid_session(
            "Refresh token reuse was detected",
            code=REFRESH_TOKEN_REUSED,
        )

    now = datetime.utcnow()
    next_refresh_jti = uuid4().hex

    session.refresh_jti_hash = (
        hash_refresh_jti(
            next_refresh_jti
        )
    )
    session.last_rotated_at = now
    session.last_used_at = now

    return session, next_refresh_jti


def revoke_auth_session(
    session: AuthSession,
    *,
    reason: str,
) -> bool:
    if session.revoked_at is not None:
        return False

    session.revoked_at = datetime.utcnow()
    session.revoked_reason = reason[:64]

    return True


def revoke_all_auth_sessions(
    db: Session,
    user,
    *,
    reason: str,
) -> int:
    sessions = (
        db.query(AuthSession)
        .filter(
            AuthSession.user_id == user.id,
            AuthSession.company_id
            == user.company_id,
            AuthSession.revoked_at.is_(None),
        )
        .all()
    )

    revoked_count = 0

    for session in sessions:
        if (
            session.user_id != user.id
            or session.company_id
            != user.company_id
        ):
            continue

        if revoke_auth_session(
            session,
            reason=reason,
        ):
            revoked_count += 1

    return revoked_count


def revoke_user_authentication(
    db: Session,
    user,
    *,
    reason: str,
) -> int:
    bump_user_auth_token_version(
        user
    )

    return revoke_all_auth_sessions(
        db,
        user,
        reason=reason,
    )
