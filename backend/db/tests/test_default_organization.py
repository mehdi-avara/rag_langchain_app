from types import SimpleNamespace

from Models import (
    OrganizationDepartment,
    OrganizationPosition,
    OrganizationUserAssignment,
    User,
)
from db.provision_company_defaults import (
    DEFAULT_DEPARTMENT_CODE,
    DEFAULT_POSITION_CODE,
    _ensure_default_organization,
)


class FakeQuery:
    def __init__(self, db, target):
        self.db = db
        self.target = target

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.db.first_results.get(self.target)

    def all(self):
        return list(self.db.all_results.get(self.target, []))


class FakeDB:
    def __init__(self):
        self.first_results = {}
        self.all_results = {}
        self.added = []
        self.next_id = 100

    def query(self, target):
        return FakeQuery(self, target)

    def add(self, value):
        self.added.append(value)

    def flush(self):
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = self.next_id
                self.next_id += 1


def test_default_organization_creates_assignments_for_unassigned_users():
    db = FakeDB()
    db.first_results = {
        OrganizationDepartment: None,
        OrganizationPosition: None,
    }
    db.all_results = {
        OrganizationUserAssignment: [],
        User: [
            SimpleNamespace(id=1, company_id=9, is_active=True),
            SimpleNamespace(id=2, company_id=9, is_active=True),
        ],
    }

    department, position = _ensure_default_organization(
        db,
        company_id=9,
    )

    assignments = [
        value
        for value in db.added
        if isinstance(value, OrganizationUserAssignment)
    ]

    assert department.code == DEFAULT_DEPARTMENT_CODE
    assert position.code == DEFAULT_POSITION_CODE
    assert position.department_id == department.id
    assert len(assignments) == 2
    assert {item.user_id for item in assignments} == {1, 2}
    assert all(item.department_id == department.id for item in assignments)
    assert all(item.position_id == position.id for item in assignments)
    assert all(item.is_primary is True for item in assignments)


def test_default_organization_does_not_duplicate_active_assignment():
    department = OrganizationDepartment(
        id=10,
        company_id=9,
        code=DEFAULT_DEPARTMENT_CODE,
        name="General",
        is_active=True,
    )
    position = OrganizationPosition(
        id=20,
        company_id=9,
        department_id=10,
        code=DEFAULT_POSITION_CODE,
        title="Member",
        is_active=True,
    )
    existing_assignment = OrganizationUserAssignment(
        id=30,
        company_id=9,
        user_id=1,
        department_id=10,
        position_id=20,
        is_primary=True,
        is_active=True,
    )

    db = FakeDB()
    db.first_results = {
        OrganizationDepartment: department,
        OrganizationPosition: position,
    }
    db.all_results = {
        OrganizationUserAssignment: [existing_assignment],
        User: [
            SimpleNamespace(id=1, company_id=9, is_active=True),
            SimpleNamespace(id=2, company_id=9, is_active=True),
        ],
    }

    _ensure_default_organization(
        db,
        company_id=9,
    )

    assignments = [
        value
        for value in db.added
        if isinstance(value, OrganizationUserAssignment)
    ]

    assert len(assignments) == 1
    assert assignments[0].user_id == 2
