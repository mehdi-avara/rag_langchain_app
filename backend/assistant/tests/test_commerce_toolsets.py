from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from assistant.tests.fakes import ALL_COMMERCE_PERMS, make_user

import goods_receipt_management.assistant_tools  # noqa: F401
import material_management.assistant_tools as material_tools
import purchase_management.assistant_tools  # noqa: F401
import requisition_management.assistant_tools  # noqa: F401
import rfq_management.assistant_tools  # noqa: F401
import supplier_management.assistant_tools as supplier_tools
import warehouse_management.assistant_tools  # noqa: F401
from assistant import registry, router as router_mod
from assistant.graph import build_assistant_graph
from core.exceptions.app_exception import AppException
from core.exceptions.error_codes import PERMISSION_DENIED
from shared import commerce_assistant as commerce_tools


def _names(user):
    return {spec.name for spec in registry.assemble_intents(user)}


def test_commerce_registry_respects_rbac():
    user = make_user(ALL_COMMERCE_PERMS)
    names = _names(user)
    assert "search_suppliers" in names
    assert "add_supplier" in names
    assert "search_items" in names
    assert "add_material_requisition" in names
    assert "add_rfq" in names
    assert "add_purchase_order" in names
    assert "add_goods_receipt" in names
    assert "add_stock_adjustment" in names

    no_supplier_create = make_user([p for p in ALL_COMMERCE_PERMS if p != "supplier_management:create"])
    names = _names(no_supplier_create)
    assert "add_supplier" not in names
    assert "search_suppliers" in names


def test_commerce_search_handler_returns_retrieved_items(monkeypatch):
    def fake_search(**kwargs):
        return [
            SimpleNamespace(
                supplier_id=12,
                code="SUP-12",
                name="ACME",
                supplier_type="local",
                status="approved",
            )
        ]

    toolset = supplier_tools.SupplierAssistantToolSet()
    toolset.search_specs = (replace(toolset.search_specs[0], search_fn=fake_search),)
    out = asyncio.run(
        toolset.handle_read(
            intent="search_suppliers",
            db=None,
            user=make_user(ALL_COMMERCE_PERMS),
            slots={"query": "ACME"},
        )
    )
    assert out["retrieved_items"][0]["citation_key"] == "supplier:12"
    assert out["retrieved_items"][0]["data"]["name"] == "ACME"
    assert out["citations"] == ["supplier:12"]


def test_commerce_ask_handler_returns_answer_and_references(monkeypatch):
    captured = {}

    async def fake_answer_from_references(**kwargs):
        captured.update(kwargs)
        return "ACME is approved. [supplier:12]"

    def fake_search(**kwargs):
        return [SimpleNamespace(supplier_id=12, code="SUP-12", name="ACME", status="approved")]

    monkeypatch.setattr(commerce_tools, "answer_from_references", fake_answer_from_references)
    toolset = supplier_tools.SupplierAssistantToolSet()
    toolset.search_specs = (replace(toolset.search_specs[0], search_fn=fake_search),)
    out = asyncio.run(
        toolset.handle_read(
            intent="ask_suppliers",
            db=None,
            user=make_user(ALL_COMMERCE_PERMS),
            slots={"question": "Is ACME approved?"},
        )
    )
    assert out["answer"].startswith("ACME is approved")
    assert out["retrieved_items"][0]["citation_key"] == "supplier:12"
    assert out["citations"] == ["supplier:12"]
    assert captured["language"] == "en"


def test_commerce_ask_handler_detects_persian_answer_language(monkeypatch):
    captured = {}

    async def fake_answer_from_references(**kwargs):
        captured.update(kwargs)
        return "بله، ACME تایید شده است. [supplier:12]"

    def fake_search(**kwargs):
        return [SimpleNamespace(supplier_id=12, code="SUP-12", name="ACME", status="approved")]

    monkeypatch.setattr(commerce_tools, "answer_from_references", fake_answer_from_references)
    toolset = supplier_tools.SupplierAssistantToolSet()
    toolset.search_specs = (replace(toolset.search_specs[0], search_fn=fake_search),)
    out = asyncio.run(
        toolset.handle_read(
            intent="ask_suppliers",
            db=None,
            user=make_user(ALL_COMMERCE_PERMS),
            slots={"question": "آیا تامین‌کننده ACME تایید شده است؟"},
        )
    )
    assert out["answer"].startswith("بله")
    assert out["citations"] == ["supplier:12"]
    assert captured["language"] == "fa"


