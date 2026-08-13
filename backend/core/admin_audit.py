from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from Models.admin_audit import AdminAuditLog


SENSITIVE_AUDIT_KEY_MARKERS = (
    "password",
    "pw_hash",
    "token",
    "jti",
    "secret",
    "authorization",
    "cookie",
)


def _is_sensitive_audit_key(
    key: object,
) -> bool:
    normalized = str(key).casefold()

    return any(
        marker in normalized
        for marker in SENSITIVE_AUDIT_KEY_MARKERS
    )


def sanitize_admin_audit_details(
    value: Any,
) -> Any:
    if isinstance(value, dict):
        return {
            str(key): sanitize_admin_audit_details(
                item
            )
            for key, item in value.items()
            if not _is_sensitive_audit_key(
                key
            )
        }

    if isinstance(value, list):
        return [
            sanitize_admin_audit_details(
                item
            )
            for item in value
        ]

    if isinstance(value, tuple):
        return [
            sanitize_admin_audit_details(
                item
            )
            for item in value
        ]

    if isinstance(
        value,
        (str, int, float, bool),
    ) or value is None:
        return value

    return str(value)


def append_admin_audit(
    db: Session,
    *,
    company_id: int,
    actor_user_id: int | None,
    action: str,
    target_type: str,
    target_id: int | str,
    details: dict[str, Any] | None = None,
) -> AdminAuditLog:
    audit = AdminAuditLog(
        company_id=company_id,
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        details_json=sanitize_admin_audit_details(
            details or {}
        ),
    )

    db.add(audit)

    return audit
