from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from workflow_management.models import (
    WorkflowStepType,
    WorkflowVersionStatus,
)
from workflow_management.services import (
    _assert_draft_version,
    _validate_graph_structure,
)


def step(
    step_id,
    *,
    start=False,
    terminal=False,
    approval_count=1,
):
    return SimpleNamespace(
        id=step_id,
        is_start=start,
        is_terminal=terminal,
        step_type=(
            WorkflowStepType.END.value
            if terminal
            else WorkflowStepType.APPROVAL.value
        ),
        required_approval_count=approval_count,
    )


def transition(from_step_id, to_step_id):
    return SimpleNamespace(
        from_step_id=from_step_id,
        to_step_id=to_step_id,
    )


def test_valid_workflow_graph_passes():
    steps = [
        step(1, start=True),
        step(2),
        step(3, terminal=True),
    ]
    transitions = [
        transition(1, 2),
        transition(2, 3),
    ]

    _validate_graph_structure(
        steps,
        transitions,
    )


def test_graph_requires_exactly_one_start():
    steps = [
        step(1),
        step(2, terminal=True),
    ]

    with pytest.raises(HTTPException) as exc:
        _validate_graph_structure(
            steps,
            [transition(1, 2)],
        )

    assert exc.value.status_code == 422
    assert (
        exc.value.detail["code"]
        == "WORKFLOW_VERSION_INVALID"
    )


def test_graph_rejects_steps_without_terminal_path():
    steps = [
        step(1, start=True),
        step(2),
        step(3, terminal=True),
    ]
    transitions = [
        transition(1, 2),
        transition(2, 1),
    ]

    with pytest.raises(HTTPException) as exc:
        _validate_graph_structure(
            steps,
            transitions,
        )

    assert exc.value.status_code == 422


def test_published_version_is_immutable():
    version = SimpleNamespace(
        status=WorkflowVersionStatus.PUBLISHED.value
    )

    with pytest.raises(HTTPException) as exc:
        _assert_draft_version(version)

    assert exc.value.status_code == 409
    assert (
        exc.value.detail["code"]
        == "WORKFLOW_VERSION_IMMUTABLE"
    )
