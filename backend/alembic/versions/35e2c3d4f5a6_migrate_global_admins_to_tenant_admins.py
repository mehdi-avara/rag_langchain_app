"""Migrate tenant users away from the global administrator role.

Revision ID: 35e2c3d4f5a6
Revises: 24d1b2c3e4f5
Create Date: 2026-08-02
"""

from collections import defaultdict
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "35e2c3d4f5a6"
down_revision: Union[
    str,
    None,
] = "24d1b2c3e4f5"
branch_labels: Union[
    str,
    Sequence[str],
    None,
] = None
depends_on: Union[
    str,
    Sequence[str],
    None,
] = None


GLOBAL_ADMIN_ROLE_NAME = "admin"
TENANT_ADMIN_ROLE_NAME = "company_admin"
GLOBAL_USER_ROLE_NAME = "user"

MIGRATION_MARKER_PREFIX = (
    "SEC4M_CREATED_FOR_USERS:"
)

TENANT_PERMISSION_PREFIXES = (
    "assistant:",
    "business_management:",
    "chat:",
    "comments:",
    "company:",
    "documents:",
    "financial_management:",
    "goods_receipt_management:",
    "material_management:",
    "models:",
    "organization:",
    "profile:",
    "property_management:",
    "purchase_management:",
    "requisition_management:",
    "rfq_management:",
    "stt:",
    "supplier_management:",
    "tags:",
    "warehouse_management:",
    "workflow:",
)

TENANT_PERMISSION_NAMES = frozenset(
    {
        "currencies:read",
        "exchange_rates:read",
        "permissions:read",
        "roles:read",
        "users:read",
    }
)

TENANT_PERMISSION_DENYLIST = frozenset(
    {
        "assistant:debug",
    }
)


roles = sa.table(
    "roles",
    sa.column("id", sa.Integer()),
    sa.column("company_id", sa.Integer()),
    sa.column("name", sa.String()),
    sa.column("description", sa.String()),
    sa.column("is_active", sa.Boolean()),
    sa.column("is_system", sa.Boolean()),
)

permissions = sa.table(
    "permissions",
    sa.column("id", sa.Integer()),
    sa.column("name", sa.String()),
)

users = sa.table(
    "users",
    sa.column("id", sa.Integer()),
    sa.column("company_id", sa.Integer()),
    sa.column("role", sa.String()),
    sa.column("is_active", sa.Boolean()),
    sa.column("auth_token_version", sa.Integer()),
)

user_role = sa.table(
    "user_role",
    sa.column("user_id", sa.Integer()),
    sa.column("role_id", sa.Integer()),
)

role_permission = sa.table(
    "role_permission",
    sa.column("role_id", sa.Integer()),
    sa.column("permission_id", sa.Integer()),
)

auth_sessions = sa.table(
    "auth_sessions",
    sa.column("user_id", sa.Integer()),
    sa.column("revoked_at", sa.DateTime()),
    sa.column("revoked_reason", sa.String()),
)


def _tenant_permission_condition():
    allowed = sa.or_(
        permissions.c.name.in_(
            sorted(
                TENANT_PERMISSION_NAMES
            )
        ),
        *[
            permissions.c.name.like(
                f"{prefix}%"
            )
            for prefix in (
                TENANT_PERMISSION_PREFIXES
            )
        ],
    )

    return sa.and_(
        allowed,
        permissions.c.name.not_in(
            sorted(
                TENANT_PERMISSION_DENYLIST
            )
        ),
    )


def _build_marker(
    user_ids: list[int],
) -> str:
    normalized = sorted(
        {
            int(user_id)
            for user_id in user_ids
        }
    )

    if not normalized:
        raise RuntimeError(
            "Migration marker requires user IDs"
        )

    marker = (
        MIGRATION_MARKER_PREFIX
        + ",".join(
            str(user_id)
            for user_id in normalized
        )
    )

    if len(marker) > 200:
        raise RuntimeError(
            "Migration marker exceeds role description limit"
        )

    return marker


def _parse_marker(
    description: str | None,
) -> list[int]:
    if (
        not description
        or not description.startswith(
            MIGRATION_MARKER_PREFIX
        )
    ):
        raise RuntimeError(
            "Invalid tenant-admin migration marker"
        )

    raw_ids = description[
        len(MIGRATION_MARKER_PREFIX):
    ]

    try:
        user_ids = sorted(
            {
                int(value)
                for value in raw_ids.split(",")
                if value
            }
        )
    except ValueError as exc:
        raise RuntimeError(
            "Invalid migrated user identifier"
        ) from exc

    if not user_ids:
        raise RuntimeError(
            "Migration marker contains no users"
        )

    return user_ids


