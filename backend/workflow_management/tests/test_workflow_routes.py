from fastapi import FastAPI

from workflow_management.routes import workflow_router


def test_workflow_designer_routes_are_registered():
    app = FastAPI()
    app.include_router(workflow_router)

    paths = set(app.openapi()["paths"])

    assert {
        "/workflow/definitions",
        "/workflow/definitions/{definition_id}",
        "/workflow/definitions/{definition_id}/versions",
        "/workflow/versions/{version_id}",
        "/workflow/versions/{version_id}/publish",
        "/workflow/versions/{version_id}/steps",
        "/workflow/steps/{step_id}",
        "/workflow/versions/{version_id}/transitions",
        "/workflow/transitions/{transition_id}",
    }.issubset(paths)
