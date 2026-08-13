import inspect
import os
from pathlib import Path

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

from core import admin_summary
from core.authorization import (
    is_tenant_permission_name,
)
from db import seed_rbac
from routs import rbac
from schemas.admin_summary import (
    AdminSummaryAuditOut,
    AdminSummaryCompanyOut,
    AdminSummaryOut,
    AdminSummaryRolesOut,
    AdminSummarySessionsOut,
    AdminSummaryUsersOut,
)


def test_admin_summary_permission_is_tenant_scoped():
    assert (
        is_tenant_permission_name(
            "admin:summary:read"
        )
        is True
    )

    assert (
        is_tenant_permission_name(
            "assistant:debug"
        )
        is False
    )


def test_seed_declares_admin_summary_permission():
    source = inspect.getsource(
        seed_rbac.seed
    )

    assert (
        '"admin:summary:read"'
        in source
    )


def test_admin_summary_route_permission():
    source = inspect.getsource(
        rbac.get_admin_summary
    )

    assert (
        "admin:summary:read"
        in source
    )

    assert (
        "_require_company_id"
        in source
    )

    assert (
        "Company.id"
        in source
    )

    assert (
        "build_admin_summary"
        in source
    )


def test_admin_summary_schema_contract():
    assert set(
        AdminSummaryUsersOut.model_fields
    ) == {
        "total",
        "active",
        "inactive",
    }

    assert set(
        AdminSummaryRolesOut.model_fields
    ) == {
        "total_custom",
        "active_custom",
        "inactive_custom",
    }

    assert set(
        AdminSummarySessionsOut.model_fields
    ) == {
        "total",
        "active",
        "revoked",
        "expired",
        "stale",
    }

    assert set(
        AdminSummaryAuditOut.model_fields
    ) == {
        "total",
        "last_24_hours",
        "latest_activity_at",
    }

    assert set(
        AdminSummaryCompanyOut.model_fields
    ) == {
        "id",
        "name",
    }

    assert set(
        AdminSummaryOut.model_fields
    ) == {
        "users",
        "roles",
        "sessions",
        "audit",
        "company",
    }


def test_admin_summary_has_no_sensitive_output_fields():
    schemas = (
        AdminSummaryUsersOut,
        AdminSummaryRolesOut,
        AdminSummarySessionsOut,
        AdminSummaryAuditOut,
        AdminSummaryCompanyOut,
        AdminSummaryOut,
    )

    forbidden = {
        "username",
        "email",
        "password",
        "pw_hash",
        "token",
        "refresh_token",
        "jti",
        "refresh_jti_hash",
        "notification_token",
    }

    for schema in schemas:
        fields = {
            name.casefold()
            for name
            in schema.model_fields
        }

        assert not (
            fields & forbidden
        )


def test_summary_service_is_tenant_scoped():
    source = inspect.getsource(
        admin_summary.build_admin_summary
    )

    assert (
        "User.company_id == company_id"
        in source
    )

    assert (
        "Role.company_id == company_id"
        in source
    )

    assert (
        "AuthSession.company_id"
        in source
    )

    assert (
        "AdminAuditLog.company_id"
        in source
    )


def test_summary_session_classification_contract():
    source = inspect.getsource(
        admin_summary.build_admin_summary
    )

    assert (
        "AuthSession.revoked_at"
        in source
    )

    assert (
        "AuthSession.expires_at"
        in source
    )

    assert (
        "AuthSession.token_version"
        in source
    )

    assert (
        "User.auth_token_version"
        in source
    )

    assert (
        "User.is_active"
        in source
    )

    assert (
        '"stale"'
        in source
    )

    assert (
        "classification is incomplete"
        in source
    )


def test_custom_role_counts_exclude_reserved_company_admin():
    source = inspect.getsource(
        admin_summary.build_admin_summary
    )

    assert (
        "TENANT_ADMIN_ROLE_NAME"
        in source
    )

    assert (
        "Role.is_system.is_(False)"
        in source
    )


def test_admin_summary_service_never_reads_session_secret():
    source = Path(
        admin_summary.__file__
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "refresh_jti_hash"
        not in source
    )

    assert (
        "pw_hash"
        not in source
    )

    assert (
        "notification_token"
        not in source
    )


def test_admin_summary_is_read_only():
    source = (
        inspect.getsource(
            rbac.get_admin_summary
        )
        + inspect.getsource(
            admin_summary.build_admin_summary
        )
    )

    for mutation in {
        "db.add(",
        "db.delete(",
        "db.commit(",
        "db.flush(",
        "db.rollback(",
    }:
        assert mutation not in source