def _global_admin_role_id(
    bind,
) -> int | None:
    return bind.execute(
        sa.select(
            roles.c.id
        ).where(
            roles.c.name
            == GLOBAL_ADMIN_ROLE_NAME,
            roles.c.company_id.is_(None),
            roles.c.is_system.is_(True),
            roles.c.is_active.is_(True),
        )
    ).scalar_one_or_none()


def _revoke_authentication(
    bind,
    user_ids: list[int],
    reason: str,
) -> None:
    if not user_ids:
        return

    bind.execute(
        users.update()
        .where(
            users.c.id.in_(user_ids)
        )
        .values(
            auth_token_version=(
                users.c.auth_token_version
                + 1
            )
        )
    )

    bind.execute(
        auth_sessions.update()
        .where(
            auth_sessions.c.user_id.in_(
                user_ids
            ),
            auth_sessions.c.revoked_at.is_(
                None
            ),
        )
        .values(
            revoked_at=sa.func.now(),
            revoked_reason=reason,
        )
    )


def upgrade() -> None:
    bind = op.get_bind()

    global_admin_role_id = (
        _global_admin_role_id(bind)
    )

    if global_admin_role_id is None:
        return

    global_admin_users = bind.execute(
        sa.select(
            users.c.id,
            users.c.company_id,
            users.c.role,
            users.c.is_active,
        )
        .select_from(
            users.join(
                user_role,
                user_role.c.user_id
                == users.c.id,
            )
        )
        .where(
            user_role.c.role_id
            == global_admin_role_id
        )
        .order_by(
            users.c.id
        )
        .with_for_update(
            of=users
        )
    ).mappings().all()

    if not global_admin_users:
        return

    active_user_ids = [
        row["id"]
        for row in global_admin_users
        if row["is_active"] is True
    ]

    if not active_user_ids:
        raise RuntimeError(
            "Global admin assignments exist without "
            "an active platform administrator"
        )

    preserved_user_id = min(
        active_user_ids
    )

    candidates = [
        row
        for row in global_admin_users
        if row["id"] != preserved_user_id
    ]

    if not candidates:
        return

    invalid_company_users = [
        row["id"]
        for row in candidates
        if row["company_id"] is None
    ]

    if invalid_company_users:
        raise RuntimeError(
            "Tenant migration candidates must belong "
            "to a company"
        )

    invalid_legacy_roles = [
        row["id"]
        for row in candidates
        if row["role"]
        != GLOBAL_ADMIN_ROLE_NAME
    ]

    if invalid_legacy_roles:
        raise RuntimeError(
            "Tenant migration candidates have an "
            "unexpected legacy role"
        )

    existing_tenant_roles = bind.execute(
        sa.select(
            roles.c.id,
            roles.c.company_id,
        ).where(
            roles.c.name
            == TENANT_ADMIN_ROLE_NAME,
            roles.c.company_id.is_not(
                None
            ),
        )
    ).mappings().all()

    if existing_tenant_roles:
        raise RuntimeError(
            "Pre-existing company_admin roles require "
            "manual reconciliation"
        )

    tenant_permission_ids = list(
        bind.execute(
            sa.select(
                permissions.c.id
            )
            .where(
                _tenant_permission_condition()
            )
            .order_by(
                permissions.c.id
            )
        ).scalars()
    )

    if not tenant_permission_ids:
        raise RuntimeError(
            "Tenant administrator permissions "
            "are unavailable"
        )

    by_company = defaultdict(list)

    for row in candidates:
        by_company[
            row["company_id"]
        ].append(
            row["id"]
        )

    migrated_user_ids: list[int] = []

    for company_id in sorted(by_company):
        company_user_ids = sorted(
            by_company[company_id]
        )

        marker = _build_marker(
            company_user_ids
        )

        company_admin_role_id = (
            bind.execute(
                roles.insert()
                .values(
                    company_id=company_id,
                    name=TENANT_ADMIN_ROLE_NAME,
                    description=marker,
                    is_active=True,
                    is_system=False,
                )
                .returning(
                    roles.c.id
                )
            ).scalar_one()
        )

        bind.execute(
            role_permission.insert(),
            [
                {
                    "role_id": (
                        company_admin_role_id
                    ),
                    "permission_id": (
                        permission_id
                    ),
                }
                for permission_id
                in tenant_permission_ids
            ],
        )

        bind.execute(
            user_role.insert(),
            [
                {
                    "user_id": user_id,
                    "role_id": (
                        company_admin_role_id
                    ),
                }
                for user_id
                in company_user_ids
            ],
        )

        bind.execute(
            user_role.delete().where(
                user_role.c.user_id.in_(
                    company_user_ids
                ),
                user_role.c.role_id
                == global_admin_role_id,
            )
        )

        bind.execute(
            users.update()
            .where(
                users.c.id.in_(
                    company_user_ids
                )
            )
            .values(
                role=TENANT_ADMIN_ROLE_NAME
            )
        )

        migrated_user_ids.extend(
            company_user_ids
        )

    _revoke_authentication(
        bind,
        migrated_user_ids,
        "tenant_admin_scope_migration",
    )

    remaining_candidate_assignments = (
        bind.execute(
            sa.select(
                sa.func.count()
            )
            .select_from(
                user_role
            )
            .where(
                user_role.c.user_id.in_(
                    migrated_user_ids
                ),
                user_role.c.role_id
                == global_admin_role_id,
            )
        ).scalar_one()
    )

    if remaining_candidate_assignments:
        raise RuntimeError(
            "Global administrator assignments "
            "remain after migration"
        )

    preserved_assignment_count = (
        bind.execute(
            sa.select(
                sa.func.count()
            )
            .select_from(
                user_role
            )
            .where(
                user_role.c.user_id
                == preserved_user_id,
                user_role.c.role_id
                == global_admin_role_id,
            )
        ).scalar_one()
    )

    if preserved_assignment_count != 1:
        raise RuntimeError(
            "Platform administrator assignment "
            "was not preserved"
        )


