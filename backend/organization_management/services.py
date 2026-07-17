from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from Models.user import User
from core.exceptions.error_codes import (
    ORGANIZATION_ASSIGNMENT_ALREADY_EXISTS,
    ORGANIZATION_ASSIGNMENT_INVALID_DEPARTMENT,
    ORGANIZATION_ASSIGNMENT_INVALID_POSITION,
    ORGANIZATION_ASSIGNMENT_INVALID_USER,
    ORGANIZATION_ASSIGNMENT_NOT_FOUND,
    ORGANIZATION_ASSIGNMENT_PRIMARY_CONFLICT,
    ORGANIZATION_DEPARTMENT_ALREADY_EXISTS,
    ORGANIZATION_DEPARTMENT_IN_USE,
    ORGANIZATION_DEPARTMENT_MANAGER_INVALID,
    ORGANIZATION_DEPARTMENT_NOT_FOUND,
    ORGANIZATION_DEPARTMENT_PARENT_INVALID,
    ORGANIZATION_POSITION_ALREADY_EXISTS,
    ORGANIZATION_POSITION_DEPARTMENT_MISMATCH,
    ORGANIZATION_POSITION_IN_USE,
    ORGANIZATION_POSITION_NOT_FOUND,
    USER_HAS_NO_COMPANY,
)

from .models import (
    OrganizationDepartment,
    OrganizationPosition,
    OrganizationUserAssignment,
)


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


def tenant_id(current_user: User) -> int:
    if current_user.company_id is None:
        _raise(
            status.HTTP_403_FORBIDDEN,
            USER_HAS_NO_COMPANY,
            "Current user does not belong to a company",
        )

    return current_user.company_id


def get_department_or_404(
    db: Session,
    current_user: User,
    department_id: int,
) -> OrganizationDepartment:
    department = (
        db.query(OrganizationDepartment)
        .filter(
            OrganizationDepartment.id == department_id,
            OrganizationDepartment.company_id
            == tenant_id(current_user),
        )
        .first()
    )

    if department is None:
        _raise(
            status.HTTP_404_NOT_FOUND,
            ORGANIZATION_DEPARTMENT_NOT_FOUND,
            "Department not found",
        )

    return department


def _validate_parent_department(
    db: Session,
    company_id: int,
    parent_department_id: Optional[int],
    current_department_id: Optional[int] = None,
) -> None:
    if parent_department_id is None:
        return

    if (
        current_department_id is not None
        and parent_department_id == current_department_id
    ):
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ORGANIZATION_DEPARTMENT_PARENT_INVALID,
            "A department cannot be its own parent",
        )

    parent = (
        db.query(OrganizationDepartment)
        .filter(
            OrganizationDepartment.id == parent_department_id,
            OrganizationDepartment.company_id == company_id,
        )
        .first()
    )

    if parent is None:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ORGANIZATION_DEPARTMENT_PARENT_INVALID,
            "Parent department is invalid",
        )

    if current_department_id is None:
        return

    visited = set()
    cursor = parent

    while cursor is not None:
        if cursor.id == current_department_id:
            _raise(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                ORGANIZATION_DEPARTMENT_PARENT_INVALID,
                "Department hierarchy cannot contain a cycle",
            )

        if cursor.id in visited:
            _raise(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                ORGANIZATION_DEPARTMENT_PARENT_INVALID,
                "Department hierarchy contains a cycle",
            )

        visited.add(cursor.id)

        if cursor.parent_department_id is None:
            break

        cursor = (
            db.query(OrganizationDepartment)
            .filter(
                OrganizationDepartment.id
                == cursor.parent_department_id,
                OrganizationDepartment.company_id == company_id,
            )
            .first()
        )


def _validate_manager(
    db: Session,
    company_id: int,
    manager_user_id: Optional[int],
) -> None:
    if manager_user_id is None:
        return

    manager = (
        db.query(User)
        .filter(
            User.id == manager_user_id,
            User.company_id == company_id,
            User.is_active.is_(True),
        )
        .first()
    )

    if manager is None:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ORGANIZATION_DEPARTMENT_MANAGER_INVALID,
            "Department manager is invalid",
        )


def _department_conflict(
    db: Session,
    company_id: int,
    code: str,
    name: str,
    exclude_id: Optional[int] = None,
) -> Optional[OrganizationDepartment]:
    query = db.query(OrganizationDepartment).filter(
        OrganizationDepartment.company_id == company_id,
        or_(
            OrganizationDepartment.code == code,
            OrganizationDepartment.name == name,
        ),
    )

    if exclude_id is not None:
        query = query.filter(
            OrganizationDepartment.id != exclude_id
        )

    return query.first()


