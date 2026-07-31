import inspect
import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import BaseModel


os.environ.setdefault("POSTGRES_DB", "security_unit_test")
os.environ.setdefault("POSTGRES_USER", "security_unit_test")
os.environ.setdefault("POSTGRES_PASSWORD", "security_unit_test")
os.environ.setdefault("POSTGRES_IP", "127.0.0.1")
os.environ.setdefault("default_username", "test-admin")
os.environ.setdefault("default_password", "test-password")
os.environ.setdefault("default_firstname", "Test")
os.environ.setdefault("jwt_secret", "security-unit-test-secret")
os.environ.setdefault("openai_api_key", "test")
os.environ.setdefault("jina_api_key", "test")


from Models import Company, Permission, Role, User
from core import registration_security
from core.exceptions.error_codes import (
    REGISTRATION_CONFLICT,
    REGISTRATION_DISABLED,
    REGISTRATION_RATE_LIMITED,
)
from deps import require_permission
from routs import auth
from schemas.auth import RegisterRequest
from settings import Settings


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

    def first(self):
        if self.model is User:
            return self.db.existing_user

        if self.model is Company:
            return self.db.slug_collision

        if self.model is Role:
            return self.db.existing_role

        return None

    def all(self):
        if self.model is Permission:
            return list(
                self.db.permissions
            )

        return []


class FakeDB:
    def __init__(
        self,
        *,
        existing_user=None,
        existing_role=None,
        permissions=None,
    ):
        self.existing_user = existing_user
        self.existing_role = existing_role
        self.permissions = list(
            permissions or []
        )
        self.slug_collision = None
        self.added = []
        self.query_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self._next_id = 10

    def query(
        self,
        model,
    ):
        self.query_count += 1

        return FakeQuery(
            self,
            model,
        )

    def add(
        self,
        value,
    ):
        self.added.append(
            value
        )

    def flush(self):
        for value in self.added:
            if (
                hasattr(value, "id")
                and value.id is None
            ):
                value.id = self._next_id
                self._next_id += 1

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1

    def refresh(
        self,
        _value,
    ):
        return None


def permission(
    name: str,
) -> Permission:
    resource, action = (
        name.rsplit(":", 1)
        if ":" in name
        else (name, "read")
    )

    return Permission(
        name=name,
        resource=resource,
        action=action,
        description=name,
    )


@pytest.fixture(autouse=True)
def reset_registration_limiter():
    registration_security._reset_registration_rate_limits_for_tests()

    yield

    registration_security._reset_registration_rate_limits_for_tests()


def configure_open_registration(
    monkeypatch,
):
    monkeypatch.setattr(
        auth.settings,
        "self_registration_mode",
        "open",
    )

    monkeypatch.setattr(
        auth,
        "enforce_registration_rate_limit",
        lambda **_kwargs: None,
    )

    monkeypatch.setattr(
        auth.bcrypt,
        "hash",
        lambda _password: "test-password-hash",
    )

    monkeypatch.setattr(
        auth,
        "create_access_token",
        lambda _user: "test-access-token",
    )

    monkeypatch.setattr(
        auth,
        "create_refresh_token",
        lambda _user: "test-refresh-token",
    )


def registration_payload() -> RegisterRequest:
    return RegisterRequest(
        email="owner@example.test",
        password="valid-test-password",
        first_name="Owner",
        last_name="User",
        company_name="Example Company",
    )


def test_registration_policy_defaults_to_disabled():
    assert (
        Settings.model_fields[
            "self_registration_mode"
        ].default
        == "disabled"
    )


@pytest.mark.asyncio
async def test_public_registration_is_denied_before_database_access(
    monkeypatch,
):
    monkeypatch.setattr(
        auth.settings,
        "self_registration_mode",
        "disabled",
    )

    monkeypatch.setattr(
        auth,
        "enforce_registration_rate_limit",
        lambda **_kwargs: pytest.fail(
            "rate limiter must not run when registration is disabled"
        ),
    )

    db = FakeDB()

    with pytest.raises(
        HTTPException
    ) as exc:
        await auth.register(
            registration_payload(),
            db=db,
        )

    assert exc.value.status_code == 403
    assert (
        exc.value.detail["code"]
        == REGISTRATION_DISABLED
    )
    assert db.query_count == 0
    assert db.added == []
    assert db.commit_count == 0


