import importlib.util
from pathlib import Path

from core import authorization


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / (
        "35e2c3d4f5a6_"
        "migrate_global_admins_"
        "to_tenant_admins.py"
    )
)


def load_migration():
    spec = (
        importlib.util.spec_from_file_location(
            "tenant_admin_migration",
            MIGRATION_PATH,
        )
    )

    assert spec is not None
    assert spec.loader is not None

    module = (
        importlib.util.module_from_spec(
            spec
        )
    )

    spec.loader.exec_module(
        module
    )

    return module


def test_revision_contract():
    migration = load_migration()

    assert (
        migration.revision
        == "35e2c3d4f5a6"
    )

    assert (
        migration.down_revision
        == "24d1b2c3e4f5"
    )


def test_permission_contract_matches_runtime():
    migration = load_migration()

    assert (
        migration.TENANT_PERMISSION_PREFIXES
        == authorization.TENANT_PERMISSION_PREFIXES
    )

    assert (
        migration.TENANT_PERMISSION_NAMES
        == authorization.TENANT_PERMISSION_NAMES
    )

    assert (
        migration.TENANT_PERMISSION_DENYLIST
        == authorization.TENANT_PERMISSION_DENYLIST
    )

    assert (
        authorization.is_tenant_permission_name(
            "assistant:chat"
        )
        is True
    )

    assert (
        authorization.is_tenant_permission_name(
            "assistant:debug"
        )
        is False
    )

    assert (
        authorization.is_tenant_permission_name(
            "llm:update"
        )
        is False
    )


def test_marker_round_trip():
    migration = load_migration()

    marker = migration._build_marker(
        [21, 4, 4, 12]
    )

    assert marker == (
        "SEC4M_CREATED_FOR_USERS:"
        "4,12,21"
    )

    assert migration._parse_marker(
        marker
    ) == [4, 12, 21]


def test_migration_is_environment_independent():
    source = MIGRATION_PATH.read_text(
        encoding="utf-8"
    )

    assert "mehdi_avara" not in source
    assert "admin123" not in source
    assert (
        "preserved_user_id = min("
        in source
    )


def test_migration_revokes_authentication():
    source = MIGRATION_PATH.read_text(
        encoding="utf-8"
    )

    assert "auth_token_version" in source
    assert "auth_sessions" in source
    assert (
        "tenant_admin_scope_migration"
        in source
    )

    assert (
        "tenant_admin_scope_downgrade"
        in source
    )


def _compiled_string_constants(source: str) -> set[str]:
    import types

    values: set[str] = set()

    def collect(code):
        for value in code.co_consts:
            if isinstance(value, str):
                values.add(value)
            elif isinstance(value, types.CodeType):
                collect(value)

    collect(
        compile(
            source,
            str(MIGRATION_PATH),
            "exec",
        )
    )

    return values


def test_downgrade_has_safety_guards():
    source = MIGRATION_PATH.read_text(
        encoding="utf-8"
    )

    messages = _compiled_string_constants(
        source
    )

    assert any(
        "unmanaged company_admin roles exist"
        in message
        for message in messages
    )

    assert any(
        "administrator assignments changed"
        in message
        for message in messages
    )

    assert any(
        "a migrated user role changed"
        in message
        for message in messages
    )

    assert any(
        "already has global administrator access"
        in message
        for message in messages
    )


def test_no_persistent_audit_table_created():
    source = MIGRATION_PATH.read_text(
        encoding="utf-8"
    )

    assert "op.create_table(" not in source
    assert "op.add_column(" not in source
    assert "op.create_index(" not in source

def test_downgrade_does_not_require_unique_user_role():
    source = MIGRATION_PATH.read_text(
        encoding="utf-8"
    )

    assert "pg_insert" not in source
    assert "on_conflict_do_nothing" not in source
    assert "user_role.insert()" in source