def list_departments(
    db: Session,
    current_user: User,
    is_active: Optional[bool] = None,
    parent_department_id: Optional[int] = None,
) -> list[OrganizationDepartment]:
    query = db.query(OrganizationDepartment).filter(
        OrganizationDepartment.company_id == tenant_id(current_user)
    )

    if is_active is not None:
        query = query.filter(
            OrganizationDepartment.is_active.is_(is_active)
        )

    if parent_department_id is not None:
        query = query.filter(
            OrganizationDepartment.parent_department_id
            == parent_department_id
        )

    return query.order_by(
        OrganizationDepartment.name.asc(),
        OrganizationDepartment.id.asc(),
    ).all()


def create_department(
    db: Session,
    current_user: User,
    data: dict,
) -> OrganizationDepartment:
    company_id = tenant_id(current_user)

    _validate_parent_department(
        db,
        company_id,
        data.get("parent_department_id"),
    )
    _validate_manager(
        db,
        company_id,
        data.get("manager_user_id"),
    )

    conflict = _department_conflict(
        db,
        company_id,
        data["code"],
        data["name"],
    )

    if conflict is not None:
        _raise(
            status.HTTP_409_CONFLICT,
            ORGANIZATION_DEPARTMENT_ALREADY_EXISTS,
            "Department code or name already exists",
        )

    department = OrganizationDepartment(
        company_id=company_id,
        **data,
    )
    db.add(department)

    try:
        db.commit()
        db.refresh(department)
        return department
    except IntegrityError:
        db.rollback()
        _raise(
            status.HTTP_409_CONFLICT,
            ORGANIZATION_DEPARTMENT_ALREADY_EXISTS,
            "Department code or name already exists",
        )


def update_department(
    db: Session,
    current_user: User,
    department_id: int,
    data: dict,
) -> OrganizationDepartment:
    department = get_department_or_404(
        db,
        current_user,
        department_id,
    )
    company_id = tenant_id(current_user)

    code = data.get("code", department.code)
    name = data.get("name", department.name)

    conflict = _department_conflict(
        db,
        company_id,
        code,
        name,
        exclude_id=department.id,
    )

    if conflict is not None:
        _raise(
            status.HTTP_409_CONFLICT,
            ORGANIZATION_DEPARTMENT_ALREADY_EXISTS,
            "Department code or name already exists",
        )

    if "parent_department_id" in data:
        _validate_parent_department(
            db,
            company_id,
            data["parent_department_id"],
            current_department_id=department.id,
        )

    if "manager_user_id" in data:
        _validate_manager(
            db,
            company_id,
            data["manager_user_id"],
        )

    if data.get("is_active") is False:
        active_child = (
            db.query(OrganizationDepartment.id)
            .filter(
                OrganizationDepartment.company_id == company_id,
                OrganizationDepartment.parent_department_id
                == department.id,
                OrganizationDepartment.is_active.is_(True),
            )
            .first()
        )
        active_position = (
            db.query(OrganizationPosition.id)
            .filter(
                OrganizationPosition.company_id == company_id,
                OrganizationPosition.department_id == department.id,
                OrganizationPosition.is_active.is_(True),
            )
            .first()
        )
        active_assignment = (
            db.query(OrganizationUserAssignment.id)
            .filter(
                OrganizationUserAssignment.company_id == company_id,
                OrganizationUserAssignment.department_id
                == department.id,
                OrganizationUserAssignment.is_active.is_(True),
            )
            .first()
        )

        if (
            active_child is not None
            or active_position is not None
            or active_assignment is not None
        ):
            _raise(
                status.HTTP_409_CONFLICT,
                ORGANIZATION_DEPARTMENT_IN_USE,
                "Department has active dependent records",
            )

    for field, value in data.items():
        setattr(department, field, value)

    try:
        db.commit()
        db.refresh(department)
        return department
    except IntegrityError:
        db.rollback()
        _raise(
            status.HTTP_409_CONFLICT,
            ORGANIZATION_DEPARTMENT_ALREADY_EXISTS,
            "Department code or name already exists",
        )


def deactivate_department(
    db: Session,
    current_user: User,
    department_id: int,
) -> None:
    update_department(
        db,
        current_user,
        department_id,
        {"is_active": False},
    )


