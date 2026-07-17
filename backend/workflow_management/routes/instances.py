from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from Models import User
from db.init_db import get_db
from deps import require_permission

from ..models import WorkflowInstanceStatus
from ..runtime_services import (
    attach_instance_file,
    cancel_instance,
    detach_instance_file,
    get_instance_or_404,
    list_inbox,
    list_instance_audit,
    list_instance_files,
    list_instances,
    perform_action,
    start_instance,
)
from ..schemas import (
    WorkflowActionCreate,
    WorkflowAuditRead,
    WorkflowCancelCreate,
    WorkflowFileCreate,
    WorkflowFileRead,
    WorkflowInstanceCreate,
    WorkflowInstanceRead,
)

router = APIRouter()


@router.post(
    "/instances",
    response_model=WorkflowInstanceRead,
    status_code=status.HTTP_201_CREATED,
)
def start_workflow_instance(
    payload: WorkflowInstanceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:instances:start")
    ),
):
    return start_instance(
        db,
        current_user,
        payload.model_dump(),
    )


@router.get(
    "/instances",
    response_model=list[WorkflowInstanceRead],
)
def list_workflow_instances(
    instance_status: Optional[WorkflowInstanceStatus] = Query(
        None,
        alias="status",
    ),
    entity_type: Optional[str] = Query(None),
    entity_id: Optional[str] = Query(None),
    workflow_definition_id: Optional[int] = Query(None, gt=0),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:instances:read")
    ),
):
    return list_instances(
        db,
        current_user,
        instance_status=instance_status,
        entity_type=entity_type,
        entity_id=entity_id,
        workflow_definition_id=workflow_definition_id,
        limit=limit,
    )


@router.get(
    "/instances/inbox",
    response_model=list[WorkflowInstanceRead],
)
def list_my_workflow_inbox(
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:instances:read")
    ),
):
    return list_inbox(
        db,
        current_user,
        limit=limit,
    )


@router.get(
    "/instances/{instance_id}",
    response_model=WorkflowInstanceRead,
)
def get_workflow_instance(
    instance_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:instances:read")
    ),
):
    return get_instance_or_404(
        db,
        current_user,
        instance_id,
    )


@router.post(
    "/instances/{instance_id}/actions",
    response_model=WorkflowInstanceRead,
)
def perform_workflow_action(
    instance_id: int,
    payload: WorkflowActionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:instances:action")
    ),
):
    return perform_action(
        db,
        current_user,
        instance_id,
        action_key=payload.action_key,
        comment=payload.comment,
    )


@router.post(
    "/instances/{instance_id}/cancel",
    response_model=WorkflowInstanceRead,
)
def cancel_workflow_instance(
    instance_id: int,
    payload: WorkflowCancelCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:instances:cancel")
    ),
):
    return cancel_instance(
        db,
        current_user,
        instance_id,
        reason=payload.reason,
    )


@router.get(
    "/instances/{instance_id}/files",
    response_model=list[WorkflowFileRead],
)
def list_workflow_instance_files(
    instance_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:instances:read")
    ),
):
    return list_instance_files(
        db,
        current_user,
        instance_id,
    )


@router.post(
    "/instances/{instance_id}/files",
    response_model=WorkflowFileRead,
    status_code=status.HTTP_201_CREATED,
)
def attach_workflow_instance_file(
    instance_id: int,
    payload: WorkflowFileCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:files:manage")
    ),
):
    return attach_instance_file(
        db,
        current_user,
        instance_id,
        payload.model_dump(),
    )


@router.delete(
    "/instances/{instance_id}/files/{workflow_file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def detach_workflow_instance_file(
    instance_id: int,
    workflow_file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:files:manage")
    ),
):
    detach_instance_file(
        db,
        current_user,
        instance_id,
        workflow_file_id,
    )


@router.get(
    "/instances/{instance_id}/audit",
    response_model=list[WorkflowAuditRead],
)
def list_workflow_instance_audit(
    instance_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("workflow:audit:read")
    ),
):
    return list_instance_audit(
        db,
        current_user,
        instance_id,
    )
