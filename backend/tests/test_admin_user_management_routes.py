import os
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_IP", "localhost")
os.environ.setdefault("default_username", "admin")
os.environ.setdefault("default_password", "admin123456")
os.environ.setdefault("default_firstname", "Admin")
os.environ.setdefault("jwt_secret", "test-secret")
os.environ.setdefault("openai_api_key", "test")
os.environ.setdefault("jina_api_key", "test")

from Models import User, Role, Permission
from routs import rbac
from schemas.users import AdminUserCreate, AdminUserPasswordReset, AdminUserRolesUpdate


class FakeQuery:
    def __init__(self, db, model):
        self.db = db
        self.model = model
        self._order = None
        self._offset = 0
        self._limit = None

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def offset(self, value):
        self._offset = value
        return self

    def limit(self, value):
        self._limit = value
        return self

    def first(self):
        if self.model is User:
            return self.db.first_user
        if self.model is Role:
            return self.db.first_role
        return None

    def all(self):
        if self.model is User:
            values = list(self.db.users)
        elif self.model is Role:
            values = list(self.db.roles)
        elif self.model is Permission:
            values = list(
                self.db.permissions
            )
        else:
            values = []

        start = self._offset

        if self._limit is None:
            return values[start:]

        return values[
            start:start + self._limit
        ]


class FakeDB:
    def __init__(
        self,
        users=None,
        roles=None,
        permissions=None,
        first_user=None,
        first_role=None,
    ):
        self.users = users or []
        self.roles = roles or []
        self.permissions = permissions or []
        self.first_user = first_user
        self.first_role = first_role
        self.added = []
        self.flushed = False
        self.committed = False
        self.refreshed = []

    def query(self, model):
        return FakeQuery(self, model)

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, User):
            self.users.append(obj)

    def flush(self):
        self.flushed = True

        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = 99

    def delete(self, obj):
        if obj in self.roles:
            self.roles.remove(obj)
        if obj in self.users:
            self.users.remove(obj)

    def commit(self):
        self.committed = True

    def refresh(self, obj):
        self.refreshed.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = 99
        if isinstance(obj, User) and getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.utcnow()


def make_role(role_id=1, name="user", active=True, permissions=None, company_id=None, is_system=True):
    role = Role(id=role_id, name=name, is_active=active, company_id=company_id, is_system=is_system)
    role.permissions = [
        Permission(id=i + 1, name=permission, resource="test", action="read")
        for i, permission in enumerate(permissions or [])
    ]
    return role


def make_user(user_id=1, company_id=1, username="user@example.com", role_name="user", active=True):
    role = make_role(name=role_name)
    user = User(
        id=user_id,
        company_id=company_id,
        username=username,
        First_name="Test",
        Last_name="User",
        pw_hash="hash",
        role=role_name,
        is_active=active,
        created_at=datetime.utcnow(),
    )
    user.roles = [role]
    return user


def test_create_company_user_uses_current_user_company():
    normal_role = make_role(role_id=2, name="user")
    current_user = make_user(user_id=1, company_id=7, role_name="admin")
    db = FakeDB(roles=[normal_role], first_user=None, first_role=normal_role)

    result = rbac.create_company_user(
        payload=AdminUserCreate(
            username="New@Example.com",
            password="StrongPass123",
            First_name="New",
            Last_name="User",
            role_ids=[],
        ),
        db=db,
        current_user=current_user,
    )

    assert result.company_id == 7
    assert result.username == "new@example.com"
    assert result.is_active is True
    assert db.flushed is True
    assert db.committed is True


def test_deactivate_self_is_rejected():
    user = make_user(user_id=5, company_id=1, role_name="admin")
    db = FakeDB(users=[user], first_user=user)

    with pytest.raises(HTTPException) as exc:
        rbac.deactivate_company_user(user_id=5, db=db, current_user=user)

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "SELF_ACTION_FORBIDDEN"
    assert exc.value.detail["message"] == "Cannot deactivate your own account"