def get_position_or_404(
    db: Session,
    current_user: User,
    position_id: int,
) -> OrganizationPosition:
    position = (
        db.query(OrganizationPosition)
        .filter(
            OrganizationPosition.id == position_id,
            OrganizationPosition.company_id
            == tenant_id(current_user),
        )
        .first()
    )

    if position is None:
        _raise(
            status.HTTP_404_NOT_FOUND,
            ORGANIZATION_POSITION_NOT_FOUND,
            "Position not found",
        )

    return position


def _validate_position_department(
    db: Session,
    current_user: User,
    department_id: Optional[int],
) -> Optional[OrganizationDepartment]:
    if department_id is None:
        return None

    return get_department_or_404(
        db,
        current_user,
        department_id,
    )


def _position_conflict(
    db: Session,
    company_id: int,
    code: str,
    exclude_id: Optional[int] = None,
) -> Optional[OrganizationPosition]:
    query = db.query(OrganizationPosition).filter(
        OrganizationPosition.company_id == company_id,
        OrganizationPosition.code == code,
    )

    if exclude_id is not None:
        query = query.filter(
            OrganizationPosition.id != exclude_id
        )

    return query.first()


def list_positions(
    db: Session,
    current_user: User,
    department_id: Optional[int] = None,
    is_active: Optional[bool] = None,
) -> list[OrganizationPosition]:
    query = db.query(OrganizationPosition).filter(
        OrganizationPosition.company_id == tenant_id(current_user)
    )

    if department_id is not None:
        query = query.filter(
            OrganizationPosition.department_id == department_id
        )

    if is_active is not None:
        query = query.filter(
            OrganizationPosition.is_active.is_(is_active)
        )

    return query.order_by(
        OrganizationPosition.title.asc(),
        OrganizationPosition.id.asc(),
    ).all()


def create_position(
    db: Session,
    current_user: User,
    data: dict,
) -> OrganizationPosition:
    company_id = tenant_id(current_user)

    _validate_position_department(
        db,
        current_user,
        data.get("department_id"),
    )

    if _position_conflict(db, company_id, data["code"]) is not None:
        _raise(
            status.HTTP_409_CONFLICT,
            ORGANIZATION_POSITION_ALREADY_EXISTS,
            "Position code already exists",
        )

    position = OrganizationPosition(
        company_id=company_id,
        **data,
    )
    db.add(position)

    try:
        db.commit()
        db.refresh(position)
        return position
    except IntegrityError:
        db.rollback()
        _raise(
            status.HTTP_409_CONFLICT,
            ORGANIZATION_POSITION_ALREADY_EXISTS,
            "Position code already exists",
        )


def update_position(
    db: Session,
    current_user: User,
    position_id: int,
    data: dict,
) -> OrganizationPosition:
    position = get_position_or_404(
        db,
        current_user,
        position_id,
    )
    company_id = tenant_id(current_user)
    code = data.get("code", position.code)

    if (
        _position_conflict(
            db,
            company_id,
            code,
            exclude_id=position.id,
        )
        is not None
    ):
        _raise(
            status.HTTP_409_CONFLICT,
            ORGANIZATION_POSITION_ALREADY_EXISTS,
            "Position code already exists",
        )

    if "department_id" in data:
        _validate_position_department(
            db,
            current_user,
            data["department_id"],
        )

    if data.get("is_active") is False:
        active_assignment = (
            db.query(OrganizationUserAssignment.id)
            .filter(
                OrganizationUserAssignment.company_id == company_id,
                OrganizationUserAssignment.position_id == position.id,
                OrganizationUserAssignment.is_active.is_(True),
            )
            .first()
        )

        if active_assignment is not None:
            _raise(
                status.HTTP_409_CONFLICT,
                ORGANIZATION_POSITION_IN_USE,
                "Position has active assignments",
            )

    for field, value in data.items():
        setattr(position, field, value)

    try:
        db.commit()
        db.refresh(position)
        return position
    except IntegrityError:
        db.rollback()
        _raise(
            status.HTTP_409_CONFLICT,
            ORGANIZATION_POSITION_ALREADY_EXISTS,
            "Position code already exists",
        )


def deactivate_position(
    db: Session,
    current_user: User,
    position_id: int,
) -> None:
    update_position(
        db,
        current_user,
        position_id,
        {"is_active": False},
    )


