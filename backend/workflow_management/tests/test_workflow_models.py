import Models

from workflow_management.models import (
    WorkflowAuditLog,
    WorkflowDefinition,
    WorkflowDefinitionVersion,
    WorkflowInstance,
    WorkflowInstanceFile,
    WorkflowStepDefinition,
    WorkflowStepInstance,
    WorkflowTransitionDefinition,
)


TABLES = [
    WorkflowDefinition.__table__,
    WorkflowDefinitionVersion.__table__,
    WorkflowStepDefinition.__table__,
    WorkflowTransitionDefinition.__table__,
    WorkflowInstance.__table__,
    WorkflowStepInstance.__table__,
    WorkflowInstanceFile.__table__,
    WorkflowAuditLog.__table__,
]


def test_workflow_table_names():
    assert {table.name for table in TABLES} == {
        "workflow_definitions",
        "workflow_definition_versions",
        "workflow_step_definitions",
        "workflow_transition_definitions",
        "workflow_instances",
        "workflow_step_instances",
        "workflow_instance_files",
        "workflow_audit_logs",
    }


def test_workflow_database_names_fit_postgresql_limit():
    names = []

    for table in TABLES:
        names.extend(
            constraint.name
            for constraint in table.constraints
            if constraint.name
        )
        names.extend(
            index.name
            for index in table.indexes
            if index.name
        )

    assert {
        name: len(name)
        for name in names
        if len(name) > 63
    } == {}


def test_workflow_foreign_key_targets():
    assert {
        foreign_key.target_fullname
        for foreign_key
        in WorkflowStepDefinition.__table__.c.target_department_id.foreign_keys
    } == {
        "organization_departments.id",
    }

    assert {
        foreign_key.target_fullname
        for foreign_key
        in WorkflowStepDefinition.__table__.c.target_position_id.foreign_keys
    } == {
        "organization_positions.id",
    }

    assert {
        foreign_key.target_fullname
        for foreign_key
        in WorkflowStepDefinition.__table__.c.target_role_id.foreign_keys
    } == {
        "roles.id",
    }

    assert {
        foreign_key.target_fullname
        for foreign_key
        in WorkflowInstanceFile.__table__.c.file_asset_id.foreign_keys
    } == {
        "file_assets.id",
    }


def test_workflow_partial_unique_indexes_exist():
    draft_index = next(
        index
        for index in WorkflowDefinitionVersion.__table__.indexes
        if index.name == "uq_wf_ver_one_draft"
    )
    published_index = next(
        index
        for index in WorkflowDefinitionVersion.__table__.indexes
        if index.name == "uq_wf_ver_one_published"
    )
    start_index = next(
        index
        for index in WorkflowStepDefinition.__table__.indexes
        if index.name == "uq_wf_step_version_start_one"
    )
    instance_index = next(
        index
        for index in WorkflowInstance.__table__.indexes
        if index.name == "uq_wf_instance_active_entity"
    )
    step_index = next(
        index
        for index in WorkflowStepInstance.__table__.indexes
        if index.name == "uq_wf_step_instance_active"
    )

    assert draft_index.unique is True
    assert published_index.unique is True
    assert start_index.unique is True
    assert instance_index.unique is True
    assert step_index.unique is True
