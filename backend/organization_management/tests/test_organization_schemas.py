from datetime import date

import pytest
from pydantic import ValidationError

from organization_management.schemas import (
    OrganizationDepartmentCreate,
    OrganizationPositionCreate,
    OrganizationUserAssignmentCreate,
)


def test_department_normalizes_code_and_text():
    department = OrganizationDepartmentCreate(
        code=" finance ",
        name=" Finance Department ",
        description=" Main finance team ",
    )

    assert department.code == "FINANCE"
    assert department.name == "Finance Department"
    assert department.description == "Main finance team"


def test_position_normalizes_code_and_title():
    position = OrganizationPositionCreate(
        code=" finance_manager ",
        title=" Finance Manager ",
    )

    assert position.code == "FINANCE_MANAGER"
    assert position.title == "Finance Manager"


def test_assignment_rejects_invalid_date_range():
    with pytest.raises(ValidationError):
        OrganizationUserAssignmentCreate(
            user_id=1,
            department_id=2,
            start_date=date(2026, 7, 20),
            end_date=date(2026, 7, 19),
        )
