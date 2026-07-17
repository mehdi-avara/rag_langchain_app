from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import status
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from Models import FileAsset, FileAssetStatus, User
from core.exceptions.error_codes import (
    WORKFLOW_ACTION_FORBIDDEN,
    WORKFLOW_ACTION_NOT_ALLOWED,
    WORKFLOW_COMMENT_REQUIRED,
    WORKFLOW_DEFINITION_INACTIVE,
    WORKFLOW_DEFINITION_NOT_FOUND,
    WORKFLOW_FILE_INVALID,
    WORKFLOW_FILE_NOT_FOUND,
    WORKFLOW_INSTANCE_ALREADY_ACTIVE,
    WORKFLOW_INSTANCE_NOT_ACTIVE,
    WORKFLOW_INSTANCE_NOT_FOUND,
    WORKFLOW_STEP_INSTANCE_NOT_FOUND,
    WORKFLOW_VERSION_INVALID,
    WORKFLOW_VERSION_NOT_PUBLISHED,
)
from organization_management.models import (
    OrganizationUserAssignment,
)

from .models import (
    WorkflowAssigneeType,
    WorkflowAuditLog,
    WorkflowDefinition,
    WorkflowDefinitionVersion,
    WorkflowInstance,
    WorkflowInstanceFile,
    WorkflowInstanceStatus,
    WorkflowStepDefinition,
    WorkflowStepInstance,
    WorkflowStepInstanceStatus,
    WorkflowTransitionDefinition,
    WorkflowVersionStatus,
)
from .services import (
    _raise,
    _validate_step_target,
    tenant_id,
)


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _instance_query(db: Session):
    return db.query(WorkflowInstance).options(
        selectinload(WorkflowInstance.step_instances),
        selectinload(WorkflowInstance.files),
        selectinload(WorkflowInstance.audit_logs),
        selectinload(WorkflowInstance.definition),
        selectinload(WorkflowInstance.version),
    )


def get_instance_or_404(
    db: Session,
    current_user: User,
    instance_id: int,
) -> WorkflowInstance:
    instance = (
        _instance_query(db)
        .filter(
            WorkflowInstance.id == instance_id,
            WorkflowInstance.company_id == tenant_id(current_user),
        )
        .first()
    )

    if instance is None:
        _raise(
            status.HTTP_404_NOT_FOUND,
            WORKFLOW_INSTANCE_NOT_FOUND,
            "Workflow instance not found",
        )

    return instance


def _get_locked_instance_or_404(
    db: Session,
    current_user: User,
    instance_id: int,
) -> WorkflowInstance:
    instance = (
        db.query(WorkflowInstance)
        .filter(
            WorkflowInstance.id == instance_id,
            WorkflowInstance.company_id == tenant_id(current_user),
        )
        .with_for_update()
        .first()
    )

    if instance is None:
        _raise(
            status.HTTP_404_NOT_FOUND,
            WORKFLOW_INSTANCE_NOT_FOUND,
            "Workflow instance not found",
        )

    return instance


def _append_audit(
    db: Session,
    *,
    instance: WorkflowInstance,
    event_type: str,
    actor_user_id: Optional[int],
    step_instance_id: Optional[int] = None,
    from_status: Optional[str] = None,
    to_status: Optional[str] = None,
    action_key: Optional[str] = None,
    message: Optional[str] = None,
    details: Optional[dict] = None,
) -> WorkflowAuditLog:
    audit = WorkflowAuditLog(
        company_id=instance.company_id,
        workflow_instance_id=instance.id,
        step_instance_id=step_instance_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        action_key=action_key,
        message=message,
        details_json=details or {},
    )
    db.add(audit)

    return audit


def _get_definition_for_start(
    db: Session,
    company_id: int,
    definition_id: int,
) -> WorkflowDefinition:
    definition = (
        db.query(WorkflowDefinition)
        .filter(
            WorkflowDefinition.id == definition_id,
            WorkflowDefinition.company_id == company_id,
        )
        .first()
    )

    if definition is None:
        _raise(
            status.HTTP_404_NOT_FOUND,
            WORKFLOW_DEFINITION_NOT_FOUND,
            "Workflow definition not found",
        )

    if not definition.is_active:
        _raise(
            status.HTTP_409_CONFLICT,
            WORKFLOW_DEFINITION_INACTIVE,
            "Workflow definition is inactive",
        )

    return definition


