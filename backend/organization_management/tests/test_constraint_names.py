from organization_management.models import (
    OrganizationDepartment,
    OrganizationPosition,
    OrganizationUserAssignment,
)


def test_organization_database_names_fit_postgresql_limit():
    tables = [
        OrganizationDepartment.__table__,
        OrganizationPosition.__table__,
        OrganizationUserAssignment.__table__,
    ]

    names = []

    for table in tables:
        names.extend(
            constraint.name
            for constraint in table.constraints
            if constraint.name
        )
        names.extend(
            index.name
            for index in table.indexes
            if index.name
        )

    too_long = {
        name: len(name)
        for name in names
        if len(name) > 63
    }

    assert too_long == {}


def test_explicit_short_constraint_names_are_present():
    names = {
        constraint.name
        for table in [
            OrganizationDepartment.__table__,
            OrganizationPosition.__table__,
            OrganizationUserAssignment.__table__,
        ]
        for constraint in table.constraints
        if constraint.name
    }

    assert "fk_org_departments_parent" in names
    assert "fk_org_positions_department" in names
    assert "fk_org_assignments_department" in names
    assert "fk_org_assignments_position" in names
    assert "ck_organization_departments_not_self_parent" in names
    assert "ck_organization_user_assignments_valid_dates" in names
