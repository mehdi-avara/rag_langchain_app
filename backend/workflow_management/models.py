from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    event,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from db.base import Base


class WorkflowVersionStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class WorkflowStepType(str, enum.Enum):
    APPROVAL = "approval"
    TASK = "task"
    END = "end"


class WorkflowAssigneeType(str, enum.Enum):
    REQUESTER = "requester"
    USER = "user"
    DEPARTMENT = "department"
    POSITION = "position"
    ROLE = "role"
    ANY = "any"


class WorkflowInstanceStatus(str, enum.Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class WorkflowStepInstanceStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class WorkflowDefinition(Base):
    __tablename__ = "workflow_definitions"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "code",
            name="uq_wf_def_company_code",
        ),
        Index(
            "ix_wf_def_company_entity",
            "company_id",
            "entity_type",
        ),
        Index(
            "ix_wf_def_company_active",
            "company_id",
            "is_active",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(
        Integer,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    code = Column(String(80), nullable=False)
    name = Column(String(255), nullable=False)
    entity_type = Column(String(80), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    company = relationship("Company")
    created_by = relationship(
        "User",
        foreign_keys=[created_by_user_id],
    )
    versions = relationship(
        "WorkflowDefinitionVersion",
        back_populates="definition",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="WorkflowDefinitionVersion.version_number",
    )
    instances = relationship(
        "WorkflowInstance",
        back_populates="definition",
    )


class WorkflowDefinitionVersion(Base):
    __tablename__ = "workflow_definition_versions"
    __table_args__ = (
        UniqueConstraint(
            "workflow_definition_id",
            "version_number",
            name="uq_wf_ver_definition_number",
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="valid_status",
        ),
        CheckConstraint(
            "version_number >= 1",
            name="valid_version_number",
        ),
        Index(
            "ix_wf_ver_definition_status",
            "workflow_definition_id",
            "status",
        ),
        Index(
            "uq_wf_ver_one_draft",
            "workflow_definition_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
        Index(
            "uq_wf_ver_one_published",
            "workflow_definition_id",
            unique=True,
            postgresql_where=text("status = 'published'"),
        ),
        Index(
            "ix_wf_ver_published_at",
            "published_at",
        ),
    )

    id = Column(Integer, primary_key=True)
    workflow_definition_id = Column(
        Integer,
        ForeignKey(
            "workflow_definitions.id",
            name="fk_wf_versions_definition",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    version_number = Column(Integer, nullable=False)
    status = Column(
        String(20),
        nullable=False,
        default=WorkflowVersionStatus.DRAFT.value,
    )
    notes = Column(Text, nullable=True)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    published_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    published_at = Column(DateTime, nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    definition = relationship(
        "WorkflowDefinition",
        back_populates="versions",
    )
    created_by = relationship(
        "User",
        foreign_keys=[created_by_user_id],
    )
    published_by = relationship(
        "User",
        foreign_keys=[published_by_user_id],
    )
    steps = relationship(
        "WorkflowStepDefinition",
        back_populates="version",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="WorkflowStepDefinition.sort_order",
    )
    transitions = relationship(
        "WorkflowTransitionDefinition",
        back_populates="version",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="WorkflowTransitionDefinition.id",
    )
    instances = relationship(
        "WorkflowInstance",
        back_populates="version",
    )


class WorkflowStepDefinition(Base):
    __tablename__ = "workflow_step_definitions"
    __table_args__ = (
        UniqueConstraint(
            "workflow_version_id",
            "code",
            name="uq_wf_step_version_code",
        ),
        CheckConstraint(
            "step_type IN ('approval', 'task', 'end')",
            name="valid_step_type",
        ),
        CheckConstraint(
            "assignee_type IN "
            "('requester', 'user', 'department', 'position', 'role', 'any')",
            name="valid_assignee_type",
        ),
        CheckConstraint(
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
            name="valid_assignee_target",
        ),
        CheckConstraint(
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
            name="valid_terminal",
        ),
        CheckConstraint(
            "sort_order >= 0",
            name="valid_sort_order",
        ),
        CheckConstraint(
            "required_approval_count >= 1",
            name="valid_approval_count",
        ),
        CheckConstraint(
            "due_in_hours IS NULL OR due_in_hours > 0",
            name="valid_due_hours",
        ),
        Index(
            "ix_wf_step_version_order",
            "workflow_version_id",
            "sort_order",
        ),
        Index(
            "ix_wf_step_assignee",
            "assignee_type",
            "target_user_id",
            "target_department_id",
            "target_position_id",
            "target_role_id",
        ),
        Index(
            "uq_wf_step_version_start_one",
            "workflow_version_id",
            unique=True,
            postgresql_where=text("is_start IS TRUE"),
        ),
        Index(
            "ix_wf_step_version_terminal",
            "workflow_version_id",
            "is_terminal",
        ),
    )

    id = Column(Integer, primary_key=True)
    workflow_version_id = Column(
        Integer,
        ForeignKey(
            "workflow_definition_versions.id",
            name="fk_wf_steps_version",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    code = Column(String(80), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    step_type = Column(
        String(20),
        nullable=False,
        default=WorkflowStepType.APPROVAL.value,
    )
    sort_order = Column(Integer, nullable=False, default=0)
    is_start = Column(Boolean, nullable=False, default=False)
    is_terminal = Column(Boolean, nullable=False, default=False)
    assignee_type = Column(
        String(20),
        nullable=False,
        default=WorkflowAssigneeType.ANY.value,
    )
    target_user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            name="fk_wf_steps_target_user",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    target_department_id = Column(
        Integer,
        ForeignKey(
            "organization_departments.id",
            name="fk_wf_steps_target_department",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    target_position_id = Column(
        Integer,
        ForeignKey(
            "organization_positions.id",
            name="fk_wf_steps_target_position",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    target_role_id = Column(
        Integer,
        ForeignKey(
            "roles.id",
            name="fk_wf_steps_target_role",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    required_approval_count = Column(
        Integer,
        nullable=False,
        default=1,
    )
    due_in_hours = Column(Integer, nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    version = relationship(
        "WorkflowDefinitionVersion",
        back_populates="steps",
    )
    target_user = relationship(
        "User",
        foreign_keys=[target_user_id],
    )
    target_department = relationship(
        "OrganizationDepartment",
        foreign_keys=[target_department_id],
    )
    target_position = relationship(
        "OrganizationPosition",
        foreign_keys=[target_position_id],
    )
    target_role = relationship(
        "Role",
        foreign_keys=[target_role_id],
    )
    outgoing_transitions = relationship(
        "WorkflowTransitionDefinition",
        back_populates="from_step",
        foreign_keys="WorkflowTransitionDefinition.from_step_id",
    )
    incoming_transitions = relationship(
        "WorkflowTransitionDefinition",
        back_populates="to_step",
        foreign_keys="WorkflowTransitionDefinition.to_step_id",
    )


class WorkflowTransitionDefinition(Base):
    __tablename__ = "workflow_transition_definitions"
    __table_args__ = (
        UniqueConstraint(
            "workflow_version_id",
            "from_step_id",
            "action_key",
            name="uq_wf_transition_from_action",
        ),
        CheckConstraint(
            "from_step_id <> to_step_id",
            name="distinct_steps",
        ),
        Index(
            "ix_wf_transition_version_from",
            "workflow_version_id",
            "from_step_id",
        ),
        Index(
            "ix_wf_transition_to",
            "to_step_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    workflow_version_id = Column(
        Integer,
        ForeignKey(
            "workflow_definition_versions.id",
            name="fk_wf_transitions_version",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    from_step_id = Column(
        Integer,
        ForeignKey(
            "workflow_step_definitions.id",
            name="fk_wf_transitions_from_step",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    to_step_id = Column(
        Integer,
        ForeignKey(
            "workflow_step_definitions.id",
            name="fk_wf_transitions_to_step",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    action_key = Column(String(80), nullable=False)
    action_label = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    require_comment = Column(Boolean, nullable=False, default=False)
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    version = relationship(
        "WorkflowDefinitionVersion",
        back_populates="transitions",
    )
    from_step = relationship(
        "WorkflowStepDefinition",
        back_populates="outgoing_transitions",
        foreign_keys=[from_step_id],
    )
    to_step = relationship(
        "WorkflowStepDefinition",
        back_populates="incoming_transitions",
        foreign_keys=[to_step_id],
    )


class WorkflowInstance(Base):
    __tablename__ = "workflow_instances"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'completed', 'cancelled')",
            name="valid_status",
        ),
        Index(
            "ix_wf_instance_company_status",
            "company_id",
            "status",
        ),
        Index(
            "ix_wf_instance_entity",
            "company_id",
            "entity_type",
            "entity_id",
        ),
        Index(
            "ix_wf_instance_definition",
            "workflow_definition_id",
        ),
        Index(
            "uq_wf_instance_active_entity",
            "company_id",
            "workflow_definition_id",
            "entity_type",
            "entity_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(
        Integer,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_definition_id = Column(
        Integer,
        ForeignKey(
            "workflow_definitions.id",
            name="fk_wf_instances_definition",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    workflow_version_id = Column(
        Integer,
        ForeignKey(
            "workflow_definition_versions.id",
            name="fk_wf_instances_version",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    current_step_definition_id = Column(
        Integer,
        ForeignKey(
            "workflow_step_definitions.id",
            name="fk_wf_instances_current_step",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    entity_type = Column(String(80), nullable=False)
    entity_id = Column(String(120), nullable=False)
    title = Column(String(255), nullable=True)
    status = Column(
        String(20),
        nullable=False,
        default=WorkflowInstanceStatus.ACTIVE.value,
    )
    context_json = Column(JSONB, nullable=False, default=dict)
    started_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    completed_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    company = relationship("Company")
    definition = relationship(
        "WorkflowDefinition",
        back_populates="instances",
    )
    version = relationship(
        "WorkflowDefinitionVersion",
        back_populates="instances",
    )
    current_step_definition = relationship(
        "WorkflowStepDefinition",
        foreign_keys=[current_step_definition_id],
    )
    started_by = relationship(
        "User",
        foreign_keys=[started_by_user_id],
    )
    step_instances = relationship(
        "WorkflowStepInstance",
        back_populates="instance",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="WorkflowStepInstance.sequence_number",
    )
    files = relationship(
        "WorkflowInstanceFile",
        back_populates="instance",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="WorkflowInstanceFile.created_at",
    )
    audit_logs = relationship(
        "WorkflowAuditLog",
        back_populates="instance",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="WorkflowAuditLog.created_at",
    )


class WorkflowStepInstance(Base):
    __tablename__ = "workflow_step_instances"
    __table_args__ = (
        UniqueConstraint(
            "workflow_instance_id",
            "sequence_number",
            name="uq_wf_step_instance_sequence",
        ),
        CheckConstraint(
            "status IN "
            "('pending', 'active', 'completed', 'skipped', 'cancelled')",
            name="valid_status",
        ),
        CheckConstraint(
            "sequence_number >= 1",
            name="valid_sequence",
        ),
        CheckConstraint(
            "assignee_type IN "
            "('requester', 'user', 'department', 'position', 'role', 'any')",
            name="valid_assignee_type",
        ),
        CheckConstraint(
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
            name="valid_assignee_target",
        ),
        CheckConstraint(
            "completed_at IS NULL OR started_at IS NULL "
            "OR completed_at >= started_at",
            name="valid_dates",
        ),
        Index(
            "ix_wf_step_instance_instance_status",
            "workflow_instance_id",
            "status",
        ),
        Index(
            "ix_wf_step_instance_assignee",
            "assignee_type",
            "assigned_user_id",
            "assigned_department_id",
            "assigned_position_id",
            "assigned_role_id",
        ),
        Index(
            "uq_wf_step_instance_active",
            "workflow_instance_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id = Column(Integer, primary_key=True)
    workflow_instance_id = Column(
        Integer,
        ForeignKey(
            "workflow_instances.id",
            name="fk_wf_step_instances_instance",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    step_definition_id = Column(
        Integer,
        ForeignKey(
            "workflow_step_definitions.id",
            name="fk_wf_step_instances_definition",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    sequence_number = Column(Integer, nullable=False)
    status = Column(
        String(20),
        nullable=False,
        default=WorkflowStepInstanceStatus.PENDING.value,
    )
    assignee_type = Column(String(20), nullable=False)
    assigned_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_department_id = Column(
        Integer,
        ForeignKey(
            "organization_departments.id",
            name="fk_wf_step_inst_department",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    assigned_position_id = Column(
        Integer,
        ForeignKey(
            "organization_positions.id",
            name="fk_wf_step_inst_position",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    assigned_role_id = Column(
        Integer,
        ForeignKey(
            "roles.id",
            name="fk_wf_step_inst_role",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    started_at = Column(DateTime, nullable=True)
    due_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    completed_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    outcome = Column(String(80), nullable=True)
    comment = Column(Text, nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    instance = relationship(
        "WorkflowInstance",
        back_populates="step_instances",
    )
    step_definition = relationship(
        "WorkflowStepDefinition",
    )
    assigned_user = relationship(
        "User",
        foreign_keys=[assigned_user_id],
    )
    assigned_department = relationship(
        "OrganizationDepartment",
        foreign_keys=[assigned_department_id],
    )
    assigned_position = relationship(
        "OrganizationPosition",
        foreign_keys=[assigned_position_id],
    )
    assigned_role = relationship(
        "Role",
        foreign_keys=[assigned_role_id],
    )
    completed_by = relationship(
        "User",
        foreign_keys=[completed_by_user_id],
    )
    files = relationship(
        "WorkflowInstanceFile",
        back_populates="step_instance",
    )
    audit_logs = relationship(
        "WorkflowAuditLog",
        back_populates="step_instance",
    )


class WorkflowInstanceFile(Base):
    __tablename__ = "workflow_instance_files"
    __table_args__ = (
        UniqueConstraint(
            "workflow_instance_id",
            "file_asset_id",
            name="uq_wf_file_instance_asset",
        ),
        Index(
            "ix_wf_file_instance",
            "workflow_instance_id",
        ),
        Index(
            "ix_wf_file_step_instance",
            "step_instance_id",
        ),
        Index(
            "ix_wf_file_asset",
            "file_asset_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(
        Integer,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_instance_id = Column(
        Integer,
        ForeignKey(
            "workflow_instances.id",
            name="fk_wf_files_instance",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    step_instance_id = Column(
        Integer,
        ForeignKey(
            "workflow_step_instances.id",
            name="fk_wf_files_step_instance",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    file_asset_id = Column(
        Integer,
        ForeignKey(
            "file_assets.id",
            name="fk_wf_files_asset",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    attached_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    label = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    company = relationship("Company")
    instance = relationship(
        "WorkflowInstance",
        back_populates="files",
    )
    step_instance = relationship(
        "WorkflowStepInstance",
        back_populates="files",
    )
    asset = relationship(
        "FileAsset",
        foreign_keys=[file_asset_id],
    )
    attached_by = relationship(
        "User",
        foreign_keys=[attached_by_user_id],
    )


class WorkflowAuditLog(Base):
    __tablename__ = "workflow_audit_logs"
    __table_args__ = (
        Index(
            "ix_wf_audit_company_created",
            "company_id",
            "created_at",
        ),
        Index(
            "ix_wf_audit_instance_created",
            "workflow_instance_id",
            "created_at",
        ),
        Index(
            "ix_wf_audit_step_instance",
            "step_instance_id",
        ),
        Index(
            "ix_wf_audit_event_type",
            "event_type",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(
        Integer,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_instance_id = Column(
        Integer,
        ForeignKey(
            "workflow_instances.id",
            name="fk_wf_audit_instance",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    step_instance_id = Column(
        Integer,
        ForeignKey(
            "workflow_step_instances.id",
            name="fk_wf_audit_step_instance",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    actor_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type = Column(String(80), nullable=False)
    from_status = Column(String(40), nullable=True)
    to_status = Column(String(40), nullable=True)
    action_key = Column(String(80), nullable=True)
    message = Column(Text, nullable=True)
    details_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    company = relationship("Company")
    instance = relationship(
        "WorkflowInstance",
        back_populates="audit_logs",
    )
    step_instance = relationship(
        "WorkflowStepInstance",
        back_populates="audit_logs",
    )
    actor = relationship(
        "User",
        foreign_keys=[actor_user_id],
    )


def _prevent_workflow_audit_mutation(*_args, **_kwargs):
    raise ValueError("Workflow audit logs are append-only")


event.listen(
    WorkflowAuditLog,
    "before_update",
    _prevent_workflow_audit_mutation,
)
event.listen(
    WorkflowAuditLog,
    "before_delete",
    _prevent_workflow_audit_mutation,
)

