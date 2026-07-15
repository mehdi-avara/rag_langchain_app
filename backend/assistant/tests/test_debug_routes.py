import pytest
from pathlib import Path
from fastapi import HTTPException

from assistant.tests.fakes import make_user
from assistant.routes import router
from assistant.schemas import TimelineItem
from assistant.permissions import PERMISSIONS


EXPECTED_PATHS = {
    "/debug/chats/{chat_id}",
    "/debug/chats/{chat_id}/messages",
    "/debug/chats/{chat_id}/timeline",
    "/debug/chats/{chat_id}/stream",
    "/debug/messages/{message_id}/run",
    "/debug/runs/{run_id}",
    "/debug/runs/{run_id}/events",
    "/debug/runs/{run_id}/routes",
    "/debug/runs/{run_id}/state",
    "/debug/runs/{run_id}/drafts",
    "/debug/modules",
}


def _permission_dependency(route):
    for dependency in route.dependant.dependencies:
        call = dependency.call
        closure_values = [cell.cell_contents for cell in (getattr(call, "__closure__", None) or [])]
        if "assistant:debug" in closure_values:
            return call
    return None


def test_all_debug_routes_exist_and_require_assistant_debug():
    debug_routes = [route for route in router.routes if route.path.startswith("/debug/")]
    assert {route.path for route in debug_routes} == EXPECTED_PATHS
    assert all(_permission_dependency(route) is not None for route in debug_routes)


def test_debug_permission_rejects_ordinary_assistant_user():
    route = next(route for route in router.routes if route.path == "/debug/modules")
    checker = _permission_dependency(route)
    user = make_user(["assistant:chat", "assistant:draft"])
    with pytest.raises(HTTPException) as exc:
        checker(current_user=user)
    assert exc.value.status_code == 403


def test_debug_permission_is_declared_for_admin_seed_but_not_ordinary_default():
    assert any(permission[0] == "assistant:debug" for permission in PERMISSIONS)
    seed_source = (Path(__file__).parents[2] / "db/seed_rbac.py").read_text()
    assert "permissions_data.extend(ASSISTANT_PERMISSIONS)" in seed_source
    normal_block = seed_source.split("normal_permission_names = {", 1)[1].split("}", 1)[0]
    assert '"assistant:debug"' not in normal_block


def test_generic_timeline_schema_keeps_module_specific_fields_inside_data():
    item = TimelineItem(
        id=9, agent_run_id=2, message_id=10, sequence=4, kind="route",
        event_type="task_finder.selected", stage="task_finder",
        module="purchase_management", task="create_purchase_request",
        title="Task selected", summary="Create purchase request", status="completed",
        severity="info", duration_ms=31, data={"purchase_only_field": "value"},
        created_at="2026-07-15T12:00:00",
    )
    body = item.model_dump(mode="json")
    assert body["module"] == "purchase_management"
    assert body["task"] == "create_purchase_request"
    assert "purchase_only_field" not in body
    assert body["data"] == {"purchase_only_field": "value"}
