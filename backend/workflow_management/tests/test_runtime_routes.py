from fastapi import FastAPI

from workflow_management.routes import workflow_router


def test_workflow_runtime_routes_are_registered():
    app = FastAPI()
    app.include_router(workflow_router)

    paths = set(app.openapi()["paths"])

    assert {
        "/workflow/instances",
        "/workflow/instances/inbox",
        "/workflow/instances/{instance_id}",
        "/workflow/instances/{instance_id}/actions",
        "/workflow/instances/{instance_id}/cancel",
        "/workflow/instances/{instance_id}/files",
        (
            "/workflow/instances/{instance_id}/files/"
            "{workflow_file_id}"
        ),
        "/workflow/instances/{instance_id}/audit",
    }.issubset(paths)