def _get_published_version(
    db: Session,
    definition: WorkflowDefinition,
    version_id: Optional[int],
) -> WorkflowDefinitionVersion:
    query = (
        db.query(WorkflowDefinitionVersion)
        .options(
            selectinload(WorkflowDefinitionVersion.steps),
            selectinload(WorkflowDefinitionVersion.transitions),
        )
        .filter(
            WorkflowDefinitionVersion.workflow_definition_id
            == definition.id,
            WorkflowDefinitionVersion.status
            == WorkflowVersionStatus.PUBLISHED.value,
        )
    )

    if version_id is not None:
        query = query.filter(
            WorkflowDefinitionVersion.id == version_id
        )

    version = query.order_by(
        WorkflowDefinitionVersion.version_number.desc()
    ).first()

    if version is None:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            WORKFLOW_VERSION_NOT_PUBLISHED,
            "A published workflow version was not found",
        )

    return version


def _get_start_step(
    db: Session,
    version: WorkflowDefinitionVersion,
) -> WorkflowStepDefinition:
    step = (
        db.query(WorkflowStepDefinition)
        .filter(
            WorkflowStepDefinition.workflow_version_id == version.id,
            WorkflowStepDefinition.is_start.is_(True),
        )
        .first()
    )

    if step is None:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            WORKFLOW_VERSION_INVALID,
            "Published workflow version has no start step",
        )

    return step


def _assignee_snapshot(
    step: WorkflowStepDefinition,
) -> dict:
    assignee_type = _enum_value(step.assignee_type)

    values = {
        "assignee_type": assignee_type,
        "assigned_user_id": None,
        "assigned_department_id": None,
        "assigned_position_id": None,
        "assigned_role_id": None,
    }

    if assignee_type == WorkflowAssigneeType.USER.value:
        values["assigned_user_id"] = step.target_user_id
    elif assignee_type == WorkflowAssigneeType.DEPARTMENT.value:
        values["assigned_department_id"] = (
            step.target_department_id
        )
    elif assignee_type == WorkflowAssigneeType.POSITION.value:
        values["assigned_position_id"] = step.target_position_id
    elif assignee_type == WorkflowAssigneeType.ROLE.value:
        values["assigned_role_id"] = step.target_role_id

    return values


def _next_sequence_number(
    db: Session,
    instance_id: int,
) -> int:
    highest = (
        db.query(
            func.max(WorkflowStepInstance.sequence_number)
        )
        .filter(
            WorkflowStepInstance.workflow_instance_id
            == instance_id
        )
        .scalar()
        or 0
    )

    return highest + 1


def _activate_step(
    db: Session,
    *,
    instance: WorkflowInstance,
    step: WorkflowStepDefinition,
    actor_user_id: Optional[int],
) -> WorkflowStepInstance:
    _validate_step_target(
        db,
        instance.company_id,
        {
            "assignee_type": step.assignee_type,
            "target_user_id": step.target_user_id,
            "target_department_id": step.target_department_id,
            "target_position_id": step.target_position_id,
            "target_role_id": step.target_role_id,
        },
    )

    now = datetime.utcnow()
    terminal = bool(step.is_terminal)

    step_instance = WorkflowStepInstance(
        workflow_instance_id=instance.id,
        step_definition_id=step.id,
        sequence_number=_next_sequence_number(
            db,
            instance.id,
        ),
        status=(
            WorkflowStepInstanceStatus.COMPLETED.value
            if terminal
            else WorkflowStepInstanceStatus.ACTIVE.value
        ),
        started_at=now,
        completed_at=now if terminal else None,
        due_at=(
            now + timedelta(hours=step.due_in_hours)
            if step.due_in_hours is not None and not terminal
            else None
        ),
        outcome="automatic" if terminal else None,
        **_assignee_snapshot(step),
    )
    db.add(step_instance)
    db.flush()

    instance.current_step_definition_id = step.id

    _append_audit(
        db,
        instance=instance,
        step_instance_id=step_instance.id,
        actor_user_id=actor_user_id,
        event_type="step_activated",
        to_status=step_instance.status,
        details={
            "step_definition_id": step.id,
            "step_code": step.code,
            "sequence_number": step_instance.sequence_number,
        },
    )

    if terminal:
        previous_status = instance.status
        instance.status = WorkflowInstanceStatus.COMPLETED.value
        instance.completed_at = now

        _append_audit(
            db,
            instance=instance,
            step_instance_id=step_instance.id,
            actor_user_id=actor_user_id,
            event_type="terminal_step_reached",
            from_status=WorkflowStepInstanceStatus.ACTIVE.value,
            to_status=WorkflowStepInstanceStatus.COMPLETED.value,
            action_key="automatic",
            details={
                "step_definition_id": step.id,
                "step_code": step.code,
            },
        )
        _append_audit(
            db,
            instance=instance,
            actor_user_id=actor_user_id,
            event_type="instance_completed",
            from_status=previous_status,
            to_status=instance.status,
        )

    return step_instance


