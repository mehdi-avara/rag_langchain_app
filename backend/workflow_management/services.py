from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from Models import Role, User
from core.exceptions.error_codes import (
    USER_HAS_NO_COMPANY,
    WORKFLOW_DEFINITION_ALREADY_EXISTS,
    WORKFLOW_DEFINITION_NOT_FOUND,
    WORKFLOW_STEP_INVALID_ASSIGNEE,
    WORKFLOW_STEP_NOT_FOUND,
    WORKFLOW_TRANSITION_INVALID,
    WORKFLOW_TRANSITION_NOT_FOUND,
    WORKFLOW_VERSION_IMMUTABLE,
    WORKFLOW_VERSION_INVALID,
    WORKFLOW_VERSION_NOT_DRAFT,
    WORKFLOW_VERSION_NOT_FOUND,
)
from organization_management.models import (
    OrganizationDepartment,
    OrganizationPosition,
)

from .models import (
    WorkflowAssigneeType,
    WorkflowDefinition,
    WorkflowDefinitionVersion,
    WorkflowStepDefinition,
    WorkflowStepType,
    WorkflowTransitionDefinition,
    WorkflowVersionStatus,
)
from .schemas import WorkflowStepCreate


def _raise(
    status_code: int,
    code: str,
    message: str,
    details=None,
) -> None:
    raise HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "details": details,
        },
    )


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def tenant_id(current_user: User) -> int:
    if current_user.company_id is None:
        _raise(
            status.HTTP_403_FORBIDDEN,
            USER_HAS_NO_COMPANY,
            "Current user does not belong to a company",
        )

    return current_user.company_id


def _definition_query(db: Session):
    return db.query(WorkflowDefinition).options(
        selectinload(WorkflowDefinition.versions)
    )


def get_definition_or_404(
    db: Session,
    current_user: User,
    definition_id: int,
) -> WorkflowDefinition:
    definition = (
        _definition_query(db)
        .filter(
            WorkflowDefinition.id == definition_id,
            WorkflowDefinition.company_id == tenant_id(current_user),
        )
        .first()
    )

    if definition is None:
        _raise(
            status.HTTP_404_NOT_FOUND,
            WORKFLOW_DEFINITION_NOT_FOUND,
            "Workflow definition not found",
        )

    return definition


def get_version_or_404(
    db: Session,
    current_user: User,
    version_id: int,
) -> WorkflowDefinitionVersion:
    version = (
        db.query(WorkflowDefinitionVersion)
        .join(
            WorkflowDefinition,
            WorkflowDefinition.id
            == WorkflowDefinitionVersion.workflow_definition_id,
        )
        .options(
            selectinload(WorkflowDefinitionVersion.definition),
            selectinload(WorkflowDefinitionVersion.steps),
            selectinload(WorkflowDefinitionVersion.transitions),
        )
        .filter(
            WorkflowDefinitionVersion.id == version_id,
            WorkflowDefinition.company_id == tenant_id(current_user),
        )
        .first()
    )

    if version is None:
        _raise(
            status.HTTP_404_NOT_FOUND,
            WORKFLOW_VERSION_NOT_FOUND,
            "Workflow version not found",
        )

    return version


def get_step_or_404(
    db: Session,
    current_user: User,
    step_id: int,
) -> WorkflowStepDefinition:
    step = (
        db.query(WorkflowStepDefinition)
        .join(
            WorkflowDefinitionVersion,
            WorkflowDefinitionVersion.id
            == WorkflowStepDefinition.workflow_version_id,
        )
        .join(
            WorkflowDefinition,
            WorkflowDefinition.id
            == WorkflowDefinitionVersion.workflow_definition_id,
        )
        .options(
            selectinload(WorkflowStepDefinition.version).selectinload(
                WorkflowDefinitionVersion.definition
            )
        )
        .filter(
            WorkflowStepDefinition.id == step_id,
            WorkflowDefinition.company_id == tenant_id(current_user),
        )
        .first()
    )

    if step is None:
        _raise(
            status.HTTP_404_NOT_FOUND,
            WORKFLOW_STEP_NOT_FOUND,
            "Workflow step not found",
        )

    return step


