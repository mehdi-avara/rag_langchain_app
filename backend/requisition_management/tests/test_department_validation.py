from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from organization_management.models import (
    OrganizationDepartment,
    OrganizationUserAssignment,
)
from requisition_management.services import (
    _resolve_requisition_department,
)


class FakeQuery:
    def __init__(self, db, target):
        self.db = db
        self.target = target

    def join(self, *_args, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.db.results.get(self.target)


class FakeDB:
    def __init__(self, results=None):
        self.results = dict(results or {})

    def query(self, target):
        return FakeQuery(self, target)


def make_user(user_id=7, company_id=3):
    return SimpleNamespace(
        id=user_id,
        company_id=company_id,
    )


def test_explicit_department_requires_active_assignment():
    department = SimpleNamespace(
        id=11,
        company_id=3,
        is_active=True,
    )
    assignment = SimpleNamespace(
        user_id=7,
        company_id=3,
        department_id=11,
        is_active=True,
        is_primary=True,
    )
    db = FakeDB(
        {
            OrganizationDepartment: department,
            OrganizationUserAssignment: assignment,
        }
    )

    result = _resolve_requisition_department(
        db,
        make_user(),
        11,
    )

    assert result == 11


def test_explicit_department_rejects_unknown_or_foreign_department():
    db = FakeDB(
        {
            OrganizationDepartment: None,
        }
    )

    with pytest.raises(HTTPException) as exc:
        _resolve_requisition_department(
            db,
            make_user(),
            11,
        )

    assert exc.value.status_code == 422
    assert (
        exc.value.detail["code"]
        == "MATERIAL_REQUISITION_DEPARTMENT_NOT_FOUND"
    )


def test_explicit_department_rejects_unassigned_requester():
    department = SimpleNamespace(
        id=11,
        company_id=3,
        is_active=True,
    )
    db = FakeDB(
        {
            OrganizationDepartment: department,
            OrganizationUserAssignment: None,
        }
    )

    with pytest.raises(HTTPException) as exc:
        _resolve_requisition_department(
            db,
            make_user(),
            11,
        )

    assert exc.value.status_code == 403
    assert (
        exc.value.detail["code"]
        == "MATERIAL_REQUISITION_DEPARTMENT_ACCESS_DENIED"
    )


def test_missing_department_uses_active_assignment():
    assignment = SimpleNamespace(
        user_id=7,
        company_id=3,
        department_id=22,
        is_active=True,
        is_primary=True,
    )
    db = FakeDB(
        {
            OrganizationUserAssignment: assignment,
        }
    )

    result = _resolve_requisition_department(
        db,
        make_user(),
        None,
    )

    assert result == 22


def test_missing_department_rejects_user_without_assignment():
    db = FakeDB(
        {
            OrganizationUserAssignment: None,
        }
    )

    with pytest.raises(HTTPException) as exc:
        _resolve_requisition_department(
            db,
            make_user(),
            None,
        )

    assert exc.value.status_code == 422
    assert (
        exc.value.detail["code"]
        == "MATERIAL_REQUISITION_DEPARTMENT_REQUIRED"
    )
