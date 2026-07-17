"""Backfill assistant permissions for the built-in user role."""

from alembic import op
import sqlalchemy as sa


revision = "02f46a283a7b"
down_revision = "344b0efc5b5f"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        sa.text(
            """
            INSERT INTO role_permission (role_id, permission_id)
            SELECT role_row.id, permission_row.id
            FROM roles AS role_row
            JOIN permissions AS permission_row
              ON permission_row.name IN (
                  'assistant:chat',
                  'assistant:draft',
                  'assistant:files'
              )
            WHERE role_row.name = 'user'
              AND role_row.company_id IS NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM role_permission AS existing_mapping
                  WHERE existing_mapping.role_id = role_row.id
                    AND existing_mapping.permission_id = permission_row.id
              )
            """
        )
    )


def downgrade():
    pass