def get_transition_or_404(
    db: Session,
    current_user: User,
    transition_id: int,
) -> WorkflowTransitionDefinition:
    transition = (
        db.query(WorkflowTransitionDefinition)
        .join(
            WorkflowDefinitionVersion,
            WorkflowDefinitionVersion.id
            == WorkflowTransitionDefinition.workflow_version_id,
        )
        .join(
            WorkflowDefinition,
            WorkflowDefinition.id
            == WorkflowDefinitionVersion.workflow_definition_id,
        )
        .options(
            selectinload(
                WorkflowTransitionDefinition.version
            ).selectinload(WorkflowDefinitionVersion.definition)
        )
        .filter(
            WorkflowTransitionDefinition.id == transition_id,
            WorkflowDefinition.company_id == tenant_id(current_user),
        )
        .first()
    )

    if transition is None:
        _raise(
            status.HTTP_404_NOT_FOUND,
            WORKFLOW_TRANSITION_NOT_FOUND,
            "Workflow transition not found",
        )

    return transition


def _assert_draft_version(
    version: WorkflowDefinitionVersion,
) -> None:
    if version.status != WorkflowVersionStatus.DRAFT.value:
        _raise(
            status.HTTP_409_CONFLICT,
            WORKFLOW_VERSION_IMMUTABLE,
            "Published and archived workflow versions are immutable",
        )


