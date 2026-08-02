from types import SimpleNamespace

from core.authorization import (
    get_scoped_permission_names,
    get_scoped_role_names,
    is_company_admin,
    is_platform_admin,
)


def permission(name: str):
    return SimpleNamespace(name=name)


def role(
    name: str,
    *,
    company_id,
    is_system: bool,
    is_active: bool = True,
    permissions=(),
):
    return SimpleNamespace(
        name=name,
        company_id=company_id,
        is_system=is_system,
        is_active=is_active,
        permissions=[
            permission(value)
            for value in permissions
        ],
    )


def user(
    *,
    company_id=1,
    legacy_role="user",
    roles=(),
):
    return SimpleNamespace(
        company_id=company_id,
        role=legacy_role,
        roles=list(roles),
    )


def test_legacy_admin_string_grants_no_admin_access():
    current_user = user(
        legacy_role="admin",
    )

    assert is_company_admin(current_user) is False
    assert is_platform_admin(current_user) is False


def test_matching_company_admin_is_tenant_admin():
    current_user = user(
        roles=[
            role(
                "company_admin",
                company_id=1,
                is_system=False,
            )
        ],
    )

    assert is_company_admin(current_user) is True
    assert is_platform_admin(current_user) is False


def test_foreign_company_role_is_out_of_scope():
    current_user = user(
        company_id=1,
        roles=[
            role(
                "company_admin",
                company_id=2,
                is_system=False,
                permissions=(
                    "documents:delete",
                ),
            )
        ],
    )

    assert is_company_admin(current_user) is False
    assert get_scoped_role_names(current_user) == set()
    assert get_scoped_permission_names(current_user) == set()


def test_global_user_role_remains_compatible():
    current_user = user(
        company_id=1,
        roles=[
            role(
                "user",
                company_id=None,
                is_system=True,
                permissions=(
                    "documents:read",
                ),
            )
        ],
    )

    assert get_scoped_role_names(
        current_user
    ) == {"user"}

    assert get_scoped_permission_names(
        current_user
    ) == {"documents:read"}


def test_global_admin_is_platform_admin():
    current_user = user(
        company_id=1,
        legacy_role="admin",
        roles=[
            role(
                "admin",
                company_id=None,
                is_system=True,
                permissions=(
                    "llm:update",
                ),
            )
        ],
    )

    assert is_platform_admin(current_user) is True
    assert is_company_admin(current_user) is True
    assert get_scoped_permission_names(
        current_user
    ) == {"llm:update"}


def test_inactive_roles_are_ignored():
    current_user = user(
        roles=[
            role(
                "company_admin",
                company_id=1,
                is_system=False,
                is_active=False,
                permissions=(
                    "documents:delete",
                ),
            )
        ],
    )

    assert is_company_admin(current_user) is False
    assert get_scoped_permission_names(current_user) == set()