def get_assignment_or_404(
    db: Session,
    current_user: User,
    assignment_id: int,
) -> OrganizationUserAssignment:
    assignment = (
        db.query(OrganizationUserAssignment)
        .filter(
            OrganizationUserAssignment.id == assignment_id,
            OrganizationUserAssignment.company_id
            == tenant_id(current_user),
        )
        .first()
    )

    if assignment is None:
        _raise(
            status.HTTP_404_NOT_FOUND,
            ORGANIZATION_ASSIGNMENT_NOT_FOUND,
            "Organization assignment not found",
        )

    return assignment


def _get_valid_assignment_user(
    db: Session,
    company_id: int,
    user_id: int,
) -> User:
    user = (
        db.query(User)
        .filter(
            User.id == user_id,
            User.company_id == company_id,
            User.is_active.is_(True),
        )
        .first()
    )

    if user is None:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ORGANIZATION_ASSIGNMENT_INVALID_USER,
            "Assignment user is invalid",
        )

    return user


def _get_valid_assignment_department(
    db: Session,
    company_id: int,
    department_id: int,
) -> OrganizationDepartment:
    department = (
        db.query(OrganizationDepartment)
        .filter(
            OrganizationDepartment.id == department_id,
            OrganizationDepartment.company_id == company_id,
            OrganizationDepartment.is_active.is_(True),
        )
        .first()
    )

    if department is None:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ORGANIZATION_ASSIGNMENT_INVALID_DEPARTMENT,
            "Assignment department is invalid",
        )

    return department


def _get_valid_assignment_position(
    db: Session,
    company_id: int,
    position_id: Optional[int],
) -> Optional[OrganizationPosition]:
    if position_id is None:
        return None

    position = (
        db.query(OrganizationPosition)
        .filter(
            OrganizationPosition.id == position_id,
            OrganizationPosition.company_id == company_id,
            OrganizationPosition.is_active.is_(True),
        )
        .first()
    )

    if position is None:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ORGANIZATION_ASSIGNMENT_INVALID_POSITION,
            "Assignment position is invalid",
        )

    return position


def _validate_assignment_dates(
    start_date: Optional[date],
    end_date: Optional[date],
) -> None:
    if (
        start_date is not None
        and end_date is not None
        and end_date < start_date
    ):
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ORGANIZATION_ASSIGNMENT_ALREADY_EXISTS,
            "end_date cannot be earlier than start_date",
        )


def _validate_position_department_match(
    position: Optional[OrganizationPosition],
    department_id: int,
) -> None:
    if (
        position is not None
        and position.department_id is not None
        and position.department_id != department_id
    ):
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ORGANIZATION_POSITION_DEPARTMENT_MISMATCH,
            "Position does not belong to the selected department",
        )


def _ensure_primary_assignment_available(
    db: Session,
    company_id: int,
    user_id: int,
    is_primary: bool,
    is_active: bool,
    exclude_id: Optional[int] = None,
) -> None:
    if not is_primary or not is_active:
        return

    query = db.query(OrganizationUserAssignment).filter(
        OrganizationUserAssignment.company_id == company_id,
        OrganizationUserAssignment.user_id == user_id,
        OrganizationUserAssignment.is_primary.is_(True),
        OrganizationUserAssignment.is_active.is_(True),
    )

    if exclude_id is not None:
        query = query.filter(
            OrganizationUserAssignment.id != exclude_id
        )

    if query.first() is not None:
        _raise(
            status.HTTP_409_CONFLICT,
            ORGANIZATION_ASSIGNMENT_PRIMARY_CONFLICT,
            "User already has an active primary assignment",
        )


def _ensure_assignment_not_duplicate(
    db: Session,
    company_id: int,
    user_id: int,
    department_id: int,
    position_id: Optional[int],
    exclude_id: Optional[int] = None,
) -> None:
    query = db.query(OrganizationUserAssignment).filter(
        OrganizationUserAssignment.company_id == company_id,
        OrganizationUserAssignment.user_id == user_id,
        OrganizationUserAssignment.department_id == department_id,
        OrganizationUserAssignment.is_active.is_(True),
    )

    if position_id is None:
        query = query.filter(
            OrganizationUserAssignment.position_id.is_(None)
        )
    else:
        query = query.filter(
            OrganizationUserAssignment.position_id == position_id
        )

    if exclude_id is not None:
        query = query.filter(
            OrganizationUserAssignment.id != exclude_id
        )

    if query.first() is not None:
        _raise(
            status.HTTP_409_CONFLICT,
            ORGANIZATION_ASSIGNMENT_ALREADY_EXISTS,
            "Active organization assignment already exists",
        )