def list_definitions(
    db: Session,
    current_user: User,
    entity_type: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> list[WorkflowDefinition]:
    query = _definition_query(db).filter(
        WorkflowDefinition.company_id == tenant_id(current_user)
    )

    if entity_type is not None:
        query = query.filter(
            WorkflowDefinition.entity_type == entity_type.lower()
        )

    if is_active is not None:
        query = query.filter(
            WorkflowDefinition.is_active.is_(is_active)
        )

    return query.order_by(
        WorkflowDefinition.name.asc(),
        WorkflowDefinition.id.asc(),
    ).all()


def create_definition(
    db: Session,
    current_user: User,
    data: dict,
) -> WorkflowDefinition:
    company_id = tenant_id(current_user)

    existing = (
        db.query(WorkflowDefinition.id)
        .filter(
            WorkflowDefinition.company_id == company_id,
            WorkflowDefinition.code == data["code"],
        )
        .first()
    )

    if existing is not None:
        _raise(
            status.HTTP_409_CONFLICT,
            WORKFLOW_DEFINITION_ALREADY_EXISTS,
            "Workflow definition code already exists",
        )

    definition = WorkflowDefinition(
        company_id=company_id,
        created_by_user_id=current_user.id,
        **data,
    )
    db.add(definition)

    try:
        db.flush()

        db.add(
            WorkflowDefinitionVersion(
                workflow_definition_id=definition.id,
                version_number=1,
                status=WorkflowVersionStatus.DRAFT.value,
                created_by_user_id=current_user.id,
            )
        )

        db.commit()
        db.refresh(definition)
        return definition
    except IntegrityError:
        db.rollback()
        _raise(
            status.HTTP_409_CONFLICT,
            WORKFLOW_DEFINITION_ALREADY_EXISTS,
            "Workflow definition code already exists",
        )


def update_definition(
    db: Session,
    current_user: User,
    definition_id: int,
    data: dict,
) -> WorkflowDefinition:
    definition = get_definition_or_404(
        db,
        current_user,
        definition_id,
    )

    if "code" in data and data["code"] != definition.code:
        conflict = (
            db.query(WorkflowDefinition.id)
            .filter(
                WorkflowDefinition.company_id
                == definition.company_id,
                WorkflowDefinition.code == data["code"],
                WorkflowDefinition.id != definition.id,
            )
            .first()
        )

        if conflict is not None:
            _raise(
                status.HTTP_409_CONFLICT,
                WORKFLOW_DEFINITION_ALREADY_EXISTS,
                "Workflow definition code already exists",
            )

    for field, value in data.items():
        setattr(definition, field, value)

    try:
        db.commit()
        db.refresh(definition)
        return definition
    except IntegrityError:
        db.rollback()
        _raise(
            status.HTTP_409_CONFLICT,
            WORKFLOW_DEFINITION_ALREADY_EXISTS,
            "Workflow definition code already exists",
        )


def list_versions(
    db: Session,
    current_user: User,
    definition_id: int,
) -> list[WorkflowDefinitionVersion]:
    definition = get_definition_or_404(
        db,
        current_user,
        definition_id,
    )

    return (
        db.query(WorkflowDefinitionVersion)
        .filter(
            WorkflowDefinitionVersion.workflow_definition_id
            == definition.id
        )
        .order_by(
            WorkflowDefinitionVersion.version_number.desc()
        )
        .all()
    )


def create_version(
    db: Session,
    current_user: User,
    definition_id: int,
    data: dict,
) -> WorkflowDefinitionVersion:
    definition = get_definition_or_404(
        db,
        current_user,
        definition_id,
    )

    existing_draft = (
        db.query(WorkflowDefinitionVersion)
        .filter(
            WorkflowDefinitionVersion.workflow_definition_id
            == definition.id,
            WorkflowDefinitionVersion.status
            == WorkflowVersionStatus.DRAFT.value,
        )
        .first()
    )

    if existing_draft is not None:
        _raise(
            status.HTTP_409_CONFLICT,
            WORKFLOW_VERSION_NOT_DRAFT,
            "A draft version already exists",
            {"version_id": existing_draft.id},
        )

    highest = (
        db.query(
            func.max(
                WorkflowDefinitionVersion.version_number
            )
        )
        .filter(
            WorkflowDefinitionVersion.workflow_definition_id
            == definition.id
        )
        .scalar()
        or 0
    )

    version = WorkflowDefinitionVersion(
        workflow_definition_id=definition.id,
        version_number=highest + 1,
        status=WorkflowVersionStatus.DRAFT.value,
        created_by_user_id=current_user.id,
        **data,
    )
    db.add(version)
    db.commit()
    db.refresh(version)

    return version


def update_version(
    db: Session,
    current_user: User,
    version_id: int,
    data: dict,
) -> WorkflowDefinitionVersion:
    version = get_version_or_404(
        db,
        current_user,
        version_id,
    )
    _assert_draft_version(version)

    for field, value in data.items():
        setattr(version, field, value)

    db.commit()
    db.refresh(version)

    return version


def _validate_step_target(
    db: Session,
    company_id: int,
    data: dict,
) -> None:
    assignee_type = _enum_value(data["assignee_type"])

    target_user_id = data.get("target_user_id")
    target_department_id = data.get("target_department_id")
    target_position_id = data.get("target_position_id")
    target_role_id = data.get("target_role_id")

    if assignee_type == WorkflowAssigneeType.USER.value:
        valid = (
            db.query(User.id)
            .filter(
                User.id == target_user_id,
                User.company_id == company_id,
                User.is_active.is_(True),
            )
            .first()
        )
    elif assignee_type == WorkflowAssigneeType.DEPARTMENT.value:
        valid = (
            db.query(OrganizationDepartment.id)
            .filter(
                OrganizationDepartment.id == target_department_id,
                OrganizationDepartment.company_id == company_id,
                OrganizationDepartment.is_active.is_(True),
            )
            .first()
        )
    elif assignee_type == WorkflowAssigneeType.POSITION.value:
        valid = (
            db.query(OrganizationPosition.id)
            .filter(
                OrganizationPosition.id == target_position_id,
                OrganizationPosition.company_id == company_id,
                OrganizationPosition.is_active.is_(True),
            )
            .first()
        )
    elif assignee_type == WorkflowAssigneeType.ROLE.value:
        valid = (
            db.query(Role.id)
            .filter(
                Role.id == target_role_id,
                Role.is_active.is_(True),
                or_(
                    Role.company_id.is_(None),
                    Role.company_id == company_id,
                ),
            )
            .first()
        )
    else:
        valid = True

    if not valid:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            WORKFLOW_STEP_INVALID_ASSIGNEE,
            "Workflow step assignee target is invalid",
        )


