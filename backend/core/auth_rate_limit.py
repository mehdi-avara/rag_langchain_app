from __future__ import annotations

import hashlib

import redis
from fastapi import HTTPException, status
from redis.exceptions import RedisError

from core.exceptions.error_codes import (
    AUTH_CONFIGURATION_ERROR,
    AUTH_RATE_LIMITED,
)
from settings import get_settings


settings = get_settings()

_RATE_LIMIT_SCRIPT = """
local subject_count = redis.call('INCR', KEYS[1])

if subject_count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
elseif redis.call('TTL', KEYS[1]) < 0 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end

local global_count = redis.call('INCR', KEYS[2])

if global_count == 1 then
    redis.call('EXPIRE', KEYS[2], ARGV[1])
elseif redis.call('TTL', KEYS[2]) < 0 then
    redis.call('EXPIRE', KEYS[2], ARGV[1])
end

return {
    subject_count,
    global_count,
    redis.call('TTL', KEYS[1]),
    redis.call('TTL', KEYS[2])
}
"""


def _error_detail(
    code: str,
    message: str,
) -> dict[str, str]:
    return {
        "code": code,
        "message": message,
    }


def _digest(
    value: str,
) -> str:
    normalized = value.strip().lower()

    return hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()


def _consume(
    *,
    scope: str,
    subject: str,
    window_seconds: int,
    subject_limit: int,
    global_limit: int,
) -> None:
    if not settings.auth_rate_limit_enabled:
        return

    if (
        window_seconds <= 0
        or subject_limit <= 0
        or global_limit <= 0
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_error_detail(
                AUTH_CONFIGURATION_ERROR,
                "Authentication rate-limit policy is unavailable",
            ),
        )

    client = redis.Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=2,
        socket_timeout=2,
        decode_responses=True,
    )

    subject_key = (
        f"porsa:auth:{scope}:"
        f"subject:{_digest(subject)}"
    )
    global_key = (
        f"porsa:auth:{scope}:global"
    )

    try:
        result = client.eval(
            _RATE_LIMIT_SCRIPT,
            2,
            subject_key,
            global_key,
            window_seconds,
        )
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_error_detail(
                AUTH_CONFIGURATION_ERROR,
                "Authentication security service is unavailable",
            ),
        ) from exc
    finally:
        client.close()

    (
        subject_count,
        global_count,
        subject_ttl,
        global_ttl,
    ) = (
        int(value)
        for value in result
    )

    if (
        subject_count > subject_limit
        or global_count > global_limit
    ):
        retry_after = max(
            1,
            subject_ttl,
            global_ttl,
        )

        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=_error_detail(
                AUTH_RATE_LIMITED,
                "Authentication rate limit exceeded",
            ),
            headers={
                "Retry-After": str(
                    retry_after
                ),
            },
        )


def enforce_login_rate_limit(
    *,
    username: str,
) -> None:
    _consume(
        scope="login",
        subject=username,
        window_seconds=(
            settings
            .auth_login_rate_window_seconds
        ),
        subject_limit=(
            settings
            .auth_login_rate_max_per_identity
        ),
        global_limit=(
            settings
            .auth_login_rate_max_global
        ),
    )


def enforce_refresh_rate_limit(
    *,
    refresh_token: str,
) -> None:
    _consume(
        scope="refresh",
        subject=refresh_token,
        window_seconds=(
            settings
            .auth_refresh_rate_window_seconds
        ),
        subject_limit=(
            settings
            .auth_refresh_rate_max_per_token
        ),
        global_limit=(
            settings
            .auth_refresh_rate_max_global
        ),
    )
