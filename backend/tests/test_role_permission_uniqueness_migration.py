from __future__ import annotations

import importlib.util
from pathlib import Path


BACKEND_ROOT = Path(__file__).parents[1]


def _load_migration():
    matches = list(
        (
            BACKEND_ROOT
            / "alembic"
            / "versions"
        ).glob(
            "*_restore_role_permission_"
            "primary_key.py"
        )
    )

    assert len(matches) == 1

    spec = importlib.util.spec_from_file_location(
        "role_permission_integrity_migration",
        matches[0],
    )

    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def test_upgrade_deduplicates_before_restoring_primary_key(
    monkeypatch,
):
    migration = _load_migration()
    statements: list[str] = []
    primary_key_calls: list[
        tuple[str, str, list[str]]
    ] = []

    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda statement: statements.append(
            str(statement)
        ),
    )

    monkeypatch.setattr(
        migration.op,
        "create_primary_key",
        lambda name, table, columns: (
            primary_key_calls.append(
                (
                    name,
                    table,
                    list(columns),
                )
            )
        ),
    )

    migration.upgrade()

    assert len(statements) == 1

    sql = " ".join(
        statements[0].split()
    )

    assert (
        "DELETE FROM role_permission AS duplicate"
        in sql
    )
    assert (
        "USING role_permission AS keeper"
        in sql
    )
    assert (
        "duplicate.role_id = keeper.role_id"
        in sql
    )
    assert (
        "duplicate.permission_id = "
        "keeper.permission_id"
        in sql
    )
    assert (
        "duplicate.ctid > keeper.ctid"
        in sql
    )

    assert primary_key_calls == [
        (
            "pk_role_permission",
            "role_permission",
            [
                "role_id",
                "permission_id",
            ],
        )
    ]


def test_downgrade_drops_only_restored_constraint(
    monkeypatch,
):
    migration = _load_migration()
    calls: list[
        tuple[str, str, str]
    ] = []

    monkeypatch.setattr(
        migration.op,
        "drop_constraint",
        lambda name, table, type_: (
            calls.append(
                (
                    name,
                    table,
                    type_,
                )
            )
        ),
    )

    migration.downgrade()

    assert calls == [
        (
            "pk_role_permission",
            "role_permission",
            "primary",
        )
    ]