def list_steps(
    db: Session,
    current_user: User,
    version_id: int,
) -> list[WorkflowStepDefinition]:
    version = get_version_or_404(
        db,
        current_user,
        version_id,
    )

    return (
        db.query(WorkflowStepDefinition)
        .filter(
            WorkflowStepDefinition.workflow_version_id
            == version.id
        )
        .order_by(
            WorkflowStepDefinition.sort_order.asc(),
            WorkflowStepDefinition.id.asc(),
        )
        .all()
    )


def create_step(
    db: Session,
    current_user: User,
    version_id: int,
    data: dict,
) -> WorkflowStepDefinition:
    version = get_version_or_404(
        db,
        current_user,
        version_id,
    )
    _assert_draft_version(version)

    company_id = version.definition.company_id
    normalized = WorkflowStepCreate.model_validate(
        data
    ).model_dump()

    _validate_step_target(
        db,
        company_id,
        normalized,
    )

    if normalized["is_start"]:
        existing_start = (
            db.query(WorkflowStepDefinition.id)
            .filter(
                WorkflowStepDefinition.workflow_version_id
                == version.id,
                WorkflowStepDefinition.is_start.is_(True),
            )
            .first()
        )

        if existing_start is not None:
            _raise(
                status.HTTP_409_CONFLICT,
                WORKFLOW_VERSION_INVALID,
                "Workflow version already has a start step",
            )

    step = WorkflowStepDefinition(
        workflow_version_id=version.id,
        **{
            key: _enum_value(value)
            for key, value in normalized.items()
        },
    )
    db.add(step)

    try:
        db.commit()
        db.refresh(step)
        return step
    except IntegrityError:
        db.rollback()
        _raise(
            status.HTTP_409_CONFLICT,
            WORKFLOW_VERSION_INVALID,
            "Workflow step code or start-step constraint conflicts",
        )


def update_step(
    db: Session,
    current_user: User,
    step_id: int,
    data: dict,
) -> WorkflowStepDefinition:
    step = get_step_or_404(
        db,
        current_user,
        step_id,
    )
    version = step.version
    _assert_draft_version(version)

    merged = {
        "code": step.code,
        "name": step.name,
        "description": step.description,
        "step_type": step.step_type,
        "sort_order": step.sort_order,
        "is_start": step.is_start,
        "is_terminal": step.is_terminal,
        "assignee_type": step.assignee_type,
        "target_user_id": step.target_user_id,
        "target_department_id": step.target_department_id,
        "target_position_id": step.target_position_id,
        "target_role_id": step.target_role_id,
        "required_approval_count": step.required_approval_count,
        "due_in_hours": step.due_in_hours,
    }
    merged.update(data)

    normalized = WorkflowStepCreate.model_validate(
        merged
    ).model_dump()

    _validate_step_target(
        db,
        version.definition.company_id,
        normalized,
    )

    if normalized["is_start"]:
        existing_start = (
            db.query(WorkflowStepDefinition.id)
            .filter(
                WorkflowStepDefinition.workflow_version_id
                == version.id,
                WorkflowStepDefinition.is_start.is_(True),
                WorkflowStepDefinition.id != step.id,
            )
            .first()
        )

        if existing_start is not None:
            _raise(
                status.HTTP_409_CONFLICT,
                WORKFLOW_VERSION_INVALID,
                "Workflow version already has a start step",
            )

    for field, value in normalized.items():
        setattr(step, field, _enum_value(value))

    try:
        db.commit()
        db.refresh(step)
        return step
    except IntegrityError:
        db.rollback()
        _raise(
            status.HTTP_409_CONFLICT,
            WORKFLOW_VERSION_INVALID,
            "Workflow step code or start-step constraint conflicts",
        )


