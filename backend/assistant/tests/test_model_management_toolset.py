from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
import json
from types import SimpleNamespace

import pytest

from assistant.tests.fakes import make_user
from assistant import registry
from assistant.module_interface import get_resource
from core.exceptions.app_exception import AppException
from core.exceptions.error_codes import PERMISSION_DENIED
import model_management.assistant_tools as model_tools
from shared import commerce_assistant as commerce_tools


MODEL_PERMISSIONS = (
    "assistant:chat",
    "assistant:draft",
    "models:read",
    "models:search",
    "models:ask",
    "models:create",
    "models:update",
)


def _user(*permissions):
    return make_user(permissions or MODEL_PERMISSIONS)


def test_model_management_toolset_is_registered_and_rbac_filtered():
    assert (
        registry.get_toolset("model_management")
        is not None
    )

    names = {
        spec.name
        for spec in registry.assemble_intents(_user())
    }
    assert {
        "search_models",
        "ask_models",
        "add_model",
        "update_model",
    }.issubset(names)

    read_only = _user(
        "assistant:chat",
        "models:read",
        "models:search",
    )
    read_only_names = {
        spec.name
        for spec in registry.assemble_intents(read_only)
    }
    assert "search_models" in read_only_names
    assert "add_model" not in read_only_names
    assert "update_model" not in read_only_names


def test_model_management_descriptors_explain_equipment_models():
    toolset = model_tools.ModelManagementAssistantToolSet()
    descriptor = toolset.module_descriptor()
    tasks = {
        task.intent: task
        for task in toolset.task_descriptors()
    }

    assert descriptor.display_title == "Equipment Model Management"
    assert "not AI models" in descriptor.description
    assert "Flowserve" in tasks["add_model"].examples[0]
    assert "مدل" in tasks["add_model"].examples[1]


def test_complete_add_model_returns_draft_without_domain_write():
    class NoWriteDB:
        def __init__(self):
            self.added = []
            self.commits = 0

        def add(self, value):
            self.added.append(value)

        def commit(self):
            self.commits += 1

    db = NoWriteDB()
    draft = (
        model_tools.ModelManagementAssistantToolSet()
        .build_draft(
            intent="add_model",
            db=db,
            user=_user(),
            slots={
                "manufacturer": "Flowserve",
                "model_name": "Mark 3",
                "equipment_type": "centrifugal pump",
                "model_description": "ANSI process pump",
            },
            attachments=[],
        )
    )

    assert draft.valid is True
    assert draft.target_module == "model_management"
    assert draft.target_action == "create_model"
    assert draft.payload == {
        "manufacturer": "Flowserve",
        "model": "Mark 3",
        "description": "ANSI process pump",
        "type": "centrifugal pump",
    }
    assert draft.commit_target == {
        "method": "POST",
        "endpoint": "/models/",
        "permission": "models:create",
    }
    assert db.added == []
    assert db.commits == 0


def test_add_model_missing_required_field_returns_partial_draft():
    draft = (
        model_tools.ModelManagementAssistantToolSet()
        .build_draft(
            intent="add_model",
            db=None,
            user=_user(),
            slots={"model": "Mark 3", "type": "pump"},
            attachments=[],
        )
    )

    assert draft.valid is False
    assert draft.commit_target == {}
    assert draft.payload == {
        "model": "Mark 3",
        "type": "pump",
    }
    assert draft.validation["missing"] == ["manufacturer"]


def test_update_model_uses_existing_patch_endpoint():
    draft = (
        model_tools.ModelManagementAssistantToolSet()
        .build_draft(
            intent="update_model",
            db=None,
            user=_user(),
            slots={
                "model_id": 42,
                "description": "Updated technical description",
            },
            attachments=[],
        )
    )

    assert draft.valid is True
    assert draft.target_action == "update_model"
    assert draft.payload == {
        "description": "Updated technical description",
    }
    assert draft.commit_target == {
        "method": "PATCH",
        "endpoint": "/models/42",
        "permission": "models:update",
        "entity_id": 42,
    }


def test_model_resource_is_owned_and_searchable_by_model_management():
    resource = get_resource("managed_model")

    assert resource is not None
    assert resource.read_permission == "models:read"
    assert resource.create_permission == "models:create"
    assert resource.create_endpoint == "/models/"
    assert (
        resource.provider._search_fn.__module__
        == "model_management.services"
    )


def test_search_models_returns_grounded_model_references():
    captured = {}

    def fake_search(**kwargs):
        captured.update(kwargs)
        return [
            SimpleNamespace(
                id=42,
                manufacturer="Flowserve",
                model="Mark 3",
                type="centrifugal pump",
                description="ANSI process pump",
                created_at=datetime(2026, 5, 8, 13, 25, 12, 597370),
            )
        ]

    toolset = model_tools.ModelManagementAssistantToolSet()
    toolset.search_specs = (
        replace(
            toolset.search_specs[0],
            search_fn=fake_search,
        ),
    )
    output = asyncio.run(
        toolset.handle_read(
            intent="search_models",
            db=None,
            user=_user(),
            slots={"query": "Flowserve", "limit": 5},
        )
    )

    assert captured["query_text"] == "Flowserve"
    assert captured["limit"] == 5
    assert (
        output["retrieved_items"][0]["citation_key"]
        == "model:42"
    )
    assert output["citations"] == ["model:42"]
    assert output["retrieved_items"][0]["data"]["created_at"] == (
        "2026-05-08T13:25:12.597370"
    )
    json.dumps(output["retrieved_items"])


def test_ask_models_uses_grounded_model_records(monkeypatch):
    async def fake_answer_from_references(**kwargs):
        assert kwargs["citation_prefix"] == "model"
        assert kwargs["references"][0].id == 42
        return "It is a centrifugal pump. [model:42]"

    def fake_search(**kwargs):
        return [
            SimpleNamespace(
                id=42,
                manufacturer="Flowserve",
                model="Mark 3",
                type="centrifugal pump",
                description="ANSI process pump",
            )
        ]

    monkeypatch.setattr(
        commerce_tools,
        "answer_from_references",
        fake_answer_from_references,
    )
    toolset = model_tools.ModelManagementAssistantToolSet()
    toolset.search_specs = (
        replace(
            toolset.search_specs[0],
            search_fn=fake_search,
        ),
    )

    output = asyncio.run(
        toolset.handle_read(
            intent="ask_models",
            db=None,
            user=_user(),
            slots={"question": "What type is Mark 3?"},
        )
    )

    assert output["answer"].startswith(
        "It is a centrifugal pump"
    )
    assert output["citations"] == ["model:42"]


def test_model_write_rechecks_permission_before_building_draft():
    with pytest.raises(AppException) as exc:
        (
            model_tools.ModelManagementAssistantToolSet()
            .build_draft(
                intent="add_model",
                db=None,
                user=_user("assistant:chat", "models:read"),
                slots={
                    "manufacturer": "Flowserve",
                    "model": "Mark 3",
                },
                attachments=[],
            )
        )

    assert exc.value.code == PERMISSION_DENIED