def test_commerce_read_handler_rechecks_permission():
    user = make_user([p for p in ALL_COMMERCE_PERMS if p != "supplier_management:search"])
    with pytest.raises(AppException) as exc:
        asyncio.run(
            supplier_tools.SupplierAssistantToolSet().handle_read(
                intent="search_suppliers",
                db=None,
                user=user,
                slots={"query": "x"},
            )
        )
    assert exc.value.code == PERMISSION_DENIED


def test_incomplete_commerce_write_returns_partial_draft():
    draft = material_tools.MaterialAssistantToolSet().build_draft(
        intent="add_item",
        db=None,
        user=make_user(ALL_COMMERCE_PERMS),
        slots={"item_code": "PUMP-SEAL"},
        attachments=[],
    )
    assert draft.valid is False
    assert draft.commit_target == {}
    assert draft.payload["item_code"] == "PUMP-SEAL"
    assert set(draft.validation["missing"]) == {"name", "category_id", "unit_id"}


def test_complete_commerce_write_returns_pending_draft_commit_target():
    draft = supplier_tools.SupplierAssistantToolSet().build_draft(
        intent="add_supplier",
        db=None,
        user=make_user(ALL_COMMERCE_PERMS),
        slots={"name": "ACME", "supplier_type": "local", "status": "approved"},
        attachments=[],
    )
    assert draft.valid is True
    assert draft.target_module == "supplier_management"
    assert draft.target_action == "create_supplier"
    assert draft.commit_target == {
        "method": "POST",
        "endpoint": "/supplier_management/suppliers",
        "permission": "supplier_management:create",
    }
    assert draft.payload["name"] == "ACME"


def test_update_commerce_write_uses_entity_id():
    draft = supplier_tools.SupplierAssistantToolSet().build_draft(
        intent="update_supplier",
        db=None,
        user=make_user(ALL_COMMERCE_PERMS),
        slots={"supplier_id": 42, "city": "Tehran"},
        attachments=[],
    )
    assert draft.valid is True
    assert draft.commit_target["method"] == "PATCH"
    assert draft.commit_target["endpoint"] == "/supplier_management/suppliers/42"
    assert draft.commit_target["entity_id"] == 42


def test_graph_routes_commerce_write_to_draft_not_commit(monkeypatch):
    async def fake_classify(**kwargs):
        return {
            "intent": "add_supplier",
            "language": "en",
            "slots": {"name": "ACME"},
            "clarify_question": None,
        }

    monkeypatch.setattr(router_mod, "classify", fake_classify)
    result = asyncio.run(
        build_assistant_graph().ainvoke(
            {
                "user": make_user(ALL_COMMERCE_PERMS),
                "db": None,
                "question": "add supplier ACME",
                "attachments": [],
                "slots": {},
                "step_count": 0,
            }
        )
    )
    draft = result.get("pending_draft")
    assert draft is not None
    assert draft["target_action"] == "create_supplier"
    assert draft["commit_target"]["endpoint"] == "/supplier_management/suppliers"
    assert "committed_entity_ref" not in draft


def test_followup_merges_previous_commerce_partial_draft(monkeypatch):
    async def fake_classify(**kwargs):
        return {
            "intent": "add_item",
            "language": "en",
            "slots": {"name": "Pump seal", "category_id": 5, "unit_id": 2},
            "clarify_question": None,
        }

    previous = {
        "target_module": "material_management",
        "target_action": "create_item",
        "payload": {"item_code": "PUMP-SEAL"},
        "missing": ["name", "category_id", "unit_id"],
    }
    monkeypatch.setattr(router_mod, "classify", fake_classify)
    result = asyncio.run(
        build_assistant_graph().ainvoke(
            {
                "user": make_user(ALL_COMMERCE_PERMS),
                "db": None,
                "question": "name is Pump seal, category 5, unit 2",
                "attachments": [],
                "slots": {},
                "step_count": 0,
                "active_partial_draft": previous,
            }
        )
    )
    draft = result.get("pending_draft")
    assert draft is not None
    assert draft["payload"]["item_code"] == "PUMP-SEAL"
    assert draft["payload"]["name"] == "Pump seal"
    assert draft["payload"]["category_id"] == 5
    assert draft["payload"]["unit_id"] == 2