def delete_step(
    db: Session,
    current_user: User,
    step_id: int,
) -> None:
    step = get_step_or_404(
        db,
        current_user,
        step_id,
    )
    _assert_draft_version(step.version)

    db.delete(step)
    db.commit()


def list_transitions(
    db: Session,
    current_user: User,
    version_id: int,
) -> list[WorkflowTransitionDefinition]:
    version = get_version_or_404(
        db,
        current_user,
        version_id,
    )

    return (
        db.query(WorkflowTransitionDefinition)
        .filter(
            WorkflowTransitionDefinition.workflow_version_id
            == version.id
        )
        .order_by(
            WorkflowTransitionDefinition.id.asc()
        )
        .all()
    )


def _validate_transition_steps(
    db: Session,
    version: WorkflowDefinitionVersion,
    from_step_id: int,
    to_step_id: int,
) -> tuple[
    WorkflowStepDefinition,
    WorkflowStepDefinition,
]:
    rows = (
        db.query(WorkflowStepDefinition)
        .filter(
            WorkflowStepDefinition.workflow_version_id
            == version.id,
            WorkflowStepDefinition.id.in_(
                [from_step_id, to_step_id]
            ),
        )
        .all()
    )

    by_id = {row.id: row for row in rows}
    from_step = by_id.get(from_step_id)
    to_step = by_id.get(to_step_id)

    if from_step is None or to_step is None:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            WORKFLOW_TRANSITION_INVALID,
            "Transition steps must belong to the same workflow version",
        )

    if from_step.id == to_step.id:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            WORKFLOW_TRANSITION_INVALID,
            "Transition source and target must differ",
        )

    if from_step.is_terminal:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            WORKFLOW_TRANSITION_INVALID,
            "Terminal steps cannot have outgoing transitions",
        )

    return from_step, to_step


def create_transition(
    db: Session,
    current_user: User,
    version_id: int,
    data: dict,
) -> WorkflowTransitionDefinition:
    version = get_version_or_404(
        db,
        current_user,
        version_id,
    )
    _assert_draft_version(version)

    _validate_transition_steps(
        db,
        version,
        data["from_step_id"],
        data["to_step_id"],
    )

    transition = WorkflowTransitionDefinition(
        workflow_version_id=version.id,
        **data,
    )
    db.add(transition)

    try:
        db.commit()
        db.refresh(transition)
        return transition
    except IntegrityError:
        db.rollback()
        _raise(
            status.HTTP_409_CONFLICT,
            WORKFLOW_TRANSITION_INVALID,
            "Transition action already exists for this source step",
        )


def update_transition(
    db: Session,
    current_user: User,
    transition_id: int,
    data: dict,
) -> WorkflowTransitionDefinition:
    transition = get_transition_or_404(
        db,
        current_user,
        transition_id,
    )
    version = transition.version
    _assert_draft_version(version)

    from_step_id = data.get(
        "from_step_id",
        transition.from_step_id,
    )
    to_step_id = data.get(
        "to_step_id",
        transition.to_step_id,
    )

    _validate_transition_steps(
        db,
        version,
        from_step_id,
        to_step_id,
    )

    for field, value in data.items():
        setattr(transition, field, value)

    try:
        db.commit()
        db.refresh(transition)
        return transition
    except IntegrityError:
        db.rollback()
        _raise(
            status.HTTP_409_CONFLICT,
            WORKFLOW_TRANSITION_INVALID,
            "Transition action already exists for this source step",
        )


def delete_transition(
    db: Session,
    current_user: User,
    transition_id: int,
) -> None:
    transition = get_transition_or_404(
        db,
        current_user,
        transition_id,
    )
    _assert_draft_version(transition.version)

    db.delete(transition)
    db.commit()


