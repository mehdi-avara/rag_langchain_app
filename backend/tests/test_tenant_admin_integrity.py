import inspect
import os

os.environ.setdefault(
    "POSTGRES_DB",
    "test",
)
os.environ.setdefault(
    "POSTGRES_USER",
    "test",
)
os.environ.setdefault(
    "POSTGRES_PASSWORD",
    "test",
)
os.environ.setdefault(
    "POSTGRES_IP",
    "localhost",
)
os.environ.setdefault(
    "default_username",
    "admin",
)
os.environ.setdefault(
    "default_password",
    "admin123456",
)
os.environ.setdefault(
    "default_firstname",
    "Admin",
)
os.environ.setdefault(
    "jwt_secret",
    "test-secret",
)
os.environ.setdefault(
    "openai_api_key",
    "test",
)
os.environ.setdefault(
    "jina_api_key",
    "test",
)

from Models import Permission, Role
from db import seed_rbac


class FakeQuery:
    def __init__(
        self,
        db,
        model,
    ):
        self.db = db
        self.model = model

    def filter(
        self,
        *_args,
        **_kwargs,
    ):
        return self

    def all(self):
        if self.model is Role:
            return list(
                self.db.roles
            )

        return []


class FakeDB:
    def __init__(
        self,
        roles,
    ):
        self.roles = roles

    def query(
        self,
        model,
    ):
        return FakeQuery(
            self,
            model,
        )


def permission(
    permission_id,
    name,
):
    resource, action = name.rsplit(
        ":",
        1,
    )

    return Permission(
        id=permission_id,
        name=name,
        resource=resource,
        action=action,
        description=name,
    )


def role(
    role_id,
    name,
    company_id,
    is_system,
):
    value = Role(
        id=role_id,
        name=name,
        company_id=company_id,
        is_system=is_system,
        is_active=True,
    )
    value.permissions = []
    return value


def test_global_role_lookup_is_company_null_scoped():
    source = inspect.getsource(
        seed_rbac.get_or_create_role
    )

    assert (
        "Role.company_id.is_(None)"
        in source
    )


def test_company_admin_permission_sync_is_tenant_only():
    tenant_admin = role(
        1,
        "company_admin",
        7,
        False,
    )

    custom_role = role(
        2,
        "operator",
        7,
        False,
    )

    global_admin = role(
        3,
        "admin",
        None,
        True,
    )

    custom_permission = permission(
        1,
        "documents:read",
    )

    management_permission = permission(
        2,
        "users:create",
    )

    platform_permission = permission(
        3,
        "llm:update",
    )

    custom_role.permissions = [
        custom_permission
    ]

    global_admin.permissions = [
        platform_permission
    ]

    db = FakeDB(
        [
            tenant_admin,
            custom_role,
            global_admin,
        ]
    )

    seed_rbac.sync_company_admin_permissions(
        db,
        [
            custom_permission,
            management_permission,
            platform_permission,
        ],
    )

    assert {
        item.name
        for item in tenant_admin.permissions
    } == {
        "documents:read",
        "users:create",
    }

    assert {
        item.name
        for item in custom_role.permissions
    } == {
        "documents:read",
    }

    assert {
        item.name
        for item in global_admin.permissions
    } == {
        "llm:update",
    }
