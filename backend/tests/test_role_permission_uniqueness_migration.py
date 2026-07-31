from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


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


class _Inspector:
    def __init__(
        self,
        primary_key: dict[str, Any],
    ) -> None:
        self.primary_key = primary_key

    def get_pk_constraint(
        self,
        table_name: str,
    ) -> dict[str, Any]:
        assert table_name == "role_permission"

        return self.primary_key


def _patch_inspector(
    monkeypatch,
    migration,
    primary_key: dict[str, Any],
) -> None:
    bind = object()

    monkeypatch.setattr(
        migration.op,
        "get_bind",
        lambda: bind,
    )

    monkeypatch.setattr(
        migration.sa,
        "inspect",
        lambda inspected_bind: (
            _Inspector(primary_key)
        )
        if inspected_bind is bind
        else None,
    )


def _capture_operations(
    monkeypatch,
    migration,
):
    statements: list[str] = []
    create_calls: list[
        tuple[str, str, list[str]]
    ] = []
    drop_calls: list[
        tuple[str, str, str]
    ] = []
    rename_calls: list[str] = []

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
            create_calls.append(
                (
                    name,
                    table,
                    list(columns),
                )
            )
        ),
    )

    monkeypatch.setattr(
        migration.op,
        "drop_constraint",
        lambda name, table, type_: (
            drop_calls.append(
                (
                    name,
                    table,
                    type_,
                )
            )
        ),
    )

    monkeypatch.setattr(
        migration,
        "_rename_primary_key",
        lambda current_name: (
            rename_calls.append(
                current_name
            )
        ),
    )

    return (
        statements,
        create_calls,
        drop_calls,
        rename_calls,
    )


def _assert_deduplication_statement(
    statements: list[str],
) -> None:
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


def test_upgrade_preserves_correct_primary_key(
    monkeypatch,
):
    migration = _load_migration()

    _patch_inspector(
        monkeypatch,
        migration,
        {
            "name": "pk_role_permission",
            "constrained_columns": [
                "role_id",
                "permission_id",
            ],
        },
    )

    (
        statements,
        create_calls,
        drop_calls,
        rename_calls,
    ) = _capture_operations(
        monkeypatch,
        migration,
    )

    migration.upgrade()

    _assert_deduplication_statement(
        statements
    )

    assert create_calls == []
    assert drop_calls == []
    assert rename_calls == []


def test_upgrade_renames_equivalent_primary_key(
    monkeypatch,
):
    migration = _load_migration()

    _patch_inspector(
        monkeypatch,
        migration,
        {
            "name": "legacy_role_permission_pk",
            "constrained_columns": [
                "role_id",
                "permission_id",
            ],
        },
    )

    (
        statements,
        create_calls,
        drop_calls,
        rename_calls,
    ) = _capture_operations(
        monkeypatch,
        migration,
    )

    migration.upgrade()

    _assert_deduplication_statement(
        statements
    )

    assert create_calls == []
    assert drop_calls == []
    assert rename_calls == [
        "legacy_role_permission_pk"
    ]


def test_upgrade_creates_missing_primary_key(
    monkeypatch,
):
    migration = _load_migration()

    _patch_inspector(
        monkeypatch,
        migration,
        {
            "name": None,
            "constrained_columns": [],
        },
    )

    (
        statements,
        create_calls,
        drop_calls,
        rename_calls,
    ) = _capture_operations(
        monkeypatch,
        migration,
    )

    migration.upgrade()

    _assert_deduplication_statement(
        statements
    )

    assert drop_calls == []
    assert rename_calls == []
    assert create_calls == [
        (
            "pk_role_permission",
            "role_permission",
            [
                "role_id",
                "permission_id",
            ],
        )
    ]


def test_upgrade_replaces_incorrect_primary_key(
    monkeypatch,
):
    migration = _load_migration()

    _patch_inspector(
        monkeypatch,
        migration,
        {
            "name": "legacy_incorrect_pk",
            "constrained_columns": [
                "role_id",
            ],
        },
    )

    (
        statements,
        create_calls,
        drop_calls,
        rename_calls,
    ) = _capture_operations(
        monkeypatch,
        migration,
    )

    migration.upgrade()

    _assert_deduplication_statement(
        statements
    )

    assert rename_calls == []

    assert drop_calls == [
        (
            "legacy_incorrect_pk",
            "role_permission",
            "primary",
        )
    ]

    assert create_calls == [
        (
            "pk_role_permission",
            "role_permission",
            [
                "role_id",
                "permission_id",
            ],
        )
    ]


def test_downgrade_preserves_baseline_primary_key(
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

    assert calls == []
