"""Security controls for unauthenticated tenant registration.

The limiter stores only SHA-256 digests of normalized email addresses and a
global sliding-window bucket. It intentionally follows the existing
application-level sliding-window convention without writing to Redis or the
database during registration checks.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import defaultdict, deque
from typing import Deque

from fastapi import HTTPException, status

from core.exceptions.error_codes import (
    REGISTRATION_CONFIGURATION_ERROR,
    REGISTRATION_RATE_LIMITED,
)
from settings import get_settings


settings = get_settings()

_lock = threading.Lock()
_email_hits: dict[str, Deque[float]] = defaultdict(deque)
_global_hits: Deque[float] = deque()


def _error_detail(
    code: str,
    message: str,
) -> dict[str, str]:
    return {
        "code": code,
        "message": message,
    }


def _prune(
    bucket: Deque[float],
    *,
    now: float,
    window_seconds: int,
) -> None:
    cutoff = now - window_seconds

    while bucket and bucket[0] <= cutoff:
        bucket.popleft()


def _email_digest(
    email: str,
) -> str:
    normalized = email.strip().lower()

    return hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()


def enforce_registration_rate_limit(
    *,
    email: str,
) -> None:
    window_seconds = (
        settings.self_registration_rate_window_seconds
    )
    email_limit = (
        settings.self_registration_rate_max_per_email
    )
    global_limit = (
        settings.self_registration_rate_max_global
    )

    if (
        window_seconds <= 0
        or email_limit <= 0
        or global_limit <= 0
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_error_detail(
                REGISTRATION_CONFIGURATION_ERROR,
                "Registration security policy is unavailable",
            ),
        )

    now = time.monotonic()
    digest = _email_digest(email)

    with _lock:
        email_bucket = _email_hits[digest]

        _prune(
            email_bucket,
            now=now,
            window_seconds=window_seconds,
        )

        _prune(
            _global_hits,
            now=now,
            window_seconds=window_seconds,
        )

        if (
            len(email_bucket) >= email_limit
            or len(_global_hits) >= global_limit
        ):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=_error_detail(
                    REGISTRATION_RATE_LIMITED,
                    "Registration rate limit exceeded",
                ),
                headers={
                    "Retry-After": str(
                        window_seconds
                    )
                },
            )

        email_bucket.append(now)
        _global_hits.append(now)


def _reset_registration_rate_limits_for_tests() -> None:
    with _lock:
        _email_hits.clear()
        _global_hits.clear()
