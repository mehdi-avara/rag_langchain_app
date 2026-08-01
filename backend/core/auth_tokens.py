from __future__ import annotations

import re
from datetime import datetime, timedelta
from uuid import uuid4

from jose import JWTError, jwt

from settings import get_settings


settings = get_settings()

_IDENTIFIER_PATTERN = re.compile(
    r"^[0-9a-f]{32}$"
)


def token_issued_at() -> datetime:
    return datetime.utcnow()


def user_token_version(user) -> int:
    return int(
        getattr(
            user,
            "auth_token_version",
            0,
        )
        or 0
    )


def _base_payload(
    user,
    *,
    session_id: str,
    token_type: str,
    jti: str,
    issued_at: datetime,
    expires_at: datetime,
) -> dict:
    return {
        "sub": str(user.id),
        "company_id": user.company_id,
        "sid": session_id,
        "jti": jti,
        "ver": user_token_version(user),
        "iat": int(issued_at.timestamp()),
        "nbf": int(issued_at.timestamp()),
        "exp": expires_at,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "type": token_type,
    }


def create_access_token(
    user,
    *,
    session_id: str,
) -> str:
    if settings.jwt_access_exp_minutes <= 0:
        raise RuntimeError(
            "JWT access-token lifetime is invalid"
        )

    issued_at = token_issued_at()
    expires_at = issued_at + timedelta(
        minutes=settings.jwt_access_exp_minutes
    )

    payload = _base_payload(
        user,
        session_id=session_id,
        token_type="access",
        jti=uuid4().hex,
        issued_at=issued_at,
        expires_at=expires_at,
    )

    return jwt.encode(
        payload,
        settings.jwt_secret,
        algorithm="HS256",
    )


def create_refresh_token(
    user,
    *,
    session_id: str,
    refresh_jti: str,
) -> str:
    if settings.jwt_refresh_exp_days <= 0:
        raise RuntimeError(
            "JWT refresh-token lifetime is invalid"
        )

    issued_at = token_issued_at()
    expires_at = issued_at + timedelta(
        days=settings.jwt_refresh_exp_days
    )

    payload = _base_payload(
        user,
        session_id=session_id,
        token_type="refresh",
        jti=refresh_jti,
        issued_at=issued_at,
        expires_at=expires_at,
    )

    return jwt.encode(
        payload,
        settings.jwt_secret,
        algorithm="HS256",
    )


def create_token_pair(
    user,
    *,
    session_id: str,
    refresh_jti: str,
) -> tuple[str, str]:
    access_token = create_access_token(
        user,
        session_id=session_id,
    )
    refresh_token = create_refresh_token(
        user,
        session_id=session_id,
        refresh_jti=refresh_jti,
    )

    return access_token, refresh_token


def decode_token(
    token: str,
    *,
    expected_type: str,
) -> dict:
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=["HS256"],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
    )

    required_claims = (
        "sub",
        "company_id",
        "sid",
        "jti",
        "ver",
        "iat",
        "nbf",
        "exp",
        "iss",
        "aud",
        "type",
    )

    if any(
        claim not in payload
        for claim in required_claims
    ):
        raise JWTError(
            "Token is missing required claims"
        )

    if payload.get("type") != expected_type:
        raise JWTError(
            "Token type is invalid"
        )

    try:
        int(payload["sub"])
        int(payload["ver"])
        int(payload["iat"])
        int(payload["nbf"])
    except (TypeError, ValueError) as exc:
        raise JWTError(
            "Token claims are invalid"
        ) from exc

    session_id = payload.get("sid")
    token_jti = payload.get("jti")

    if not (
        isinstance(session_id, str)
        and _IDENTIFIER_PATTERN.fullmatch(
            session_id
        )
    ):
        raise JWTError(
            "Session identifier is invalid"
        )

    if not (
        isinstance(token_jti, str)
        and _IDENTIFIER_PATTERN.fullmatch(
            token_jti
        )
    ):
        raise JWTError(
            "Token identifier is invalid"
        )

    return payload


def is_token_stale_for_user(
    payload: dict,
    user,
) -> bool:
    password_changed_at = getattr(
        user,
        "password_changed_at",
        None,
    )

    if password_changed_at is None:
        return False

    try:
        token_iat = int(
            payload.get("iat")
        )
    except (TypeError, ValueError):
        return True

    return token_iat < int(
        password_changed_at.timestamp()
    )