def downgrade() -> None:
    bind = op.get_bind()

    all_tenant_roles = bind.execute(
        sa.select(
            roles.c.id,
            roles.c.company_id,
            roles.c.description,
        ).where(
            roles.c.name
            == TENANT_ADMIN_ROLE_NAME,
            roles.c.company_id.is_not(
                None
            ),
        )
        .order_by(
            roles.c.id
        )
    ).mappings().all()

    unmanaged_roles = [
        row["id"]
        for row in all_tenant_roles
        if not (
            row["description"]
            and row["description"].startswith(
                MIGRATION_MARKER_PREFIX
            )
        )
    ]

    if unmanaged_roles:
        raise RuntimeError(
            "Downgrade refused because unmanaged "
            "company_admin roles exist"
        )

    if not all_tenant_roles:
        return

    global_admin_role_id = (
        _global_admin_role_id(bind)
    )

    if global_admin_role_id is None:
        raise RuntimeError(
            "Global administrator role is unavailable"
        )

    restored_user_ids: list[int] = []

    for role_row in all_tenant_roles:
        role_id = role_row["id"]
        recorded_user_ids = _parse_marker(
            role_row["description"]
        )

        assigned_user_ids = sorted(
            bind.execute(
                sa.select(
                    user_role.c.user_id
                )
                .where(
                    user_role.c.role_id
                    == role_id
                )
                .order_by(
                    user_role.c.user_id
                )
            ).scalars()
        )

        if assigned_user_ids != recorded_user_ids:
            raise RuntimeError(
                "Downgrade refused because tenant "
                "administrator assignments changed"
            )

        current_users = bind.execute(
            sa.select(
                users.c.id,
                users.c.role,
            ).where(
                users.c.id.in_(
                    recorded_user_ids
                )
            )
        ).mappings().all()

        if (
            len(current_users)
            != len(recorded_user_ids)
        ):
            raise RuntimeError(
                "Downgrade refused because a migrated "
                "user no longer exists"
            )

        if any(
            row["role"]
            != TENANT_ADMIN_ROLE_NAME
            for row in current_users
        ):
            raise RuntimeError(
                "Downgrade refused because a migrated "
                "user role changed"
            )

        existing_global_assignments = (
            bind.execute(
                sa.select(
                    user_role.c.user_id,
                    sa.func.count().label(
                        "assignment_count"
                    ),
                )
                .where(
                    user_role.c.user_id.in_(
                        recorded_user_ids
                    ),
                    user_role.c.role_id
                    == global_admin_role_id,
                )
                .group_by(
                    user_role.c.user_id
                )
            ).mappings().all()
        )

        if existing_global_assignments:
            raise RuntimeError(
                "Downgrade refused because a migrated "
                "user already has global administrator "
                "access"
            )

        bind.execute(
            user_role.insert(),
            [
                {
                    "user_id": user_id,
                    "role_id": (
                        global_admin_role_id
                    ),
                }
                for user_id
                in recorded_user_ids
            ],
        )

        bind.execute(
            user_role.delete().where(
                user_role.c.role_id
                == role_id,
                user_role.c.user_id.in_(
                    recorded_user_ids
                ),
            )
        )

        bind.execute(
            users.update()
            .where(
                users.c.id.in_(
                    recorded_user_ids
                )
            )
            .values(
                role=GLOBAL_ADMIN_ROLE_NAME
            )
        )

        bind.execute(
            role_permission.delete().where(
                role_permission.c.role_id
                == role_id
            )
        )

        bind.execute(
            roles.delete().where(
                roles.c.id == role_id
            )
        )

        restored_user_ids.extend(
            recorded_user_ids
        )

    _revoke_authentication(
        bind,
        restored_user_ids,
        "tenant_admin_scope_downgrade",
    )
