from workflow_management.permissions import PERMISSIONS


def test_workflow_permissions_are_registered():
    assert {item[0] for item in PERMISSIONS} == {
        "workflow:definitions:read",
        "workflow:definitions:manage",
        "workflow:definitions:publish",
        "workflow:instances:read",
        "workflow:instances:start",
        "workflow:instances:action",
        "workflow:instances:cancel",
        "workflow:files:manage",
        "workflow:audit:read",
    }


def test_workflow_models_are_exported():
    from Models import (
        WorkflowAuditLog,
        WorkflowDefinition,
        WorkflowDefinitionVersion,
        WorkflowInstance,
        WorkflowInstanceFile,
        WorkflowStepDefinition,
        WorkflowStepInstance,
        WorkflowTransitionDefinition,
    )

    assert WorkflowDefinition.__tablename__ == "workflow_definitions"
    assert (
        WorkflowDefinitionVersion.__tablename__
        == "workflow_definition_versions"
    )
    assert (
        WorkflowStepDefinition.__tablename__
        == "workflow_step_definitions"
    )
    assert (
        WorkflowTransitionDefinition.__tablename__
        == "workflow_transition_definitions"
    )
    assert WorkflowInstance.__tablename__ == "workflow_instances"
    assert (
        WorkflowStepInstance.__tablename__
        == "workflow_step_instances"
    )
    assert (
        WorkflowInstanceFile.__tablename__
        == "workflow_instance_files"
    )
    assert WorkflowAuditLog.__tablename__ == "workflow_audit_logs"
