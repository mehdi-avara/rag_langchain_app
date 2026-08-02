from __future__ import annotations

from typing import Any


GLOBAL_ADMIN_ROLE_NAME = "admin"
GLOBAL_USER_ROLE_NAME = "user"
TENANT_ADMIN_ROLE_NAME = "company_admin"

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


def is_tenant_permission_name(
    permission_name: str,
) -> bool:
    if permission_name in TENANT_PERMISSION_NAMES:
        return True

    return permission_name.startswith(
        TENANT_PERMISSION_PREFIXES
    )


def _active_roles(user: Any) -> list[Any]:
    return [
        role
        for role in getattr(user, "roles", []) or []
        if getattr(role, "is_active", True) is not False
    ]


def is_platform_admin(user: Any) -> bool:
    return any(
        getattr(role, "name", None)
        == GLOBAL_ADMIN_ROLE_NAME
        and getattr(role, "is_system", False) is True
        and getattr(role, "company_id", None) is None
        for role in _active_roles(user)
    )


def role_is_in_user_scope(
    user: Any,
    role: Any,
) -> bool:
    if getattr(role, "is_active", True) is False:
        return False

    user_company_id = getattr(
        user,
        "company_id",
        None,
    )

    role_company_id = getattr(
        role,
        "company_id",
        user_company_id,
    )

    role_is_system = getattr(
        role,
        "is_system",
        False,
    )

    role_name = getattr(
        role,
        "name",
        None,
    )

    if (
        role_is_system is True
        and role_company_id is None
    ):
        if role_name == GLOBAL_USER_ROLE_NAME:
            return True

        return (
            role_name == GLOBAL_ADMIN_ROLE_NAME
            and is_platform_admin(user)
        )

    if user_company_id is None:
        return False

    return (
        role_is_system is False
        and role_company_id == user_company_id
    )


def get_scoped_roles(user: Any) -> list[Any]:
    return [
        role
        for role in _active_roles(user)
        if role_is_in_user_scope(
            user,
            role,
        )
    ]


def get_scoped_role_names(
    user: Any,
) -> set[str]:
    return {
        role.name
        for role in get_scoped_roles(user)
        if getattr(role, "name", None)
    }


def get_scoped_permission_names(
    user: Any,
) -> set[str]:
    return {
        permission.name
        for role in get_scoped_roles(user)
        for permission in (
            getattr(role, "permissions", []) or []
        )
        if getattr(permission, "name", None)
    }


def is_company_admin(user: Any) -> bool:
    user_company_id = getattr(
        user,
        "company_id",
        None,
    )

    if user_company_id is None:
        return False

    for role in get_scoped_roles(user):
        role_name = getattr(
            role,
            "name",
            None,
        )

        role_company_id = getattr(
            role,
            "company_id",
            user_company_id,
        )

        role_is_system = getattr(
            role,
            "is_system",
            False,
        )

        if (
            role_name == TENANT_ADMIN_ROLE_NAME
            and role_company_id == user_company_id
            and role_is_system is False
        ):
            return True

        if (
            role_name == GLOBAL_ADMIN_ROLE_NAME
            and role_company_id is None
            and role_is_system is True
        ):
            return True

    return False
