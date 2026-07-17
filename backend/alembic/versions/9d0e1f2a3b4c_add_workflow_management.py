"""Add generic workflow management foundation."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "9d0e1f2a3b4c"
down_revision = "8c9d0e1f2a3b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workflow_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "company_id",
            "code",
            name="uq_wf_def_company_code",
        ),
    )
    op.create_index(
        "ix_wf_def_company_entity",
        "workflow_definitions",
        ["company_id", "entity_type"],
    )
    op.create_index(
        "ix_wf_def_company_active",
        "workflow_definitions",
        ["company_id", "is_active"],
    )

    op.create_table(
        "workflow_definition_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workflow_definition_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("published_by_user_id", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_workflow_definition_versions_valid_status",
        ),
        sa.CheckConstraint(
            "version_number >= 1",
            name="ck_workflow_definition_versions_valid_version_number",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_definition_id"],
            ["workflow_definitions.id"],
            name="fk_wf_versions_definition",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["published_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "workflow_definition_id",
            "version_number",
            name="uq_wf_ver_definition_number",
        ),
    )
    op.create_index(
        "ix_wf_ver_definition_status",
        "workflow_definition_versions",
        ["workflow_definition_id", "status"],
    )
    op.create_index(
        "uq_wf_ver_one_draft",
        "workflow_definition_versions",
        ["workflow_definition_id"],
        unique=True,
        postgresql_where=sa.text("status = 'draft'"),
    )
    op.create_index(
        "uq_wf_ver_one_published",
        "workflow_definition_versions",
        ["workflow_definition_id"],
        unique=True,
        postgresql_where=sa.text("status = 'published'"),
    )
    op.create_index(
        "ix_wf_ver_published_at",
        "workflow_definition_versions",
        ["published_at"],
    )

    op.create_table(
        "workflow_step_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_version_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "step_type",
            sa.String(length=20),
            nullable=False,
            server_default="approval",
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "is_start",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_terminal",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "assignee_type",
            sa.String(length=20),
            nullable=False,
            server_default="any",
        ),
        sa.Column("target_user_id", sa.Integer(), nullable=True),
        sa.Column("target_department_id", sa.Integer(), nullable=True),
        sa.Column("target_position_id", sa.Integer(), nullable=True),
        sa.Column("target_role_id", sa.Integer(), nullable=True),
        sa.Column(
            "required_approval_count",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("due_in_hours", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "step_type IN ('approval', 'task', 'end')",
            name="ck_workflow_step_definitions_valid_step_type",
        ),
        sa.CheckConstraint(
            "assignee_type IN "
            "('requester', 'user', 'department', 'position', 'role', 'any')",
            name="ck_workflow_step_definitions_valid_assignee_type",
        ),
        sa.CheckConstraint(
            """
            (
                assignee_type IN ('requester', 'any')
                AND target_user_id IS NULL
                AND target_department_id IS NULL
                AND target_position_id IS NULL
                AND target_role_id IS NULL
            )
            OR
            (
                assignee_type = 'user'
                AND target_user_id IS NOT NULL
                AND target_department_id IS NULL
                AND target_position_id IS NULL
                AND target_role_id IS NULL
            )
            OR
            (
                assignee_type = 'department'
                AND target_user_id IS NULL
                AND target_department_id IS NOT NULL
                AND target_position_id IS NULL
                AND target_role_id IS NULL
            )
            OR
            (
                assignee_type = 'position'
                AND target_user_id IS NULL
                AND target_department_id IS NULL
                AND target_position_id IS NOT NULL
                AND target_role_id IS NULL
            )
            OR
            (
                assignee_type = 'role'
                AND target_user_id IS NULL
                AND target_department_id IS NULL
                AND target_position_id IS NULL
                AND target_role_id IS NOT NULL
            )
            """,
            name="ck_workflow_step_definitions_valid_assignee_target",
        ),
        sa.CheckConstraint(
            """
            (
                step_type = 'end'
                AND is_terminal IS TRUE
            )
            OR
            (
                step_type <> 'end'
                AND is_terminal IS FALSE
            )
            """,
            name="ck_workflow_step_definitions_valid_terminal",
        ),
        sa.CheckConstraint(
            "sort_order >= 0",
            name="ck_workflow_step_definitions_valid_sort_order",
        ),
        sa.CheckConstraint(
            "required_approval_count >= 1",
            name="ck_workflow_step_definitions_valid_approval_count",
        ),
        sa.CheckConstraint(
            "due_in_hours IS NULL OR due_in_hours > 0",
            name="ck_workflow_step_definitions_valid_due_hours",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_version_id"],
            ["workflow_definition_versions.id"],
            name="fk_wf_steps_version",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            name="fk_wf_steps_target_user",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["target_department_id"],
            ["organization_departments.id"],
            name="fk_wf_steps_target_department",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_position_id"],
            ["organization_positions.id"],
            name="fk_wf_steps_target_position",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_role_id"],
            ["roles.id"],
            name="fk_wf_steps_target_role",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workflow_version_id",
            "code",
            name="uq_wf_step_version_code",
        ),
    )
    op.create_index(
        "ix_wf_step_version_order",
        "workflow_step_definitions",
        ["workflow_version_id", "sort_order"],
    )
    op.create_index(
        "ix_wf_step_assignee",
        "workflow_step_definitions",
        [
            "assignee_type",
            "target_user_id",
            "target_department_id",
            "target_position_id",
            "target_role_id",
        ],
    )
    op.create_index(
        "uq_wf_step_version_start_one",
        "workflow_step_definitions",
        ["workflow_version_id"],
        unique=True,
        postgresql_where=sa.text("is_start IS TRUE"),
    )
    op.create_index(
        "ix_wf_step_version_terminal",
        "workflow_step_definitions",
        ["workflow_version_id", "is_terminal"],
    )

    op.create_table(
        "workflow_transition_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_version_id", sa.Integer(), nullable=False),
        sa.Column("from_step_id", sa.Integer(), nullable=False),
        sa.Column("to_step_id", sa.Integer(), nullable=False),
        sa.Column("action_key", sa.String(length=80), nullable=False),
        sa.Column("action_label", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "require_comment",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "from_step_id <> to_step_id",
            name="ck_workflow_transition_definitions_distinct_steps",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_version_id"],
            ["workflow_definition_versions.id"],
            name="fk_wf_transitions_version",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["from_step_id"],
            ["workflow_step_definitions.id"],
            name="fk_wf_transitions_from_step",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["to_step_id"],
            ["workflow_step_definitions.id"],
            name="fk_wf_transitions_to_step",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "workflow_version_id",
            "from_step_id",
            "action_key",
            name="uq_wf_transition_from_action",
        ),
    )
    op.create_index(
        "ix_wf_transition_version_from",
        "workflow_transition_definitions",
        ["workflow_version_id", "from_step_id"],
    )
    op.create_index(
        "ix_wf_transition_to",
        "workflow_transition_definitions",
        ["to_step_id"],
    )

    op.create_table(
        "workflow_instances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("workflow_definition_id", sa.Integer(), nullable=False),
        sa.Column("workflow_version_id", sa.Integer(), nullable=False),
        sa.Column("current_step_definition_id", sa.Integer(), nullable=True),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "context_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("started_by_user_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'completed', 'cancelled')",
            name="ck_workflow_instances_valid_status",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_definition_id"],
            ["workflow_definitions.id"],
            name="fk_wf_instances_definition",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_version_id"],
            ["workflow_definition_versions.id"],
            name="fk_wf_instances_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["current_step_definition_id"],
            ["workflow_step_definitions.id"],
            name="fk_wf_instances_current_step",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["started_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_wf_instance_company_status",
        "workflow_instances",
        ["company_id", "status"],
    )
    op.create_index(
        "ix_wf_instance_entity",
        "workflow_instances",
        ["company_id", "entity_type", "entity_id"],
    )
    op.create_index(
        "ix_wf_instance_definition",
        "workflow_instances",
        ["workflow_definition_id"],
    )
    op.create_index(
        "uq_wf_instance_active_entity",
        "workflow_instances",
        [
            "company_id",
            "workflow_definition_id",
            "entity_type",
            "entity_id",
        ],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "workflow_step_instances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_instance_id", sa.Integer(), nullable=False),
        sa.Column("step_definition_id", sa.Integer(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("assignee_type", sa.String(length=20), nullable=False),
        sa.Column("assigned_user_id", sa.Integer(), nullable=True),
        sa.Column("assigned_department_id", sa.Integer(), nullable=True),
        sa.Column("assigned_position_id", sa.Integer(), nullable=True),
        sa.Column("assigned_role_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("completed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(length=80), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN "
            "('pending', 'active', 'completed', 'skipped', 'cancelled')",
            name="ck_workflow_step_instances_valid_status",
        ),
        sa.CheckConstraint(
            "sequence_number >= 1",
            name="ck_workflow_step_instances_valid_sequence",
        ),
        sa.CheckConstraint(
            "assignee_type IN "
            "('requester', 'user', 'department', 'position', 'role', 'any')",
            name="ck_workflow_step_instances_valid_assignee_type",
        ),
        sa.CheckConstraint(
            """
            (
                assignee_type IN ('requester', 'any')
                AND assigned_user_id IS NULL
                AND assigned_department_id IS NULL
                AND assigned_position_id IS NULL
                AND assigned_role_id IS NULL
            )
            OR
            (
                assignee_type = 'user'
                AND assigned_user_id IS NOT NULL
                AND assigned_department_id IS NULL
                AND assigned_position_id IS NULL
                AND assigned_role_id IS NULL
            )
            OR
            (
                assignee_type = 'department'
                AND assigned_user_id IS NULL
                AND assigned_department_id IS NOT NULL
                AND assigned_position_id IS NULL
                AND assigned_role_id IS NULL
            )
            OR
            (
                assignee_type = 'position'
                AND assigned_user_id IS NULL
                AND assigned_department_id IS NULL
                AND assigned_position_id IS NOT NULL
                AND assigned_role_id IS NULL
            )
            OR
            (
                assignee_type = 'role'
                AND assigned_user_id IS NULL
                AND assigned_department_id IS NULL
                AND assigned_position_id IS NULL
                AND assigned_role_id IS NOT NULL
            )
            """,
            name="ck_workflow_step_instances_valid_assignee_target",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR started_at IS NULL "
            "OR completed_at >= started_at",
            name="ck_workflow_step_instances_valid_dates",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_instance_id"],
            ["workflow_instances.id"],
            name="fk_wf_step_instances_instance",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["step_definition_id"],
            ["workflow_step_definitions.id"],
            name="fk_wf_step_instances_definition",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_department_id"],
            ["organization_departments.id"],
            name="fk_wf_step_inst_department",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_position_id"],
            ["organization_positions.id"],
            name="fk_wf_step_inst_position",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_role_id"],
            ["roles.id"],
            name="fk_wf_step_inst_role",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["completed_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "workflow_instance_id",
            "sequence_number",
            name="uq_wf_step_instance_sequence",
        ),
    )
    op.create_index(
        "ix_wf_step_instance_instance_status",
        "workflow_step_instances",
        ["workflow_instance_id", "status"],
    )
    op.create_index(
        "ix_wf_step_instance_assignee",
        "workflow_step_instances",
        [
            "assignee_type",
            "assigned_user_id",
            "assigned_department_id",
            "assigned_position_id",
            "assigned_role_id",
        ],
    )
    op.create_index(
        "uq_wf_step_instance_active",
        "workflow_step_instances",
        ["workflow_instance_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "workflow_instance_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("workflow_instance_id", sa.Integer(), nullable=False),
        sa.Column("step_instance_id", sa.Integer(), nullable=True),
        sa.Column("file_asset_id", sa.Integer(), nullable=False),
        sa.Column("attached_by_user_id", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_instance_id"],
            ["workflow_instances.id"],
            name="fk_wf_files_instance",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["step_instance_id"],
            ["workflow_step_instances.id"],
            name="fk_wf_files_step_instance",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["file_asset_id"],
            ["file_assets.id"],
            name="fk_wf_files_asset",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["attached_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "workflow_instance_id",
            "file_asset_id",
            name="uq_wf_file_instance_asset",
        ),
    )
    op.create_index(
        "ix_wf_file_instance",
        "workflow_instance_files",
        ["workflow_instance_id"],
    )
    op.create_index(
        "ix_wf_file_step_instance",
        "workflow_instance_files",
        ["step_instance_id"],
    )
    op.create_index(
        "ix_wf_file_asset",
        "workflow_instance_files",
        ["file_asset_id"],
    )

    op.create_table(
        "workflow_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("workflow_instance_id", sa.Integer(), nullable=False),
        sa.Column("step_instance_id", sa.Integer(), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("from_status", sa.String(length=40), nullable=True),
        sa.Column("to_status", sa.String(length=40), nullable=True),
        sa.Column("action_key", sa.String(length=80), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "details_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_instance_id"],
            ["workflow_instances.id"],
            name="fk_wf_audit_instance",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["step_instance_id"],
            ["workflow_step_instances.id"],
            name="fk_wf_audit_step_instance",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_wf_audit_company_created",
        "workflow_audit_logs",
        ["company_id", "created_at"],
    )
    op.create_index(
        "ix_wf_audit_instance_created",
        "workflow_audit_logs",
        ["workflow_instance_id", "created_at"],
    )
    op.create_index(
        "ix_wf_audit_step_instance",
        "workflow_audit_logs",
        ["step_instance_id"],
    )
    op.create_index(
        "ix_wf_audit_event_type",
        "workflow_audit_logs",
        ["event_type"],
    )


def downgrade():
    op.drop_table("workflow_audit_logs")
    op.drop_table("workflow_instance_files")
    op.drop_table("workflow_step_instances")
    op.drop_table("workflow_instances")
    op.drop_table("workflow_transition_definitions")
    op.drop_table("workflow_step_definitions")
    op.drop_table("workflow_definition_versions")
    op.drop_table("workflow_definitions")
