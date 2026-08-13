from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import (
    and_,
    case,
    func,
    or_,
)
from sqlalchemy.orm import Session

from Models import (
    AdminAuditLog,
    AuthSession,
    Role,
    User,
)
from core.authorization import (
    TENANT_ADMIN_ROLE_NAME,
)


def _integer(value: Any) -> int:
    return int(value or 0)


def build_admin_summary(
    db: Session,
    *,
    company_id: int,
    company_name: str,
) -> dict[str, Any]:
    now = datetime.utcnow()

    user_row = (
        db.query(
            func.count(
                User.id
            ).label("total"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            User.is_active.is_(True),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("active"),
        )
        .filter(
            User.company_id == company_id
        )
        .one()
    )

    user_total = _integer(
        user_row.total
    )

    user_active = _integer(
        user_row.active
    )

    custom_role_scope = (
        Role.company_id == company_id,
        Role.is_system.is_(False),
        func.lower(Role.name)
        != TENANT_ADMIN_ROLE_NAME.casefold(),
    )

    role_row = (
        db.query(
            func.count(
                Role.id
            ).label("total"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            Role.is_active.is_(True),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("active"),
        )
        .filter(
            *custom_role_scope
        )
        .one()
    )

    role_total = _integer(
        role_row.total
    )

    role_active = _integer(
        role_row.active
    )

    session_active = and_(
        AuthSession.revoked_at.is_(None),
        AuthSession.expires_at > now,
        AuthSession.token_version
        == User.auth_token_version,
        User.is_active.is_(True),
    )

    session_revoked = (
        AuthSession.revoked_at.is_not(
            None
        )
    )

    session_expired = and_(
        AuthSession.revoked_at.is_(None),
        AuthSession.expires_at <= now,
    )

    session_stale = and_(
        AuthSession.revoked_at.is_(None),
        AuthSession.expires_at > now,
        or_(
            AuthSession.token_version
            != User.auth_token_version,
            User.is_active.is_(False),
        ),
    )

    session_row = (
        db.query(
            func.count(
                AuthSession.id
            ).label("total"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            session_active,
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("active"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            session_revoked,
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("revoked"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            session_expired,
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("expired"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            session_stale,
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("stale"),
        )
        .join(
            User,
            User.id
            == AuthSession.user_id,
        )
        .filter(
            AuthSession.company_id
            == company_id,
            User.company_id
            == company_id,
        )
        .one()
    )

    audit_since = (
        now
        - timedelta(hours=24)
    )

    audit_row = (
        db.query(
            func.count(
                AdminAuditLog.id
            ).label("total"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            AdminAuditLog.created_at
                            >= audit_since,
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("last_24_hours"),
            func.max(
                AdminAuditLog.created_at
            ).label(
                "latest_activity_at"
            ),
        )
        .filter(
            AdminAuditLog.company_id
            == company_id
        )
        .one()
    )

    session_total = _integer(
        session_row.total
    )

    session_active_count = _integer(
        session_row.active
    )

    session_revoked_count = _integer(
        session_row.revoked
    )

    session_expired_count = _integer(
        session_row.expired
    )

    session_stale_count = _integer(
        session_row.stale
    )

    classified_session_total = (
        session_active_count
        + session_revoked_count
        + session_expired_count
        + session_stale_count
    )

    if (
        classified_session_total
        != session_total
    ):
        raise RuntimeError(
            "Admin session summary "
            "classification is incomplete"
        )

    return {
        "users": {
            "total": user_total,
            "active": user_active,
            "inactive": (
                user_total
                - user_active
            ),
        },
        "roles": {
            "total_custom": (
                role_total
            ),
            "active_custom": (
                role_active
            ),
            "inactive_custom": (
                role_total
                - role_active
            ),
        },
        "sessions": {
            "total": session_total,
            "active": (
                session_active_count
            ),
            "revoked": (
                session_revoked_count
            ),
            "expired": (
                session_expired_count
            ),
            "stale": (
                session_stale_count
            ),
        },
        "audit": {
            "total": _integer(
                audit_row.total
            ),
            "last_24_hours": _integer(
                audit_row.last_24_hours
            ),
            "latest_activity_at": (
                audit_row.latest_activity_at
            ),
        },
        "company": {
            "id": company_id,
            "name": company_name,
        },
    }
