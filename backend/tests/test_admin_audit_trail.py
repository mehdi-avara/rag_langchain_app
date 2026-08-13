import inspect
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

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

from Models import AdminAuditLog
from Models.admin_audit import (
    _prevent_admin_audit_mutation,
)
from core.admin_audit import (
    append_admin_audit,
    sanitize_admin_audit_details,
)
from core.authorization import (
    is_tenant_permission_name,
)
from db import seed_rbac
from routs import company, rbac
from schemas.admin_audit import (
    AdminAuditLogOut,
)


class FakeDB:
    def __init__(self):
        self.added = []

    def add(self, value):
        self.added.append(
            value
        )


def test_admin_audit_is_append_only():
    with pytest.raises(
        ValueError,
        match="append-only",
    ):
        _prevent_admin_audit_mutation()


def test_audit_detail_sanitizer_removes_secrets():
    value = sanitize_admin_audit_details(
        {
            "username": "user@example.com",
            "password": "secret-value",
            "pw_hash": "hash-value",
            "refresh_token": "refresh-value",
            "refresh_jti_hash": "jti-value",
            "nested": {
                "api_secret": "secret",
                "safe": "value",
            },
        }
    )

    assert value == {
        "username": "user@example.com",
        "nested": {
            "safe": "value",
        },
    }


def test_append_admin_audit_sanitizes_details():
    db = FakeDB()

    result = append_admin_audit(
        db,
        company_id=7,
        actor_user_id=2,
        action="user.password_reset",
        target_type="user",
        target_id=9,
        details={
            "password": "must-not-survive",
            "safe": True,
        },
    )

    assert isinstance(
        result,
        AdminAuditLog,
    )

    assert result.company_id == 7
    assert result.actor_user_id == 2
    assert result.target_id == "9"
    assert result.details_json == {
        "safe": True
    }

    assert db.added == [
        result
    ]


def test_admin_audit_permission_is_tenant_scoped():
    assert (
        is_tenant_permission_name(
            "admin:audit:read"
        )
        is True
    )

    assert (
        is_tenant_permission_name(
            "assistant:debug"
        )
        is False
    )


def test_seed_declares_admin_audit_permission():
    source = inspect.getsource(
        seed_rbac.seed
    )

    assert (
        '"admin:audit:read"'
        in source
    )


def test_audit_schema_has_no_secret_fields():
    fields = set(
        AdminAuditLogOut.model_fields
    )

    assert fields == {
        "id",
        "company_id",
        "actor_user_id",
        "action",
        "target_type",
        "target_id",
        "details_json",
        "created_at",
    }

    for forbidden in {
        "password",
        "pw_hash",
        "token",
        "jti",
        "refresh_jti_hash",
    }:
        assert forbidden not in fields


def test_admin_audit_read_route_is_permission_guarded():
    source = inspect.getsource(
        rbac.list_admin_audit_logs
    )

    assert (
        "admin:audit:read"
        in source
    )

    assert (
        "AdminAuditLog.company_id"
        in source
    )

    assert (
        "current_user"
        in source
    )


def test_admin_audit_has_no_mutation_api():
    source = Path(
        rbac.__file__
    ).read_text(
        encoding="utf-8"
    )

    assert source.count(
        '"/audit-logs"'
    ) == 1

    assert (
        '@router.get(\n    "/audit-logs"'
        in source
    )


def test_expected_admin_events_are_instrumented():
    source = (
        Path(
            rbac.__file__
        ).read_text(
            encoding="utf-8"
        )
        + Path(
            company.__file__
        ).read_text(
            encoding="utf-8"
        )
    )

    for event_name in {
        "role.created",
        "role.updated",
        "role.deleted",
        "user.created",
        "user.updated",
        "user.roles_updated",
        "user.activated",
        "user.deactivated",
        "user.password_reset",
        "user.session_revoked",
        "user.sessions_revoked_all",
        "company.settings_updated",
    }:
        assert (
            f'"{event_name}"'
            in source
        )


def test_password_reset_source_never_audits_password():
    source = inspect.getsource(
        rbac.reset_company_user_password
    )

    audit_start = source.index(
        "append_admin_audit"
    )

    audit_source = source[
        audit_start:
    ]

    assert (
        "payload.new_password"
        not in audit_source
    )

    assert (
        "pw_hash"
        not in audit_source
    )


def test_session_audit_does_not_include_jti():
    source = (
        inspect.getsource(
            rbac.revoke_company_user_session
        )
        + inspect.getsource(
            rbac.revoke_all_company_user_sessions
        )
    )

    assert "jti" not in source
    assert "refresh_jti_hash" not in source


def test_admin_audit_migration_contract():
    migration = (
        Path(__file__)
        .resolve()
        .parents[1]
        / "alembic"
        / "versions"
        / (
            "46f3d4e5a6b7_"
            "add_admin_audit_trail.py"
        )
    )

    source = migration.read_text(
        encoding="utf-8"
    )

    assert (
        'revision: str = "46f3d4e5a6b7"'
        in source
    )

    assert (
        '"35e2c3d4f5a6"'
        in source
    )

    assert (
        '"admin_audit_logs"'
        in source
    )

    assert (
        "postgresql.JSONB"
        in source
    )

    assert (
        "ix_admin_audit_company_created"
        in source
    )

    assert (
        "ix_admin_audit_actor_created"
        in source
    )

    assert (
        "ix_admin_audit_action"
        in source
    )

    assert (
        "ix_admin_audit_target"
        in source
    )


def test_append_helper_does_not_commit():
    source = inspect.getsource(
        append_admin_audit
    )

    assert "db.commit" not in source
    assert "db.rollback" not in source


def test_audit_created_at_contract():
    audit = AdminAuditLog(
        company_id=1,
        action="user.updated",
        target_type="user",
        target_id="1",
        details_json={},
        created_at=datetime.utcnow(),
    )

    assert audit.created_at is not None
