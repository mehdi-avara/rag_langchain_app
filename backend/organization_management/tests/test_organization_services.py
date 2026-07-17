from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from organization_management.services import (
    _validate_assignment_dates,
    _validate_position_department_match,
    tenant_id,
)


def test_tenant_id_returns_company_id():
    user = SimpleNamespace(company_id=12)

    assert tenant_id(user) == 12


def test_tenant_id_rejects_user_without_company():
    user = SimpleNamespace(company_id=None)

    with pytest.raises(HTTPException) as exc:
        tenant_id(user)

    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "USER_HAS_NO_COMPANY"


def test_position_must_match_assignment_department():
    position = SimpleNamespace(
        id=9,
        company_id=1,
        department_id=5,
    )

    with pytest.raises(HTTPException) as exc:
        _validate_position_department_match(
            position,
            department_id=7,
        )

    assert exc.value.status_code == 422
    assert (
        exc.value.detail["code"]
        == "ORGANIZATION_POSITION_DEPARTMENT_MISMATCH"
    )


def test_company_wide_position_can_be_used_in_any_department():
    position = SimpleNamespace(
        id=9,
        company_id=1,
        department_id=None,
    )

    _validate_position_department_match(
        position,
        department_id=7,
    )


def test_assignment_service_rejects_invalid_dates():
    with pytest.raises(HTTPException):
        _validate_assignment_dates(
            date(2026, 7, 20),
            date(2026, 7, 19),
        )