@pytest.mark.asyncio
async def test_enabled_registration_creates_only_tenant_scoped_admin(
    monkeypatch,
):
    configure_open_registration(
        monkeypatch
    )

    monkeypatch.setattr(
        auth,
        "provision_company_defaults",
        lambda *_args, **_kwargs: None,
    )

    db = FakeDB(
        permissions=[
            permission("documents:create"),
            permission("company:update"),
            permission("users:read"),
            permission("roles:read"),
            permission("permissions:read"),
            permission("llm:read"),
            permission("llm:update"),
            permission("developer_docs:read"),
            permission("currencies:manage"),
            permission("exchange_rates:create"),
            permission("roles:create"),
            permission("roles:update"),
            permission("users:create"),
        ]
    )

    response = await auth.register(
        registration_payload(),
        db=db,
    )

    users = [
        value
        for value in db.added
        if isinstance(value, User)
    ]

    companies = [
        value
        for value in db.added
        if isinstance(value, Company)
    ]

    roles = [
        value
        for value in db.added
        if isinstance(value, Role)
    ]

    assert response.access_token == "test-access-token"
    assert response.refresh_token == "test-refresh-token"
    assert len(users) == 1
    assert len(companies) == 1
    assert len(roles) == 1

    user = users[0]
    company = companies[0]
    role = roles[0]

    assert user.company_id == company.id
    assert user.role == auth.TENANT_ADMIN_ROLE_NAME
    assert user.roles == [role]

    assert role.company_id == company.id
    assert role.is_system is False
    assert role.is_active is True

    permission_names = {
        item.name
        for item in role.permissions
    }

    assert permission_names == {
        "company:update",
        "documents:create",
        "permissions:read",
        "roles:read",
        "users:read",
    }

    assert not any(
        name.startswith("llm:")
        for name in permission_names
    )

    assert not any(
        name.startswith("developer_docs:")
        for name in permission_names
    )

    assert "currencies:manage" not in permission_names
    assert "exchange_rates:create" not in permission_names
    assert "roles:create" not in permission_names
    assert "roles:update" not in permission_names
    assert "users:create" not in permission_names

    assert (
        require_permission(
            "documents:create"
        )(user)
        is user
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        require_permission(
            "llm:update"
        )(user)

    assert exc.value.status_code == 403

    with pytest.raises(
        HTTPException
    ) as exc:
        require_permission(
            "roles:create"
        )(user)

    assert exc.value.status_code == 403

    assert db.commit_count == 1
    assert db.rollback_count == 0


@pytest.mark.asyncio
async def test_duplicate_registration_is_rejected_without_writes(
    monkeypatch,
):
    configure_open_registration(
        monkeypatch
    )

    db = FakeDB(
        existing_user=SimpleNamespace(
            id=1
        )
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        await auth.register(
            registration_payload(),
            db=db,
        )

    assert exc.value.status_code == 409
    assert (
        exc.value.detail["code"]
        == REGISTRATION_CONFLICT
    )
    assert db.added == []
    assert db.commit_count == 0


@pytest.mark.asyncio
async def test_registration_rolls_back_when_company_provisioning_fails(
    monkeypatch,
):
    configure_open_registration(
        monkeypatch
    )

    def fail_provisioning(
        *_args,
        **_kwargs,
    ):
        raise RuntimeError(
            "provisioning failed"
        )

    monkeypatch.setattr(
        auth,
        "provision_company_defaults",
        fail_provisioning,
    )

    db = FakeDB(
        permissions=[
            permission(
                "documents:create"
            )
        ]
    )

    with pytest.raises(
        RuntimeError,
        match="provisioning failed",
    ):
        await auth.register(
            registration_payload(),
            db=db,
        )

    assert db.commit_count == 0
    assert db.rollback_count == 1


def test_registration_rate_limit_is_per_email_and_redacts_identity(
    monkeypatch,
):
    monkeypatch.setattr(
        registration_security.settings,
        "self_registration_rate_window_seconds",
        60,
    )

    monkeypatch.setattr(
        registration_security.settings,
        "self_registration_rate_max_per_email",
        2,
    )

    monkeypatch.setattr(
        registration_security.settings,
        "self_registration_rate_max_global",
        10,
    )

    registration_security.enforce_registration_rate_limit(
        email="person@example.test"
    )

    registration_security.enforce_registration_rate_limit(
        email="person@example.test"
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        registration_security.enforce_registration_rate_limit(
            email="person@example.test"
        )

    assert exc.value.status_code == 429
    assert (
        exc.value.detail["code"]
        == REGISTRATION_RATE_LIMITED
    )
    assert exc.value.headers["Retry-After"] == "60"

    keys = list(
        registration_security._email_hits
    )

    assert len(keys) == 1
    assert len(keys[0]) == 64
    assert "@" not in keys[0]
    assert "person" not in keys[0]


def test_registration_rate_limit_has_global_anti_automation_cap(
    monkeypatch,
):
    monkeypatch.setattr(
        registration_security.settings,
        "self_registration_rate_window_seconds",
        60,
    )

    monkeypatch.setattr(
        registration_security.settings,
        "self_registration_rate_max_per_email",
        10,
    )

    monkeypatch.setattr(
        registration_security.settings,
        "self_registration_rate_max_global",
        2,
    )

    registration_security.enforce_registration_rate_limit(
        email="first@example.test"
    )

    registration_security.enforce_registration_rate_limit(
        email="second@example.test"
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        registration_security.enforce_registration_rate_limit(
            email="third@example.test"
        )

    assert exc.value.status_code == 429
    assert (
        exc.value.detail["code"]
        == REGISTRATION_RATE_LIMITED
    )


def test_register_source_has_no_system_admin_lookup():
    source = inspect.getsource(
        auth.register
    )

    assert "Role.company_id.is_(None)" not in source
    assert 'Role.name == "admin"' not in source


def test_registration_response_contract_remains_token_only():
    fields = set(
        auth.RegisterResponse.model_fields
    )

    assert fields == {
        "access_token",
        "refresh_token",
    }

    assert issubclass(
        auth.RegisterResponse,
        BaseModel,
    )
