"""Add organization management foundation."""

from alembic import op
import sqlalchemy as sa


revision = "7b8c9d0e1f2a"
down_revision = "02f46a283a7b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "organization_departments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("parent_department_id", sa.Integer(), nullable=True),
        sa.Column("manager_user_id", sa.Integer(), nullable=True),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "parent_department_id IS NULL OR parent_department_id <> id",
            name=op.f("ck_organization_departments_not_self_parent"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_organization_departments_company_id_companies",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["manager_user_id"],
            ["users.id"],
            name="fk_organization_departments_manager_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["parent_department_id"],
            ["organization_departments.id"],
            name="fk_org_departments_parent",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_organization_departments",
        ),
        sa.UniqueConstraint(
            "company_id",
            "code",
            name="uq_organization_departments_company_code",
        ),
        sa.UniqueConstraint(
            "company_id",
            "name",
            name="uq_organization_departments_company_name",
        ),
    )

    op.create_index(
        "ix_organization_departments_company_id",
        "organization_departments",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_organization_departments_parent_department_id",
        "organization_departments",
        ["parent_department_id"],
        unique=False,
    )
    op.create_index(
        "ix_organization_departments_manager_user_id",
        "organization_departments",
        ["manager_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_organization_departments_is_active",
        "organization_departments",
        ["is_active"],
        unique=False,
    )

    op.create_table(
        "organization_positions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_manager",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_organization_positions_company_id_companies",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["organization_departments.id"],
            name="fk_org_positions_department",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_organization_positions",
        ),
        sa.UniqueConstraint(
            "company_id",
            "code",
            name="uq_organization_positions_company_code",
        ),
    )

    op.create_index(
        "ix_organization_positions_company_id",
        "organization_positions",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_organization_positions_department_id",
        "organization_positions",
        ["department_id"],
        unique=False,
    )
    op.create_index(
        "ix_organization_positions_is_active",
        "organization_positions",
        ["is_active"],
        unique=False,
    )

    op.create_table(
        "organization_user_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=False),
        sa.Column("position_id", sa.Integer(), nullable=True),
        sa.Column(
            "is_primary",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name=op.f("ck_organization_user_assignments_valid_dates"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_organization_user_assignments_company_id_companies",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["organization_departments.id"],
            name="fk_org_assignments_department",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["position_id"],
            ["organization_positions.id"],
            name="fk_org_assignments_position",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_organization_user_assignments_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_organization_user_assignments",
        ),
    )

    op.create_index(
        "ix_organization_user_assignments_company_id",
        "organization_user_assignments",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_organization_user_assignments_user_id",
        "organization_user_assignments",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_organization_user_assignments_department_id",
        "organization_user_assignments",
        ["department_id"],
        unique=False,
    )
    op.create_index(
        "ix_organization_user_assignments_position_id",
        "organization_user_assignments",
        ["position_id"],
        unique=False,
    )
    op.create_index(
        "ix_organization_user_assignments_is_active",
        "organization_user_assignments",
        ["is_active"],
        unique=False,
    )
    op.create_index(
        "uq_organization_assignments_active_primary_user",
        "organization_user_assignments",
        ["company_id", "user_id"],
        unique=True,
        postgresql_where=sa.text(
            "is_primary IS TRUE AND is_active IS TRUE"
        ),
    )


def downgrade():
    op.drop_index(
        "uq_organization_assignments_active_primary_user",
        table_name="organization_user_assignments",
    )
    op.drop_index(
        "ix_organization_user_assignments_is_active",
        table_name="organization_user_assignments",
    )
    op.drop_index(
        "ix_organization_user_assignments_position_id",
        table_name="organization_user_assignments",
    )
    op.drop_index(
        "ix_organization_user_assignments_department_id",
        table_name="organization_user_assignments",
    )
    op.drop_index(
        "ix_organization_user_assignments_user_id",
        table_name="organization_user_assignments",
    )
    op.drop_index(
        "ix_organization_user_assignments_company_id",
        table_name="organization_user_assignments",
    )
    op.drop_table("organization_user_assignments")

    op.drop_index(
        "ix_organization_positions_is_active",
        table_name="organization_positions",
    )
    op.drop_index(
        "ix_organization_positions_department_id",
        table_name="organization_positions",
    )
    op.drop_index(
        "ix_organization_positions_company_id",
        table_name="organization_positions",
    )
    op.drop_table("organization_positions")

    op.drop_index(
        "ix_organization_departments_is_active",
        table_name="organization_departments",
    )
    op.drop_index(
        "ix_organization_departments_manager_user_id",
        table_name="organization_departments",
    )
    op.drop_index(
        "ix_organization_departments_parent_department_id",
        table_name="organization_departments",
    )
    op.drop_index(
        "ix_organization_departments_company_id",
        table_name="organization_departments",
    )
    op.drop_table("organization_departments")
