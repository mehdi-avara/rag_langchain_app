"""Preserve legacy MR departments and add organization FK."""

from alembic import op
import sqlalchemy as sa


revision = "8c9d0e1f2a3b"
down_revision = "7b8c9d0e1f2a"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "material_requisitions",
        sa.Column(
            "legacy_department_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_material_requisitions_legacy_department_id",
        "material_requisitions",
        ["legacy_department_id"],
        unique=False,
    )

    op.execute(
        sa.text(
            """
            UPDATE material_requisitions
            SET legacy_department_id = department_id
            WHERE department_id IS NOT NULL
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE material_requisitions
            SET department_id = NULL
            WHERE department_id IS NOT NULL
            """
        )
    )

    op.create_foreign_key(
        op.f("fk_material_requisitions_department_org"),
        "material_requisitions",
        "organization_departments",
        ["department_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint(
        op.f("fk_material_requisitions_department_org"),
        "material_requisitions",
        type_="foreignkey",
    )

    op.execute(
        sa.text(
            """
            UPDATE material_requisitions
            SET department_id = COALESCE(
                department_id,
                legacy_department_id
            )
            WHERE legacy_department_id IS NOT NULL
            """
        )
    )

    op.drop_index(
        "ix_material_requisitions_legacy_department_id",
        table_name="material_requisitions",
    )

    op.drop_column(
        "material_requisitions",
        "legacy_department_id",
    )
