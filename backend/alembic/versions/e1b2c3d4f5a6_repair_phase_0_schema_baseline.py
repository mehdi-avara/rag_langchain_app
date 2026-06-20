"""repair_phase_0_schema_baseline

Revision ID: e1b2c3d4f5a6
Revises: 46a0f80fa1aa
Create Date: 2026-06-20
"""

from typing import Sequence, Union

from alembic import op

revision: str = "e1b2c3d4f5a6"
down_revision: Union[str, None] = "46a0f80fa1aa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_companies_base_currency_id_currencies'
                  AND conrelid = 'companies'::regclass
            ) THEN
                ALTER TABLE companies
                ADD CONSTRAINT fk_companies_base_currency_id_currencies
                FOREIGN KEY (base_currency_id)
                REFERENCES currencies(id)
                ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )

    op.execute("DROP INDEX IF EXISTS ix_roles_name")
    op.execute("CREATE INDEX IF NOT EXISTS ix_roles_name ON roles (name)")

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_document_intelligence_jobs_triggered_by_user_id
        ON document_intelligence_jobs (triggered_by_user_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_document_segments_job_id
        ON document_segments (job_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_purchase_orders_created_by_user_id
        ON purchase_orders (created_by_user_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_purchase_orders_supplier_id
        ON purchase_orders (supplier_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_intelligence_jobs_triggered_by_user_id")
    op.execute("DROP INDEX IF EXISTS ix_document_segments_job_id")
    op.execute("DROP INDEX IF EXISTS ix_purchase_orders_created_by_user_id")
    op.execute("DROP INDEX IF EXISTS ix_purchase_orders_supplier_id")
