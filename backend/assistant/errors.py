"""Catalogued assistant errors (PROMPT §9).

Every failure path raises a registered ``AppException`` — never an ad-hoc
``HTTPException``. ``INTERNAL_SERVER_ERROR`` is the only uncatalogued case and is
produced by the global handler, not here.
"""

from __future__ import annotations

from core.exceptions.app_exception import AppException
from core.exceptions.error_codes import (
    ASSISTANT_DRAFT_INVALID,
    ASSISTANT_DRAFT_NOT_FOUND,
    ASSISTANT_DRAFT_NOT_PENDING,
    ASSISTANT_FILE_UNREADABLE,
    ASSISTANT_INTENT_UNCLEAR,
    ASSISTANT_RATE_LIMITED,
    ASSISTANT_RUN_NOT_FOUND,
    BAD_REQUEST_STATUS_CODE,
    CONFLICT_STATUS_CODE,
    FORBIDDEN_STATUS_CODE,
    NOT_FOUND_STATUS_CODE,
    PERMISSION_DENIED,
    TOO_MANY_REQUESTS_STATUS_CODE,
    VALIDATION_STATUS_CODE,
)


def permission_denied(permission: str | None = None) -> AppException:
    return AppException(
        status_code=FORBIDDEN_STATUS_CODE,
        code=PERMISSION_DENIED,
        message="Permission denied" + (f": {permission}" if permission else ""),
        details={"permission": permission} if permission else None,
    )


def intent_unclear(message: str = "Could not determine the user's intent") -> AppException:
    return AppException(
        status_code=BAD_REQUEST_STATUS_CODE,
        code=ASSISTANT_INTENT_UNCLEAR,
        message=message,
    )


def draft_not_found() -> AppException:
    return AppException(
        status_code=NOT_FOUND_STATUS_CODE,
        code=ASSISTANT_DRAFT_NOT_FOUND,
        message="Draft not found",
    )


def draft_not_pending() -> AppException:
    return AppException(
        status_code=CONFLICT_STATUS_CODE,
        code=ASSISTANT_DRAFT_NOT_PENDING,
        message="Draft is not pending",
    )


def draft_invalid(details=None) -> AppException:
    return AppException(
        status_code=VALIDATION_STATUS_CODE,
        code=ASSISTANT_DRAFT_INVALID,
        message="Draft payload is invalid",
        details=details,
    )


def run_not_found() -> AppException:
    return AppException(
        status_code=NOT_FOUND_STATUS_CODE,
        code=ASSISTANT_RUN_NOT_FOUND,
        message="Agent run not found",
    )


def rate_limited(message: str = "Assistant rate limit exceeded") -> AppException:
    return AppException(
        status_code=TOO_MANY_REQUESTS_STATUS_CODE,
        code=ASSISTANT_RATE_LIMITED,
        message=message,
    )


def file_unreadable(details=None) -> AppException:
    return AppException(
        status_code=BAD_REQUEST_STATUS_CODE,
        code=ASSISTANT_FILE_UNREADABLE,
        message="Could not read the attached file",
        details=details,
    )
