import pytest
from pydantic import ValidationError

from workflow_management.models import (
    WorkflowAssigneeType,
    WorkflowStepType,
)
from workflow_management.schemas import (
    WorkflowDefinitionCreate,
    WorkflowStepCreate,
    WorkflowTransitionCreate,
)


def test_definition_normalizes_code_and_entity_type():
    payload = WorkflowDefinitionCreate(
        code=" purchase_approval ",
        name=" Purchase Approval ",
        entity_type=" Material_Requisition ",
    )

    assert payload.code == "PURCHASE_APPROVAL"
    assert payload.name == "Purchase Approval"
    assert payload.entity_type == "material_requisition"


def test_user_assignee_requires_only_user_target():
    payload = WorkflowStepCreate(
        code="manager_approval",
        name="Manager Approval",
        assignee_type=WorkflowAssigneeType.USER,
        target_user_id=5,
    )

    assert payload.code == "MANAGER_APPROVAL"
    assert payload.target_user_id == 5


def test_user_assignee_rejects_missing_target():
    with pytest.raises(ValidationError):
        WorkflowStepCreate(
            code="manager_approval",
            name="Manager Approval",
            assignee_type=WorkflowAssigneeType.USER,
        )


def test_requester_assignee_rejects_target():
    with pytest.raises(ValidationError):
        WorkflowStepCreate(
            code="requester_review",
            name="Requester Review",
            assignee_type=WorkflowAssigneeType.REQUESTER,
            target_user_id=5,
        )


def test_end_step_must_be_terminal_and_any():
    payload = WorkflowStepCreate(
        code="completed",
        name="Completed",
        step_type=WorkflowStepType.END,
        is_terminal=True,
        assignee_type=WorkflowAssigneeType.ANY,
    )

    assert payload.is_terminal is True


def test_transition_rejects_same_source_and_target():
    with pytest.raises(ValidationError):
        WorkflowTransitionCreate(
            from_step_id=10,
            to_step_id=10,
            action_key="approve",
            action_label="Approve",
        )
