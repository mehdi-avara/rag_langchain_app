from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_migration():
    versions_dir = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
    )

    matches = list(
        versions_dir.glob(
            "*_backfill_assistant_permissions_to_user_role.py"
        )
    )

    assert len(matches) == 1

    migration_path = matches[0]
    spec = importlib.util.spec_from_file_location(
        "assistant_permission_backfill_migration",
        migration_path,
    )

    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def test_upgrade_backfills_assistant_permissions_idempotently(
    monkeypatch,
):
    migration = _load_migration()
    statements = []

    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda statement: statements.append(str(statement)),
    )

    migration.upgrade()

    assert len(statements) == 1

    sql = " ".join(statements[0].split())

    assert "INSERT INTO role_permission" in sql
    assert "role_row.name = 'user'" in sql
    assert "role_row.company_id IS NULL" in sql
    assert "'assistant:chat'" in sql
    assert "'assistant:draft'" in sql
    assert "'assistant:files'" in sql
    assert "NOT EXISTS" in sql
    assert "existing_mapping.role_id = role_row.id" in sql
    assert (
        "existing_mapping.permission_id = permission_row.id"
        in sql
    )
    assert "ON CONFLICT" not in sql


def test_downgrade_preserves_runtime_role_assignments(
    monkeypatch,
):
    migration = _load_migration()
    statements = []

    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda statement: statements.append(str(statement)),
    )

    migration.downgrade()

    assert statements == []
