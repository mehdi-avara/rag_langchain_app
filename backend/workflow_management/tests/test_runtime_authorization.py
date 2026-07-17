from types import SimpleNamespace

import pytest

from workflow_management.models import (
    WorkflowAssigneeType,
)
from workflow_management.runtime_services import (
    _assignee_snapshot,
    _matches_step_assignee,
)


@pytest.mark.parametrize(
    (
        "assignee_type",
        "assigned_user_id",
        "assigned_department_id",
        "assigned_position_id",
        "assigned_role_id",
        "started_by_user_id",
        "department_ids",
        "position_ids",
        "role_ids",
        "expected",
    ),
    [
        (
            WorkflowAssigneeType.ANY.value,
            None,
            None,
            None,
            None,
            50,
            set(),
            set(),
            set(),
            True,
        ),
        (
            WorkflowAssigneeType.REQUESTER.value,
            None,
            None,
            None,
            None,
            10,
            set(),
            set(),
            set(),
            True,
        ),
        (
            WorkflowAssigneeType.USER.value,
            10,
            None,
            None,
            None,
            50,
            set(),
            set(),
            set(),
            True,
        ),
        (
            WorkflowAssigneeType.DEPARTMENT.value,
            None,
            20,
            None,
            None,
            50,
            {20},
            set(),
            set(),
            True,
        ),
        (
            WorkflowAssigneeType.POSITION.value,
            None,
            None,
            30,
            None,
            50,
            set(),
            {30},
            set(),
            True,
        ),
        (
            WorkflowAssigneeType.ROLE.value,
            None,
            None,
            None,
            40,
            50,
            set(),
            set(),
            {40},
            True,
        ),
        (
            WorkflowAssigneeType.DEPARTMENT.value,
            None,
            99,
            None,
            None,
            50,
            {20},
            set(),
            set(),
            False,
        ),
    ],
)
def test_runtime_assignee_authorization(
    assignee_type,
    assigned_user_id,
    assigned_department_id,
    assigned_position_id,
    assigned_role_id,
    started_by_user_id,
    department_ids,
    position_ids,
    role_ids,
    expected,
):
    step_instance = SimpleNamespace(
        assignee_type=assignee_type,
        assigned_user_id=assigned_user_id,
        assigned_department_id=assigned_department_id,
        assigned_position_id=assigned_position_id,
        assigned_role_id=assigned_role_id,
    )
    instance = SimpleNamespace(
        started_by_user_id=started_by_user_id
    )

    assert (
        _matches_step_assignee(
            step_instance=step_instance,
            instance=instance,
            user_id=10,
            department_ids=department_ids,
            position_ids=position_ids,
            role_ids=role_ids,
        )
        is expected
    )


def test_assignee_snapshot_preserves_department_target():
    step = SimpleNamespace(
        assignee_type=WorkflowAssigneeType.DEPARTMENT.value,
        target_user_id=None,
        target_department_id=25,
        target_position_id=None,
        target_role_id=None,
    )

    assert _assignee_snapshot(step) == {
        "assignee_type": "department",
        "assigned_user_id": None,
        "assigned_department_id": 25,
        "assigned_position_id": None,
        "assigned_role_id": None,
    }
