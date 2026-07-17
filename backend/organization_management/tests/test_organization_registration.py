from fastapi import FastAPI

from organization_management.permissions import PERMISSIONS
from organization_management.routes import organization_router


def test_permission_names_are_registered():
    names = {item[0] for item in PERMISSIONS}

    assert names == {
        "organization:departments:read",
        "organization:departments:manage",
        "organization:positions:read",
        "organization:positions:manage",
        "organization:assignments:read",
        "organization:assignments:manage",
    }


def test_router_contains_expected_paths():
    app = FastAPI()
    app.include_router(organization_router)

    paths = set(app.openapi()["paths"])

    assert "/organization/departments" in paths
    assert "/organization/departments/{department_id}" in paths
    assert "/organization/positions" in paths
    assert "/organization/positions/{position_id}" in paths
    assert "/organization/assignments" in paths
    assert "/organization/assignments/{assignment_id}" in paths
    assert "/organization/users/{user_id}/assignments" in paths
    assert "/organization/me/assignments" in paths