def list_assignments(
    db: Session,
    current_user: User,
    user_id: Optional[int] = None,
    department_id: Optional[int] = None,
    position_id: Optional[int] = None,
    is_active: Optional[bool] = None,
) -> list[OrganizationUserAssignment]:
    query = db.query(OrganizationUserAssignment).filter(
        OrganizationUserAssignment.company_id == tenant_id(current_user)
    )

    if user_id is not None:
        query = query.filter(
            OrganizationUserAssignment.user_id == user_id
        )

    if department_id is not None:
        query = query.filter(
            OrganizationUserAssignment.department_id == department_id
        )

    if position_id is not None:
        query = query.filter(
            OrganizationUserAssignment.position_id == position_id
        )

    if is_active is not None:
        query = query.filter(
            OrganizationUserAssignment.is_active.is_(is_active)
        )

    return query.order_by(
        OrganizationUserAssignment.is_primary.desc(),
        OrganizationUserAssignment.created_at.desc(),
        OrganizationUserAssignment.id.desc(),
    ).all()


def create_assignment(
    db: Session,
    current_user: User,
    data: dict,
) -> OrganizationUserAssignment:
    company_id = tenant_id(current_user)
    user_id = data["user_id"]
    department_id = data["department_id"]
    position_id = data.get("position_id")
    is_primary = bool(data.get("is_primary", False))
    is_active = bool(data.get("is_active", True))

    _get_valid_assignment_user(db, company_id, user_id)
    _get_valid_assignment_department(
        db,
        company_id,
        department_id,
    )
    position = _get_valid_assignment_position(
        db,
        company_id,
        position_id,
    )
    _validate_position_department_match(
        position,
        department_id,
    )
    _validate_assignment_dates(
        data.get("start_date"),
        data.get("end_date"),
    )
    _ensure_primary_assignment_available(
        db,
        company_id,
        user_id,
        is_primary,
        is_active,
    )
    _ensure_assignment_not_duplicate(
        db,
        company_id,
        user_id,
        department_id,
        position_id,
    )

    assignment = OrganizationUserAssignment(
        company_id=company_id,
        **data,
    )
    db.add(assignment)

    try:
        db.commit()
        db.refresh(assignment)
        return assignment
    except IntegrityError:
        db.rollback()
        _raise(
            status.HTTP_409_CONFLICT,
            ORGANIZATION_ASSIGNMENT_PRIMARY_CONFLICT,
            "Organization assignment conflicts with an existing record",
        )


def update_assignment(
    db: Session,
    current_user: User,
    assignment_id: int,
    data: dict,
) -> OrganizationUserAssignment:
    assignment = get_assignment_or_404(
        db,
        current_user,
        assignment_id,
    )
    company_id = tenant_id(current_user)

    user_id = data.get("user_id", assignment.user_id)
    department_id = data.get(
        "department_id",
        assignment.department_id,
    )
    position_id = (
        data["position_id"]
        if "position_id" in data
        else assignment.position_id
    )
    is_primary = data.get(
        "is_primary",
        assignment.is_primary,
    )
    is_active = data.get(
        "is_active",
        assignment.is_active,
    )
    start_date = data.get(
        "start_date",
        assignment.start_date,
    )
    end_date = (
        data["end_date"]
        if "end_date" in data
        else assignment.end_date
    )

    _get_valid_assignment_user(db, company_id, user_id)
    _get_valid_assignment_department(
        db,
        company_id,
        department_id,
    )
    position = _get_valid_assignment_position(
        db,
        company_id,
        position_id,
    )
    _validate_position_department_match(
        position,
        department_id,
    )
    _validate_assignment_dates(start_date, end_date)
    _ensure_primary_assignment_available(
        db,
        company_id,
        user_id,
        is_primary,
        is_active,
        exclude_id=assignment.id,
    )

    if is_active:
        _ensure_assignment_not_duplicate(
            db,
            company_id,
            user_id,
            department_id,
            position_id,
            exclude_id=assignment.id,
        )

    for field, value in data.items():
        setattr(assignment, field, value)

    try:
        db.commit()
        db.refresh(assignment)
        return assignment
    except IntegrityError:
        db.rollback()
        _raise(
            status.HTTP_409_CONFLICT,
            ORGANIZATION_ASSIGNMENT_PRIMARY_CONFLICT,
            "Organization assignment conflicts with an existing record",
        )


def deactivate_assignment(
    db: Session,
    current_user: User,
    assignment_id: int,
) -> None:
    assignment = get_assignment_or_404(
        db,
        current_user,
        assignment_id,
    )
    assignment.is_active = False
    assignment.is_primary = False
    db.commit()