def _validate_graph_structure(
    steps: list,
    transitions: list,
) -> None:
    if not steps:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            WORKFLOW_VERSION_INVALID,
            "Workflow version must contain at least one step",
        )

    starts = [step for step in steps if step.is_start]
    terminals = [step for step in steps if step.is_terminal]

    if len(starts) != 1:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            WORKFLOW_VERSION_INVALID,
            "Workflow version must contain exactly one start step",
        )

    if not terminals:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            WORKFLOW_VERSION_INVALID,
            "Workflow version must contain at least one terminal step",
        )

    step_by_id = {step.id: step for step in steps}
    outgoing = {
        step.id: []
        for step in steps
    }
    incoming = {
        step.id: []
        for step in steps
    }

    for transition in transitions:
        if (
            transition.from_step_id not in step_by_id
            or transition.to_step_id not in step_by_id
        ):
            _raise(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                WORKFLOW_VERSION_INVALID,
                "Every transition must reference steps in this version",
            )

        outgoing[transition.from_step_id].append(
            transition.to_step_id
        )
        incoming[transition.to_step_id].append(
            transition.from_step_id
        )

    for step in steps:
        if step.required_approval_count != 1:
            _raise(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                WORKFLOW_VERSION_INVALID,
                "Multiple approvals per step are not enabled yet",
                {"step_id": step.id},
            )

        if step.is_terminal and outgoing[step.id]:
            _raise(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                WORKFLOW_VERSION_INVALID,
                "Terminal steps cannot have outgoing transitions",
                {"step_id": step.id},
            )

        if not step.is_terminal and not outgoing[step.id]:
            _raise(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                WORKFLOW_VERSION_INVALID,
                "Every non-terminal step must have an outgoing transition",
                {"step_id": step.id},
            )

    reachable = set()
    stack = [starts[0].id]

    while stack:
        step_id = stack.pop()

        if step_id in reachable:
            continue

        reachable.add(step_id)
        stack.extend(outgoing[step_id])

    if reachable != set(step_by_id):
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            WORKFLOW_VERSION_INVALID,
            "Every workflow step must be reachable from the start step",
            {
                "unreachable_step_ids": sorted(
                    set(step_by_id) - reachable
                )
            },
        )

    can_reach_terminal = set()
    stack = [step.id for step in terminals]

    while stack:
        step_id = stack.pop()

        if step_id in can_reach_terminal:
            continue

        can_reach_terminal.add(step_id)
        stack.extend(incoming[step_id])

    if can_reach_terminal != set(step_by_id):
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            WORKFLOW_VERSION_INVALID,
            "Every workflow step must be able to reach a terminal step",
            {
                "blocked_step_ids": sorted(
                    set(step_by_id) - can_reach_terminal
                )
            },
        )


def publish_version(
    db: Session,
    current_user: User,
    version_id: int,
) -> WorkflowDefinitionVersion:
    version = get_version_or_404(
        db,
        current_user,
        version_id,
    )

    if version.status != WorkflowVersionStatus.DRAFT.value:
        _raise(
            status.HTTP_409_CONFLICT,
            WORKFLOW_VERSION_NOT_DRAFT,
            "Only draft workflow versions may be published",
        )

    steps = list(version.steps)
    transitions = list(version.transitions)

    for step in steps:
        _validate_step_target(
            db,
            version.definition.company_id,
            {
                "assignee_type": step.assignee_type,
                "target_user_id": step.target_user_id,
                "target_department_id": step.target_department_id,
                "target_position_id": step.target_position_id,
                "target_role_id": step.target_role_id,
            },
        )

    _validate_graph_structure(
        steps,
        transitions,
    )

    db.query(WorkflowDefinitionVersion).filter(
        WorkflowDefinitionVersion.workflow_definition_id
        == version.workflow_definition_id,
        WorkflowDefinitionVersion.status
        == WorkflowVersionStatus.PUBLISHED.value,
        WorkflowDefinitionVersion.id != version.id,
    ).update(
        {
            WorkflowDefinitionVersion.status:
            WorkflowVersionStatus.ARCHIVED.value
        },
        synchronize_session=False,
    )

    version.status = WorkflowVersionStatus.PUBLISHED.value
    version.published_by_user_id = current_user.id
    version.published_at = datetime.utcnow()

    db.commit()
    db.refresh(version)

    return version