def test_deactivate_last_active_admin_is_rejected():
    current_user = make_user(user_id=1, company_id=1, role_name="admin")
    target_admin = make_user(user_id=2, company_id=1, role_name="admin")
    db = FakeDB(users=[target_admin], first_user=target_admin)

    with pytest.raises(HTTPException) as exc:
        rbac.deactivate_company_user(user_id=2, db=db, current_user=current_user)

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "LAST_ADMIN_PROTECTED"
    assert exc.value.detail["message"] == "Cannot modify the last active admin of the company"


def test_reset_password_updates_password_changed_at():
    current_user = make_user(user_id=1, company_id=1, role_name="admin")
    target = make_user(user_id=3, company_id=1, role_name="user")
    db = FakeDB(first_user=target)

    result = rbac.reset_company_user_password(
        user_id=3,
        payload=AdminUserPasswordReset(new_password="NewStrongPass123"),
        db=db,
        current_user=current_user,
    )

    assert result.id == 3
    assert target.password_changed_at is not None
    assert db.committed is True


def test_change_own_roles_is_rejected():
    admin_role = make_role(role_id=1, name="admin")
    user = make_user(user_id=1, company_id=1, role_name="admin")
    db = FakeDB(roles=[admin_role], first_user=user)

    with pytest.raises(HTTPException) as exc:
        rbac.update_company_user_roles(
            user_id=1,
            payload=AdminUserRolesUpdate(role_ids=[1]),
            db=db,
            current_user=user,
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "SELF_ACTION_FORBIDDEN"
    assert exc.value.detail["message"] == "Cannot change your own roles"


def test_delete_role_assigned_to_active_user_is_rejected():
    current_user = make_user(user_id=1, company_id=1, role_name="admin")
    custom_role = make_role(role_id=9, name="operator", company_id=1, is_system=False)
    assigned_user = make_user(user_id=8, company_id=1, role_name="user", active=True)
    custom_role.users = [assigned_user]

    db = FakeDB(roles=[custom_role], first_user=None, first_role=custom_role)

    with pytest.raises(HTTPException) as exc:
        rbac.delete_role(role_id=9, db=db, current_user=current_user)

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "ROLE_IN_USE"
    assert exc.value.detail["message"] == "Cannot modify a role assigned to active users"


def test_delete_role_assigned_only_to_inactive_user_is_allowed():
    current_user = make_user(user_id=1, company_id=1, role_name="admin")
    custom_role = make_role(role_id=9, name="operator", company_id=1, is_system=False)
    assigned_user = make_user(user_id=8, company_id=1, role_name="user", active=False)
    custom_role.users = [assigned_user]

    db = FakeDB(roles=[custom_role], first_user=None, first_role=custom_role)
    deleted = []

    def delete(obj):
        deleted.append(obj)

    db.delete = delete

    result = rbac.delete_role(role_id=9, db=db, current_user=current_user)

    assert result == {"message": "Role deleted"}
    assert deleted == [custom_role]
    assert db.committed is True


def test_inactivate_role_assigned_to_active_user_is_rejected():
    current_user = make_user(user_id=1, company_id=1, role_name="admin")
    custom_role = make_role(role_id=9, name="operator", company_id=1, is_system=False)
    assigned_user = make_user(user_id=8, company_id=1, role_name="user", active=True)
    custom_role.users = [assigned_user]

    db = FakeDB(roles=[custom_role], first_role=custom_role)

    with pytest.raises(HTTPException) as exc:
        rbac.update_role(
            role_id=9,
            data=rbac.RoleUpdate(is_active=False),
            db=db,
            current_user=current_user,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "ROLE_IN_USE"
    assert exc.value.detail["message"] == "Cannot modify a role assigned to active users"


def test_inactivate_role_assigned_only_to_inactive_user_is_allowed():
    current_user = make_user(user_id=1, company_id=1, role_name="admin")
    custom_role = make_role(role_id=9, name="operator", company_id=1, is_system=False)
    assigned_user = make_user(user_id=8, company_id=1, role_name="user", active=False)
    custom_role.users = [assigned_user]

    db = FakeDB(roles=[custom_role], first_role=custom_role)

    result = rbac.update_role(
        role_id=9,
        data=rbac.RoleUpdate(is_active=False),
        db=db,
        current_user=current_user,
    )

    assert result.is_active is False
    assert custom_role.is_active is False
    assert db.committed is True


def test_get_missing_role_returns_standard_error():
    current_user = make_user(user_id=1, company_id=1, role_name="admin")
    db = FakeDB(roles=[], first_role=None)

    with pytest.raises(HTTPException) as exc:
        rbac.update_role(
            role_id=404,
            data=rbac.RoleUpdate(description="x"),
            db=db,
            current_user=current_user,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "ROLE_NOT_FOUND"
    assert exc.value.detail["message"] == "Role not found"


def test_invalid_role_ids_returns_standard_error():
    current_user = make_user(user_id=1, company_id=1, role_name="admin")
    target = make_user(user_id=2, company_id=1, role_name="user")
    db = FakeDB(users=[target], roles=[], first_user=target)

    with pytest.raises(HTTPException) as exc:
        rbac.update_company_user_roles(
            user_id=2,
            payload=AdminUserRolesUpdate(role_ids=[999]),
            db=db,
            current_user=current_user,
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "INVALID_ROLE_IDS"
    assert exc.value.detail["message"] == "Invalid role_ids"


def test_current_user_access_returns_roles_permissions_and_admin_flag():
    role = make_role(
        role_id=1,
        name="admin",
        permissions=["users:read", "users:create"],
    )
    user = make_user(user_id=10, company_id=3, username="admin@example.com", role_name="admin")
    user.roles = [role]

    result = rbac.get_current_user_access(current_user=user)

    assert result.user_id == 10
    assert result.company_id == 3
    assert result.username == "admin@example.com"
    assert result.roles == ["admin"]
    assert result.permissions == ["users:create", "users:read"]
    assert result.is_admin is True
    assert result.is_active is True


def test_current_user_access_ignores_inactive_roles_permissions():
    active_role = make_role(
        role_id=1,
        name="operator",
        permissions=["documents:read"],
        is_system=False,
        company_id=1,
    )
    inactive_role = make_role(
        role_id=2,
        name="inactive-role",
        active=False,
        permissions=["users:delete"],
        is_system=False,
        company_id=1,
    )

    user = make_user(user_id=11, company_id=1, username="operator@example.com", role_name="user")
    user.role = None
    user.roles = [active_role, inactive_role]

    result = rbac.get_current_user_access(current_user=user)

    assert result.roles == ["operator"]
    assert result.permissions == ["documents:read"]
    assert result.is_admin is False


def test_list_company_users_returns_lightweight_roles():
    admin_role = make_role(
        role_id=1,
        name="admin",
        permissions=["users:read", "users:create"],
    )
    user = make_user(user_id=1, company_id=1, username="admin@example.com", role_name="admin")
    user.roles = [admin_role]

    db = FakeDB(users=[user])
    current_user = make_user(user_id=2, company_id=1, role_name="admin")

    result = rbac.list_company_users(db=db, current_user=current_user)

    assert len(result) == 1
    assert result[0].id == 1
    assert result[0].roles == ["admin"]
    assert result[0].permissions == ["users:create", "users:read"]
    assert all(not hasattr(role, "permissions") for role in result[0].roles)


def test_get_company_user_still_returns_full_role_objects():
    admin_role = make_role(
        role_id=1,
        name="admin",
        permissions=["users:read", "users:create"],
    )
    user = make_user(user_id=1, company_id=1, username="admin@example.com", role_name="admin")
    user.roles = [admin_role]

    db = FakeDB(users=[user], first_user=user)
    current_user = make_user(user_id=2, company_id=1, role_name="admin")

    result = rbac.get_company_user(user_id=1, db=db, current_user=current_user)

    assert result.id == 1
    assert result.roles[0].name == "admin"
    assert len(result.roles[0].permissions) == 2
    assert result.permissions == ["users:create", "users:read"]



def test_create_role_rejects_platform_permission_ids():
    current_user = make_user(
        user_id=1,
        company_id=1,
        role_name="admin",
    )

    platform_permission = Permission(
        id=900,
        name="assistant:debug",
        resource="assistant",
        action="debug",
        description="Platform debug access",
    )

    db = FakeDB(
        permissions=[
            platform_permission
        ]
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        rbac.create_role(
            data=rbac.RoleCreate(
                name="unsafe-role",
                permission_ids=[900],
            ),
            db=db,
            current_user=current_user,
        )

    assert exc.value.status_code == 400
    assert (
        exc.value.detail["code"]
        == "INVALID_PERMISSION_IDS"
    )
    assert (
        exc.value.detail["message"]
        == "Invalid permission_ids"
    )


def test_create_role_rejects_missing_permission_ids():
    current_user = make_user(
        user_id=1,
        company_id=1,
        role_name="admin",
    )

    db = FakeDB(
        permissions=[]
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        rbac.create_role(
            data=rbac.RoleCreate(
                name="invalid-role",
                permission_ids=[999],
            ),
            db=db,
            current_user=current_user,
        )

    assert exc.value.status_code == 400
    assert (
        exc.value.detail["code"]
        == "INVALID_PERMISSION_IDS"
    )


def test_create_role_accepts_tenant_permission_ids():
    current_user = make_user(
        user_id=1,
        company_id=1,
        role_name="admin",
    )

    tenant_permission = Permission(
        id=10,
        name="documents:read",
        resource="documents",
        action="read",
        description="Read documents",
    )

    db = FakeDB(
        permissions=[
            tenant_permission
        ]
    )

    result = rbac.create_role(
        data=rbac.RoleCreate(
            name="document-reader",
            permission_ids=[10],
        ),
        db=db,
        current_user=current_user,
    )

    assert result.name == "document-reader"
    assert result.company_id == 1
    assert [
        permission.name
        for permission
        in result.permissions
    ] == [
        "documents:read"
    ]


def test_update_role_rejects_platform_permission_ids():
    current_user = make_user(
        user_id=1,
        company_id=1,
        role_name="admin",
    )

    custom_role = make_role(
        role_id=8,
        name="operator",
        company_id=1,
        is_system=False,
    )

    platform_permission = Permission(
        id=901,
        name="llm:update",
        resource="llm",
        action="update",
        description="Update LLM configuration",
    )

    db = FakeDB(
        roles=[custom_role],
        permissions=[
            platform_permission
        ],
        first_role=custom_role,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        rbac.update_role(
            role_id=8,
            data=rbac.RoleUpdate(
                permission_ids=[901]
            ),
            db=db,
            current_user=current_user,
        )

    assert exc.value.status_code == 400
    assert (
        exc.value.detail["code"]
        == "INVALID_PERMISSION_IDS"
    )


def test_list_company_users_supports_offset_and_limit():
    users = [
        make_user(
            user_id=1,
            company_id=1,
            username="one@example.com",
        ),
        make_user(
            user_id=2,
            company_id=1,
            username="two@example.com",
        ),
        make_user(
            user_id=3,
            company_id=1,
            username="three@example.com",
        ),
    ]

    db = FakeDB(
        users=users
    )

    current_user = make_user(
        user_id=50,
        company_id=1,
        role_name="admin",
    )

    result = rbac.list_company_users(
        offset=1,
        limit=1,
        db=db,
        current_user=current_user,
    )

    assert len(result) == 1
    assert result[0].id == 2


def test_list_roles_supports_offset_and_limit():
    roles = [
        make_role(
            role_id=1,
            name="one",
            company_id=1,
            is_system=False,
        ),
        make_role(
            role_id=2,
            name="two",
            company_id=1,
            is_system=False,
        ),
        make_role(
            role_id=3,
            name="three",
            company_id=1,
            is_system=False,
        ),
    ]

    db = FakeDB(
        roles=roles
    )

    current_user = make_user(
        user_id=50,
        company_id=1,
        role_name="admin",
    )

    result = rbac.list_roles(
        offset=1,
        limit=1,
        db=db,
        current_user=current_user,
    )

    assert len(result) == 1
    assert result[0].id == 2