def start_instance(
    db: Session,
    current_user: User,
    data: dict,
) -> WorkflowInstance:
    company_id = tenant_id(current_user)

    definition = _get_definition_for_start(
        db,
        company_id,
        data["workflow_definition_id"],
    )

    entity_type = data["entity_type"].lower()

    if definition.entity_type != entity_type:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            WORKFLOW_VERSION_INVALID,
            "Workflow definition does not support this entity type",
            {
                "expected_entity_type": definition.entity_type,
                "received_entity_type": entity_type,
            },
        )

    version = _get_published_version(
        db,
        definition,
        data.get("workflow_version_id"),
    )

    existing = (
        db.query(WorkflowInstance.id)
        .filter(
            WorkflowInstance.company_id == company_id,
            WorkflowInstance.workflow_definition_id
            == definition.id,
            WorkflowInstance.entity_type == entity_type,
            WorkflowInstance.entity_id == data["entity_id"],
            WorkflowInstance.status
            == WorkflowInstanceStatus.ACTIVE.value,
        )
        .first()
    )

    if existing is not None:
        _raise(
            status.HTTP_409_CONFLICT,
            WORKFLOW_INSTANCE_ALREADY_ACTIVE,
            "An active workflow instance already exists",
        )

    start_step = _get_start_step(db, version)

    instance = WorkflowInstance(
        company_id=company_id,
        workflow_definition_id=definition.id,
        workflow_version_id=version.id,
        current_step_definition_id=start_step.id,
        entity_type=entity_type,
        entity_id=data["entity_id"],
        title=data.get("title"),
        context_json=data.get("context_json") or {},
        status=WorkflowInstanceStatus.ACTIVE.value,
        started_by_user_id=current_user.id,
        started_at=datetime.utcnow(),
    )
    db.add(instance)

    try:
        db.flush()

        _append_audit(
            db,
            instance=instance,
            actor_user_id=current_user.id,
            event_type="instance_started",
            to_status=instance.status,
            details={
                "workflow_definition_id": definition.id,
                "workflow_version_id": version.id,
                "entity_type": instance.entity_type,
                "entity_id": instance.entity_id,
            },
        )

        _activate_step(
            db,
            instance=instance,
            step=start_step,
            actor_user_id=current_user.id,
        )

        db.commit()

        return get_instance_or_404(
            db,
            current_user,
            instance.id,
        )
    except IntegrityError:
        db.rollback()
        _raise(
            status.HTTP_409_CONFLICT,
            WORKFLOW_INSTANCE_ALREADY_ACTIVE,
            "An active workflow instance already exists",
        )


def list_instances(
    db: Session,
    current_user: User,
    *,
    instance_status: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    workflow_definition_id: Optional[int] = None,
    limit: int = 100,
) -> list[WorkflowInstance]:
    query = _instance_query(db).filter(
        WorkflowInstance.company_id == tenant_id(current_user)
    )

    if instance_status is not None:
        query = query.filter(
            WorkflowInstance.status
            == _enum_value(instance_status)
        )

    if entity_type is not None:
        query = query.filter(
            WorkflowInstance.entity_type == entity_type.lower()
        )

    if entity_id is not None:
        query = query.filter(
            WorkflowInstance.entity_id == entity_id
        )

    if workflow_definition_id is not None:
        query = query.filter(
            WorkflowInstance.workflow_definition_id
            == workflow_definition_id
        )

    return query.order_by(
        WorkflowInstance.created_at.desc(),
        WorkflowInstance.id.desc(),
    ).limit(limit).all()


def _authorization_context(
    db: Session,
    current_user: User,
) -> tuple[set[int], set[int], set[int]]:
    today = date.today()

    assignments = (
        db.query(OrganizationUserAssignment)
        .filter(
            OrganizationUserAssignment.company_id
            == tenant_id(current_user),
            OrganizationUserAssignment.user_id
            == current_user.id,
            OrganizationUserAssignment.is_active.is_(True),
            or_(
                OrganizationUserAssignment.start_date.is_(None),
                OrganizationUserAssignment.start_date <= today,
            ),
            or_(
                OrganizationUserAssignment.end_date.is_(None),
                OrganizationUserAssignment.end_date >= today,
            ),
        )
        .all()
    )

    department_ids = {
        assignment.department_id
        for assignment in assignments
    }
    position_ids = {
        assignment.position_id
        for assignment in assignments
        if assignment.position_id is not None
    }
    role_ids = {
        role.id
        for role in current_user.roles
        if role.is_active
    }

    return department_ids, position_ids, role_ids


