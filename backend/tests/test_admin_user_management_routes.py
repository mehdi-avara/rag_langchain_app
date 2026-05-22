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

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def first(self):
        if self.model is User:
            return self.db.first_user
        if self.model is Role:
            return self.db.first_role
        return None

    def all(self):
        if self.model is User:
            return list(self.db.users)
        if self.model is Role:
            return list(self.db.roles)
        return []


class FakeDB:
    def __init__(self, users=None, roles=None, first_user=None, first_role=None):
        self.users = users or []
        self.roles = roles or []
        self.first_user = first_user
        self.first_role = first_role
        self.added = []
        self.committed = False
        self.refreshed = []

    def query(self, model):
        return FakeQuery(self, model)

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, User):
            self.users.append(obj)

    def commit(self):
        self.committed = True

    def refresh(self, obj):
        self.refreshed.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = 99
        if isinstance(obj, User) and getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.utcnow()


def make_role(role_id=1, name="user", active=True, permissions=None):
    role = Role(id=role_id, name=name, is_active=active)
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
    assert db.committed is True


def test_deactivate_self_is_rejected():
    user = make_user(user_id=5, company_id=1, role_name="admin")
    db = FakeDB(users=[user], first_user=user)

    with pytest.raises(HTTPException) as exc:
        rbac.deactivate_company_user(user_id=5, db=db, current_user=user)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Cannot deactivate your own account"


def test_deactivate_last_active_admin_is_rejected():
    current_user = make_user(user_id=1, company_id=1, role_name="admin")
    target_admin = make_user(user_id=2, company_id=1, role_name="admin")
    db = FakeDB(users=[target_admin], first_user=target_admin)

    with pytest.raises(HTTPException) as exc:
        rbac.deactivate_company_user(user_id=2, db=db, current_user=current_user)

    assert exc.value.status_code == 409
    assert exc.value.detail == "Cannot modify the last active admin of the company"


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
    assert exc.value.detail == "Cannot change your own roles"
