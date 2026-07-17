from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from Models import User
from db.init_db import get_db
from deps import require_permission

from ..schemas import (
    WorkflowDefinitionCreate,
    WorkflowDefinitionRead,
    WorkflowDefinitionUpdate,
    WorkflowStepCreate,
    WorkflowStepRead,
    WorkflowStepUpdate,
    WorkflowTransitionCreate,
    WorkflowTransitionRead,
    WorkflowTransitionUpdate,
    WorkflowVersionCreate,
    WorkflowVersionRead,
    WorkflowVersionUpdate,
)
from ..services import (
    create_definition,
    create_step,
    create_transition,
    create_version,
    delete_step,
    delete_transition,
    get_definition_or_404,
    get_step_or_404,
    get_transition_or_404,
    get_version_or_404,
    list_definitions,
    list_steps,
    list_transitions,
    list_versions,
    publish_version,
    update_definition,
    update_step,
    update_transition,
    update_version,
)

router = APIRouter()


@router.post(
    "/definitions",
    response_model=WorkflowDefinitionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_definition(
    payload: WorkflowDefinitionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:definitions:manage")
    ),
):
    return create_definition(
        db,
        current_user,
        payload.model_dump(),
    )


@router.get(
    "/definitions",
    response_model=list[WorkflowDefinitionRead],
)
def list_workflow_definitions(
    entity_type: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:definitions:read")
    ),
):
    return list_definitions(
        db,
        current_user,
        entity_type=entity_type,
        is_active=is_active,
    )


@router.get(
    "/definitions/{definition_id}",
    response_model=WorkflowDefinitionRead,
)
def get_workflow_definition(
    definition_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:definitions:read")
    ),
):
    return get_definition_or_404(
        db,
        current_user,
        definition_id,
    )


@router.patch(
    "/definitions/{definition_id}",
    response_model=WorkflowDefinitionRead,
)
def patch_workflow_definition(
    definition_id: int,
    payload: WorkflowDefinitionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:definitions:manage")
    ),
):
    return update_definition(
        db,
        current_user,
        definition_id,
        payload.model_dump(exclude_unset=True),
    )


@router.post(
    "/definitions/{definition_id}/versions",
    response_model=WorkflowVersionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_version(
    definition_id: int,
    payload: WorkflowVersionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:definitions:manage")
    ),
):
    return create_version(
        db,
        current_user,
        definition_id,
        payload.model_dump(),
    )


@router.get(
    "/definitions/{definition_id}/versions",
    response_model=list[WorkflowVersionRead],
)
def list_workflow_versions(
    definition_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:definitions:read")
    ),
):
    return list_versions(
        db,
        current_user,
        definition_id,
    )


@router.get(
    "/versions/{version_id}",
    response_model=WorkflowVersionRead,
)
def get_workflow_version(
    version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:definitions:read")
    ),
):
    return get_version_or_404(
        db,
        current_user,
        version_id,
    )


@router.patch(
    "/versions/{version_id}",
    response_model=WorkflowVersionRead,
)
def patch_workflow_version(
    version_id: int,
    payload: WorkflowVersionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:definitions:manage")
    ),
):
    return update_version(
        db,
        current_user,
        version_id,
        payload.model_dump(exclude_unset=True),
    )


@router.post(
    "/versions/{version_id}/publish",
    response_model=WorkflowVersionRead,
)
def publish_workflow_version(
    version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:definitions:publish")
    ),
):
    return publish_version(
        db,
        current_user,
        version_id,
    )


@router.post(
    "/versions/{version_id}/steps",
    response_model=WorkflowStepRead,
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_step(
    version_id: int,
    payload: WorkflowStepCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:definitions:manage")
    ),
):
    return create_step(
        db,
        current_user,
        version_id,
        payload.model_dump(),
    )


@router.get(
    "/versions/{version_id}/steps",
    response_model=list[WorkflowStepRead],
)
def list_workflow_steps(
    version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:definitions:read")
    ),
):
    return list_steps(
        db,
        current_user,
        version_id,
    )


@router.get(
    "/steps/{step_id}",
    response_model=WorkflowStepRead,
)
def get_workflow_step(
    step_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:definitions:read")
    ),
):
    return get_step_or_404(
        db,
        current_user,
        step_id,
    )


@router.patch(
    "/steps/{step_id}",
    response_model=WorkflowStepRead,
)
def patch_workflow_step(
    step_id: int,
    payload: WorkflowStepUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:definitions:manage")
    ),
):
    return update_step(
        db,
        current_user,
        step_id,
        payload.model_dump(exclude_unset=True),
    )


@router.delete(
    "/steps/{step_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_workflow_step(
    step_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:definitions:manage")
    ),
):
    delete_step(
        db,
        current_user,
        step_id,
    )


@router.post(
    "/versions/{version_id}/transitions",
    response_model=WorkflowTransitionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_transition(
    version_id: int,
    payload: WorkflowTransitionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:definitions:manage")
    ),
):
    return create_transition(
        db,
        current_user,
        version_id,
        payload.model_dump(),
    )


@router.get(
    "/versions/{version_id}/transitions",
    response_model=list[WorkflowTransitionRead],
)
def list_workflow_transitions(
    version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:definitions:read")
    ),
):
    return list_transitions(
        db,
        current_user,
        version_id,
    )


@router.get(
    "/transitions/{transition_id}",
    response_model=WorkflowTransitionRead,
)
def get_workflow_transition(
    transition_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:definitions:read")
    ),
):
    return get_transition_or_404(
        db,
        current_user,
        transition_id,
    )


@router.patch(
    "/transitions/{transition_id}",
    response_model=WorkflowTransitionRead,
)
def patch_workflow_transition(
    transition_id: int,
    payload: WorkflowTransitionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:definitions:manage")
    ),
):
    return update_transition(
        db,
        current_user,
        transition_id,
        payload.model_dump(exclude_unset=True),
    )


@router.delete(
    "/transitions/{transition_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_workflow_transition(
    transition_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:definitions:manage")
    ),
):
    delete_transition(
        db,
        current_user,
        transition_id,
    )