def _matches_step_assignee(
    *,
    step_instance: WorkflowStepInstance,
    instance: WorkflowInstance,
    user_id: int,
    department_ids: set[int],
    position_ids: set[int],
    role_ids: set[int],
) -> bool:
    assignee_type = _enum_value(
        step_instance.assignee_type
    )

    if assignee_type == WorkflowAssigneeType.ANY.value:
        return True

    if assignee_type == WorkflowAssigneeType.REQUESTER.value:
        return instance.started_by_user_id == user_id

    if assignee_type == WorkflowAssigneeType.USER.value:
        return step_instance.assigned_user_id == user_id

    if assignee_type == WorkflowAssigneeType.DEPARTMENT.value:
        return (
            step_instance.assigned_department_id
            in department_ids
        )

    if assignee_type == WorkflowAssigneeType.POSITION.value:
        return step_instance.assigned_position_id in position_ids

    if assignee_type == WorkflowAssigneeType.ROLE.value:
        return step_instance.assigned_role_id in role_ids

    return False


def _active_step_for_instance(
    db: Session,
    instance_id: int,
    *,
    lock: bool = False,
) -> WorkflowStepInstance:
    query = db.query(WorkflowStepInstance).filter(
        WorkflowStepInstance.workflow_instance_id == instance_id,
        WorkflowStepInstance.status
        == WorkflowStepInstanceStatus.ACTIVE.value,
    )

    if lock:
        query = query.with_for_update()

    step_instance = query.first()

    if step_instance is None:
        _raise(
            status.HTTP_409_CONFLICT,
            WORKFLOW_STEP_INSTANCE_NOT_FOUND,
            "Active workflow step was not found",
        )

    return step_instance


def _ensure_user_can_act(
    db: Session,
    current_user: User,
    instance: WorkflowInstance,
    step_instance: WorkflowStepInstance,
) -> None:
    department_ids, position_ids, role_ids = (
        _authorization_context(db, current_user)
    )

    if not _matches_step_assignee(
        step_instance=step_instance,
        instance=instance,
        user_id=current_user.id,
        department_ids=department_ids,
        position_ids=position_ids,
        role_ids=role_ids,
    ):
        _raise(
            status.HTTP_403_FORBIDDEN,
            WORKFLOW_ACTION_FORBIDDEN,
            "Current user is not assigned to this workflow step",
        )


def list_inbox(
    db: Session,
    current_user: User,
    *,
    limit: int = 100,
) -> list[WorkflowInstance]:
    instances = (
        _instance_query(db)
        .join(
            WorkflowStepInstance,
            WorkflowStepInstance.workflow_instance_id
            == WorkflowInstance.id,
        )
        .filter(
            WorkflowInstance.company_id == tenant_id(current_user),
            WorkflowInstance.status
            == WorkflowInstanceStatus.ACTIVE.value,
            WorkflowStepInstance.status
            == WorkflowStepInstanceStatus.ACTIVE.value,
        )
        .order_by(
            WorkflowInstance.created_at.desc(),
            WorkflowInstance.id.desc(),
        )
        .limit(500)
        .all()
    )

    department_ids, position_ids, role_ids = (
        _authorization_context(db, current_user)
    )

    matched = []

    for instance in instances:
        active_step = next(
            (
                step
                for step in instance.step_instances
                if step.status
                == WorkflowStepInstanceStatus.ACTIVE.value
            ),
            None,
        )

        if active_step is None:
            continue

        if _matches_step_assignee(
            step_instance=active_step,
            instance=instance,
            user_id=current_user.id,
            department_ids=department_ids,
            position_ids=position_ids,
            role_ids=role_ids,
        ):
            matched.append(instance)

        if len(matched) >= limit:
            break

    return matched


