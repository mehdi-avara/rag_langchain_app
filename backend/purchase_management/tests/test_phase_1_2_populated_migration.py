from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine, text


DATABASE_URL = os.getenv(
    "PHASE_1_2_POPULATED_TEST_DATABASE_URL"
)

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason=(
        "PHASE_1_2_POPULATED_TEST_DATABASE_URL "
        "is not configured"
    ),
)

BACKEND_ROOT = Path(__file__).parents[2]


def _database_name(database_url: str) -> str:
    return urlparse(database_url).path.lstrip("/")


def _snapshot(engine):
    with engine.connect() as connection:
        return connection.execute(
            text(
                """
                SELECT
                    COUNT(*) AS order_count,
                    COUNT(DISTINCT line.id)
                        AS line_count,
                    COUNT(DISTINCT phase.id)
                        AS phase_count,
                    COUNT(DISTINCT allocation.id)
                        AS allocation_count,
                    COUNT(DISTINCT cost.id)
                        AS cost_count,
                    COUNT(DISTINCT receipt.id)
                        AS receipt_link_count
                FROM purchase_orders AS po
                LEFT JOIN purchase_order_lines AS line
                  ON line.purchase_order_id = po.id
                LEFT JOIN purchase_phases AS phase
                  ON phase.purchase_order_id = po.id
                LEFT JOIN purchase_phase_allocations
                    AS allocation
                  ON allocation.phase_id = phase.id
                LEFT JOIN purchase_order_costs AS cost
                  ON cost.purchase_order_id = po.id
                LEFT JOIN purchase_order_receipt_links
                    AS receipt
                  ON receipt.purchase_order_id = po.id
                """
            )
        ).one()


def _run_alembic(
    database_url: str,
    command: str,
    revision: str,
) -> None:
    database_name = _database_name(
        database_url
    )
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": database_url,
            "DB_NAME": database_name,
            "DATABASE_NAME": database_name,
            "POSTGRES_DB": database_name,
        }
    )

    subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            command,
            revision,
        ],
        cwd=BACKEND_ROOT,
        env=environment,
        check=True,
    )


def test_populated_database_roundtrip_preserves_purchase_data():
    assert DATABASE_URL is not None

    database_name = _database_name(
        DATABASE_URL
    )

    assert database_name != "rag"
    assert (
        database_name.startswith(
            "rag_phase_1_2_"
        )
        or database_name.startswith(
            "rag_p12_"
        )
    )

    engine = create_engine(
        DATABASE_URL,
        future=True,
    )

    before = _snapshot(engine)

    _run_alembic(
        DATABASE_URL,
        "downgrade",
        "b1c2d3e4f5a6",
    )

    after_downgrade = _snapshot(engine)

    assert after_downgrade == before

    _run_alembic(
        DATABASE_URL,
        "upgrade",
        "head",
    )

    after_upgrade = _snapshot(engine)

    assert after_upgrade == before

    with engine.connect() as connection:
        permission_count = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM permissions
                WHERE name = (
                    'purchase_management:'
                    'phases:split'
                )
                """
            )
        ).scalar_one()

        assignment_count = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM role_permission AS assignment
                JOIN roles AS role
                  ON role.id = assignment.role_id
                JOIN permissions AS permission
                  ON permission.id =
                     assignment.permission_id
                WHERE role.name = 'admin'
                  AND role.company_id IS NULL
                  AND permission.name = (
                      'purchase_management:'
                      'phases:split'
                  )
                """
            )
        ).scalar_one()

        duplicate_pair_count = (
            connection.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM (
                        SELECT
                            role_id,
                            permission_id
                        FROM role_permission
                        GROUP BY
                            role_id,
                            permission_id
                        HAVING COUNT(*) > 1
                    ) AS duplicate_pair
                    """
                )
            ).scalar_one()
        )

        primary_key_definition = (
            connection.execute(
                text(
                    """
                    SELECT pg_get_constraintdef(
                        constraint_row.oid
                    )
                    FROM pg_constraint
                        AS constraint_row
                    JOIN pg_class AS table_row
                      ON table_row.oid =
                         constraint_row.conrelid
                    WHERE table_row.relname =
                          'role_permission'
                      AND constraint_row.conname =
                          'pk_role_permission'
                      AND constraint_row.contype =
                          'p'
                    """
                )
            ).scalar_one()
        )

    assert permission_count == 1
    assert assignment_count == 1
    assert duplicate_pair_count == 0
    assert primary_key_definition == (
        "PRIMARY KEY "
        "(role_id, permission_id)"
    )