def perform_action(
    db: Session,
    current_user: User,
    instance_id: int,
    *,
    action_key: str,
    comment: Optional[str] = None,
) -> WorkflowInstance:
    instance = _get_locked_instance_or_404(
        db,
        current_user,
        instance_id,
    )

    if instance.status != WorkflowInstanceStatus.ACTIVE.value:
        _raise(
            status.HTTP_409_CONFLICT,
            WORKFLOW_INSTANCE_NOT_ACTIVE,
            "Workflow instance is not active",
        )

    active_step = _active_step_for_instance(
        db,
        instance.id,
        lock=True,
    )

    _ensure_user_can_act(
        db,
        current_user,
        instance,
        active_step,
    )

    transition = (
        db.query(WorkflowTransitionDefinition)
        .filter(
            WorkflowTransitionDefinition.workflow_version_id
            == instance.workflow_version_id,
            WorkflowTransitionDefinition.from_step_id
            == active_step.step_definition_id,
            WorkflowTransitionDefinition.action_key
            == action_key.lower(),
        )
        .first()
    )

    if transition is None:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            WORKFLOW_ACTION_NOT_ALLOWED,
            "Workflow action is not available for the active step",
        )

    if transition.require_comment and not comment:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            WORKFLOW_COMMENT_REQUIRED,
            "A comment is required for this workflow action",
        )

    target_step = (
        db.query(WorkflowStepDefinition)
        .filter(
            WorkflowStepDefinition.id == transition.to_step_id,
            WorkflowStepDefinition.workflow_version_id
            == instance.workflow_version_id,
        )
        .first()
    )

    if target_step is None:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            WORKFLOW_VERSION_INVALID,
            "Transition target step is invalid",
        )

    now = datetime.utcnow()
    previous_step_status = active_step.status

    active_step.status = (
        WorkflowStepInstanceStatus.COMPLETED.value
    )
    active_step.completed_at = now
    active_step.completed_by_user_id = current_user.id
    active_step.outcome = transition.action_key
    active_step.comment = comment

    _append_audit(
        db,
        instance=instance,
        step_instance_id=active_step.id,
        actor_user_id=current_user.id,
        event_type="step_completed",
        from_status=previous_step_status,
        to_status=active_step.status,
        action_key=transition.action_key,
        message=comment,
        details={
            "step_definition_id":
            active_step.step_definition_id,
            "transition_id": transition.id,
        },
    )

    _append_audit(
        db,
        instance=instance,
        step_instance_id=active_step.id,
        actor_user_id=current_user.id,
        event_type="transition_performed",
        action_key=transition.action_key,
        message=comment,
        details={
            "transition_id": transition.id,
            "from_step_id": transition.from_step_id,
            "to_step_id": transition.to_step_id,
        },
    )

    _activate_step(
        db,
        instance=instance,
        step=target_step,
        actor_user_id=current_user.id,
    )

    db.commit()

    return get_instance_or_404(
        db,
        current_user,
        instance.id,
    )


def cancel_instance(
    db: Session,
    current_user: User,
    instance_id: int,
    *,
    reason: Optional[str] = None,
) -> WorkflowInstance:
    instance = _get_locked_instance_or_404(
        db,
        current_user,
        instance_id,
    )

    if instance.status != WorkflowInstanceStatus.ACTIVE.value:
        _raise(
            status.HTTP_409_CONFLICT,
            WORKFLOW_INSTANCE_NOT_ACTIVE,
            "Workflow instance is not active",
        )

    now = datetime.utcnow()
    previous_status = instance.status

    active_step = (
        db.query(WorkflowStepInstance)
        .filter(
            WorkflowStepInstance.workflow_instance_id
            == instance.id,
            WorkflowStepInstance.status
            == WorkflowStepInstanceStatus.ACTIVE.value,
        )
        .with_for_update()
        .first()
    )

    if active_step is not None:
        active_step.status = (
            WorkflowStepInstanceStatus.CANCELLED.value
        )
        active_step.completed_at = now
        active_step.completed_by_user_id = current_user.id
        active_step.outcome = "cancelled"
        active_step.comment = reason

    instance.status = WorkflowInstanceStatus.CANCELLED.value
    instance.cancelled_at = now

    _append_audit(
        db,
        instance=instance,
        step_instance_id=(
            active_step.id
            if active_step is not None
            else None
        ),
        actor_user_id=current_user.id,
        event_type="instance_cancelled",
        from_status=previous_status,
        to_status=instance.status,
        action_key="cancel",
        message=reason,
    )

    db.commit()

    return get_instance_or_404(
        db,
        current_user,
        instance.id,
    )


def list_instance_files(
    db: Session,
    current_user: User,
    instance_id: int,
) -> list[WorkflowInstanceFile]:
    instance = get_instance_or_404(
        db,
        current_user,
        instance_id,
    )

    return (
        db.query(WorkflowInstanceFile)
        .filter(
            WorkflowInstanceFile.workflow_instance_id
            == instance.id,
            WorkflowInstanceFile.company_id
            == instance.company_id,
        )
        .order_by(
            WorkflowInstanceFile.created_at.asc(),
            WorkflowInstanceFile.id.asc(),
        )
        .all()
    )


def attach_instance_file(
    db: Session,
    current_user: User,
    instance_id: int,
    data: dict,
) -> WorkflowInstanceFile:
    instance = get_instance_or_404(
        db,
        current_user,
        instance_id,
    )

    asset = (
        db.query(FileAsset)
        .filter(
            FileAsset.id == data["file_asset_id"],
            FileAsset.company_id == instance.company_id,
            FileAsset.status == FileAssetStatus.READY.value,
        )
        .first()
    )

    if asset is None:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            WORKFLOW_FILE_INVALID,
            "File asset is invalid, inaccessible, or not ready",
        )

    step_instance_id = data.get("step_instance_id")

    if step_instance_id is not None:
        valid_step = (
            db.query(WorkflowStepInstance.id)
            .filter(
                WorkflowStepInstance.id == step_instance_id,
                WorkflowStepInstance.workflow_instance_id
                == instance.id,
            )
            .first()
        )

        if valid_step is None:
            _raise(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                WORKFLOW_FILE_INVALID,
                "Workflow step instance is invalid",
            )

    link = WorkflowInstanceFile(
        company_id=instance.company_id,
        workflow_instance_id=instance.id,
        step_instance_id=step_instance_id,
        file_asset_id=asset.id,
        attached_by_user_id=current_user.id,
        label=data.get("label"),
        description=data.get("description"),
    )
    db.add(link)

    try:
        db.flush()

        _append_audit(
            db,
            instance=instance,
            step_instance_id=step_instance_id,
            actor_user_id=current_user.id,
            event_type="file_attached",
            details={
                "workflow_instance_file_id": link.id,
                "file_asset_id": asset.id,
                "original_filename": asset.original_filename,
            },
        )

        db.commit()
        db.refresh(link)

        return link
    except IntegrityError:
        db.rollback()
        _raise(
            status.HTTP_409_CONFLICT,
            WORKFLOW_FILE_INVALID,
            "File asset is already attached to this workflow instance",
        )


def get_instance_file_or_404(
    db: Session,
    current_user: User,
    instance_id: int,
    workflow_file_id: int,
) -> WorkflowInstanceFile:
    workflow_file = (
        db.query(WorkflowInstanceFile)
        .filter(
            WorkflowInstanceFile.id == workflow_file_id,
            WorkflowInstanceFile.workflow_instance_id
            == instance_id,
            WorkflowInstanceFile.company_id
            == tenant_id(current_user),
        )
        .first()
    )

    if workflow_file is None:
        _raise(
            status.HTTP_404_NOT_FOUND,
            WORKFLOW_FILE_NOT_FOUND,
            "Workflow instance file not found",
        )

    return workflow_file


def detach_instance_file(
    db: Session,
    current_user: User,
    instance_id: int,
    workflow_file_id: int,
) -> None:
    instance = get_instance_or_404(
        db,
        current_user,
        instance_id,
    )
    workflow_file = get_instance_file_or_404(
        db,
        current_user,
        instance.id,
        workflow_file_id,
    )

    details = {
        "workflow_instance_file_id": workflow_file.id,
        "file_asset_id": workflow_file.file_asset_id,
    }
    step_instance_id = workflow_file.step_instance_id

    db.delete(workflow_file)

    _append_audit(
        db,
        instance=instance,
        step_instance_id=step_instance_id,
        actor_user_id=current_user.id,
        event_type="file_detached",
        details=details,
    )

    db.commit()


def list_instance_audit(
    db: Session,
    current_user: User,
    instance_id: int,
) -> list[WorkflowAuditLog]:
    instance = get_instance_or_404(
        db,
        current_user,
        instance_id,
    )

    return (
        db.query(WorkflowAuditLog)
        .filter(
            WorkflowAuditLog.workflow_instance_id
            == instance.id,
            WorkflowAuditLog.company_id
            == instance.company_id,
        )
        .order_by(
            WorkflowAuditLog.created_at.asc(),
            WorkflowAuditLog.id.asc(),
        )
        .all()
    )
