from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from assistant.tests.fakes import ALL_COMMERCE_PERMS, FakeProvider, make_user

import goods_receipt_management.assistant_tools as goods_receipt_tools
import material_management.assistant_tools as material_tools
import purchase_management.assistant_tools as purchase_tools
import requisition_management.assistant_tools as requisition_tools
import rfq_management.assistant_tools as rfq_tools
import supplier_management.assistant_tools as supplier_tools
import warehouse_management.assistant_tools as warehouse_tools
from assistant import registry, router as router_mod
from assistant.graph import build_assistant_graph
from assistant.module_interface import Candidate, ResourceSpec, get_resource, register_resource
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


def test_material_item_resolves_category_and_unit_names_to_english_id_fields():
    saved_category = get_resource("item_category")
    saved_unit = get_resource("material_unit")
    register_resource(ResourceSpec(
        key="item_category",
        read_permission="material_management:read",
        provider=FakeProvider([
            Candidate(
                id=5,
                match_text="Spare Parts",
                label="SPARE - Spare Parts",
                data={"id": 5, "code": "SPARE", "name": "Spare Parts"},
            )
        ]),
        create_permission="material_management:create",
        create_endpoint="/materials/categories",
    ))
    register_resource(ResourceSpec(
        key="material_unit",
        read_permission="material_management:read",
        provider=FakeProvider([
            Candidate(
                id=2,
                match_text="Piece",
                label="PCS - Piece - count",
                data={"id": 2, "code": "PCS", "name": "Piece", "unit_type": "count"},
            )
        ]),
        create_permission="material_management:create",
        create_endpoint="/materials/units",
    ))
    try:
        draft = material_tools.MaterialAssistantToolSet().build_draft(
            intent="add_item",
            db=None,
            user=make_user(ALL_COMMERCE_PERMS),
            slots={
                "item_code": "PUMP-SEAL",
                "name": "Pump seal",
                "category": "Spare Parts",
                "unit": "Piece",
            },
            attachments=[],
        )
    finally:
        if saved_category is not None:
            register_resource(saved_category)
        if saved_unit is not None:
            register_resource(saved_unit)

    assert draft.valid is True
    assert draft.payload["category_id"] == 5
    assert draft.payload["unit_id"] == 2
    assert "category" not in draft.payload
    assert "unit" not in draft.payload
    assert draft.commit_target == {
        "method": "POST",
        "endpoint": "/materials",
        "permission": "material_management:create",
    }


def test_material_item_missing_unit_name_returns_partial_reference():
    saved_category = get_resource("item_category")
    saved_unit = get_resource("material_unit")
    register_resource(ResourceSpec(
        key="item_category",
        read_permission="material_management:read",
        provider=FakeProvider([
            Candidate(
                id=5,
                match_text="Spare Parts",
                label="SPARE - Spare Parts",
                data={"id": 5, "code": "SPARE", "name": "Spare Parts"},
            )
        ]),
        create_permission="material_management:create",
        create_endpoint="/materials/categories",
    ))
    register_resource(ResourceSpec(
        key="material_unit",
        read_permission="material_management:read",
        provider=FakeProvider([]),
        create_permission="material_management:create",
        create_endpoint="/materials/units",
        suggestion_from=lambda raw, slots: {"code": raw, "name": raw},
    ))
    try:
        draft = material_tools.MaterialAssistantToolSet().build_draft(
            intent="add_item",
            db=None,
            user=make_user(ALL_COMMERCE_PERMS),
            slots={
                "item_code": "BELZONA-M22",
                "name": "Belzona adhesive M22",
                "category": "Spare Parts",
                "unit": "box",
            },
            attachments=[],
        )
    finally:
        if saved_category is not None:
            register_resource(saved_category)
        if saved_unit is not None:
            register_resource(saved_unit)

    assert draft.valid is False
    assert draft.commit_target == {}
    assert draft.payload["category_id"] == 5
    assert "unit_id" not in draft.payload
    assert "unit" in draft.validation["missing"]
    reference = next(ref for ref in draft.validation["references"] if ref["field"] == "unit_id")
    assert reference["status"] == "missing"
    assert reference["create_suggestion"]["endpoint"] == "/materials/units"
    assert "unit" in draft.clarify_question


def test_material_item_ambiguous_category_returns_choices():
    saved_category = get_resource("item_category")
    saved_unit = get_resource("material_unit")
    register_resource(ResourceSpec(
        key="item_category",
        read_permission="material_management:read",
        provider=FakeProvider([
            Candidate(
                id=5,
                match_text="Mechanical Spare Parts",
                label="MECH - Mechanical Spare Parts",
                data={"id": 5, "code": "MECH", "name": "Mechanical Spare Parts"},
            ),
            Candidate(
                id=6,
                match_text="Electrical Spare Parts",
                label="ELEC - Electrical Spare Parts",
                data={"id": 6, "code": "ELEC", "name": "Electrical Spare Parts"},
            ),
        ]),
        create_permission="material_management:create",
        create_endpoint="/materials/categories",
    ))
    register_resource(ResourceSpec(
        key="material_unit",
        read_permission="material_management:read",
        provider=FakeProvider([
            Candidate(
                id=2,
                match_text="Piece",
                label="PCS - Piece - count",
                data={"id": 2, "code": "PCS", "name": "Piece", "unit_type": "count"},
            )
        ]),
    ))
    try:
        draft = material_tools.MaterialAssistantToolSet().build_draft(
            intent="add_item",
            db=None,
            user=make_user(ALL_COMMERCE_PERMS),
            slots={
                "item_code": "PUMP-SEAL",
                "name": "Pump seal",
                "category": "Spare Parts",
                "unit": "Piece",
            },
            attachments=[],
        )
    finally:
        if saved_category is not None:
            register_resource(saved_category)
        if saved_unit is not None:
            register_resource(saved_unit)

    assert draft.valid is False
    reference = next(ref for ref in draft.validation["references"] if ref["field"] == "category_id")
    assert reference["status"] == "ambiguous"
    assert reference["chosen"]["id"] == 5
    assert reference["alternatives"][0]["id"] == 6
    assert "category" in draft.clarify_question


def test_material_item_resolves_optional_model_name_to_model_id():
    saved_category = get_resource("item_category")
    saved_unit = get_resource("material_unit")
    saved_model = get_resource("managed_model")
    register_resource(ResourceSpec(
        key="item_category",
        read_permission="material_management:read",
        provider=FakeProvider([
            Candidate(id=5, match_text="Spare Parts", label="SPARE - Spare Parts", data={})
        ]),
    ))
    register_resource(ResourceSpec(
        key="material_unit",
        read_permission="material_management:read",
        provider=FakeProvider([
            Candidate(id=2, match_text="Piece", label="PCS - Piece - count", data={})
        ]),
    ))
    register_resource(ResourceSpec(
        key="managed_model",
        read_permission="models:read",
        provider=FakeProvider([
            Candidate(
                id=77,
                match_text="M22",
                label="Belzona - M22 - material",
                data={"id": 77, "manufacturer": "Belzona", "model": "M22"},
            )
        ]),
        create_permission="models:create",
        create_endpoint="/models",
    ))
    try:
        draft = material_tools.MaterialAssistantToolSet().build_draft(
            intent="add_item",
            db=None,
            user=make_user(ALL_COMMERCE_PERMS),
            slots={
                "item_code": "BELZONA-M22",
                "name": "Belzona adhesive M22",
                "category": "Spare Parts",
                "unit": "Piece",
                "model": "M22",
            },
            attachments=[],
        )
    finally:
        if saved_category is not None:
            register_resource(saved_category)
        if saved_unit is not None:
            register_resource(saved_unit)
        if saved_model is not None:
            register_resource(saved_model)

    assert draft.valid is True
    assert draft.payload["model_id"] == 77
    assert "model" not in draft.payload


def test_material_requisition_resolves_item_name_to_item_id():
    saved = get_resource("material_item")
    register_resource(ResourceSpec(
        key="material_item",
        read_permission="material_management:search",
        provider=FakeProvider([
            Candidate(
                id=99,
                match_text="Pump seal",
                label="PUMP-SEAL - Pump seal",
                data={"item_id": 99, "item_code": "PUMP-SEAL", "name": "Pump seal"},
            )
        ]),
        create_permission="material_management:create",
        create_endpoint="/materials",
        suggestion_from=lambda raw, slots: {"name": raw, "item_code": raw},
    ))
    try:
        draft = requisition_tools.RequisitionAssistantToolSet().build_draft(
            intent="add_material_requisition",
            db=None,
            user=make_user(ALL_COMMERCE_PERMS),
            slots={
                "needed_by_date": "2026-08-01",
                "reason": "pump repair",
                "item_name": "Pump seal",
                "quantity": "2",
            },
            attachments=[],
        )
    finally:
        if saved is not None:
            register_resource(saved)

    assert draft.valid is True
    assert draft.target_action == "create_material_requisition"
    assert draft.payload["items"] == [{"quantity": "2", "item_id": 99}]
    assert draft.commit_target == {
        "method": "POST",
        "endpoint": "/requisitions",
        "permission": "requisition_management:create",
    }
    assert draft.validation["references"][0]["chosen"]["label"] == "PUMP-SEAL - Pump seal"


def test_material_requisition_resolves_item_currency_codes_to_ids():
    saved_item = get_resource("material_item")
    saved_currency = get_resource("currency")
    register_resource(ResourceSpec(
        key="material_item",
        read_permission="material_management:search",
        provider=FakeProvider([
            Candidate(id=99, match_text="Pump seal", label="PUMP-SEAL - Pump seal", data={})
        ]),
    ))
    register_resource(ResourceSpec(
        key="currency",
        read_permission="currencies:read",
        provider=FakeProvider([
            Candidate(id=1, match_text="IRT", label="IRT - Toman", data={"code": "IRT"}),
        ]),
    ))
    try:
        draft = requisition_tools.RequisitionAssistantToolSet().build_draft(
            intent="add_material_requisition",
            db=None,
            user=make_user(ALL_COMMERCE_PERMS),
            slots={
                "needed_by_date": "2026-08-01",
                "reason": "pump repair",
                "item_name": "Pump seal",
                "quantity": "2",
                "estimated_unit_cost": "100",
                "currency": "IRT",
                "estimated_unit_cost_base": "100",
                "base_currency": "IRT",
                "exchange_rate_used": "1",
            },
            attachments=[],
        )
    finally:
        if saved_item is not None:
            register_resource(saved_item)
        if saved_currency is not None:
            register_resource(saved_currency)

    assert draft.valid is True
    assert draft.payload["items"] == [{
        "quantity": "2",
        "estimated_unit_cost": "100",
        "estimated_unit_cost_base": "100",
        "exchange_rate_used": "1",
        "item_id": 99,
        "currency_id": 1,
        "base_currency_id": 1,
    }]


def test_material_requisition_missing_item_returns_partial_with_create_suggestion():
    saved = get_resource("material_item")
    register_resource(ResourceSpec(
        key="material_item",
        read_permission="material_management:search",
        provider=FakeProvider([]),
        create_permission="material_management:create",
        create_endpoint="/materials",
        suggestion_from=lambda raw, slots: {"name": raw, "item_code": raw},
    ))
    try:
        draft = requisition_tools.RequisitionAssistantToolSet().build_draft(
            intent="add_material_requisition",
            db=None,
            user=make_user(ALL_COMMERCE_PERMS),
            slots={
                "needed_by_date": "2026-08-01",
                "reason": "pump repair",
                "item_name": "Persian pump seal",
                "quantity": "2",
            },
            attachments=[],
        )
    finally:
        if saved is not None:
            register_resource(saved)

    assert draft.valid is False
    assert draft.commit_target == {}
    assert draft.payload["items"] == [{"item_query": "Persian pump seal", "quantity": "2"}]
    assert "item" in draft.validation["missing"]
    reference = draft.validation["references"][0]
    assert reference["status"] == "missing"
    assert reference["create_suggestion"]["endpoint"] == "/materials"
    assert "create it" in draft.clarify_question


def test_material_requisition_weak_item_hits_are_missing_not_ambiguous():
    saved = get_resource("material_item")
    register_resource(ResourceSpec(
        key="material_item",
        read_permission="material_management:search",
        provider=FakeProvider([
            Candidate(
                id=7,
                match_text="Legacy tewtwe tetw",
                label="LEGACY-WI-1 - Legacy tewtwe tetw #C77700 - material",
                data={"item_id": 7, "item_code": "LEGACY-WI-1", "name": "Legacy tewtwe tetw"},
            ),
            Candidate(
                id=11,
                match_text="test",
                label="32412312 - test - material",
                data={"item_id": 11, "item_code": "32412312", "name": "test"},
            ),
        ]),
        create_permission="material_management:create",
        create_endpoint="/materials",
        suggestion_from=lambda raw, slots: {"name": raw, "item_code": raw},
    ))
    try:
        draft = requisition_tools.RequisitionAssistantToolSet().build_draft(
            intent="add_material_requisition",
            db=None,
            user=make_user(ALL_COMMERCE_PERMS),
            slots={
                "item_name": "چسب belzona مدل m22",
            },
            attachments=[],
        )
    finally:
        if saved is not None:
            register_resource(saved)

    reference = draft.validation["references"][0]
    assert draft.valid is False
    assert reference["status"] == "missing"
    assert reference["alternatives"] == []
    assert reference["create_suggestion"]["endpoint"] == "/materials"
    assert "create it" in draft.clarify_question


def test_purchase_order_from_rfq_uses_rfq_conversion_endpoint():
    saved = get_resource("rfq")
    register_resource(ResourceSpec(
        key="rfq",
        read_permission="rfq_management:search",
        provider=FakeProvider([
            Candidate(
                id=17,
                match_text="RFQ-17",
                label="RFQ-17 - Pump parts",
                data={"rfq_id": 17, "rfq_number": "RFQ-17", "title": "Pump parts"},
            )
        ]),
    ))
    try:
        draft = purchase_tools.PurchaseAssistantToolSet().build_draft(
            intent="add_purchase_order",
            db=None,
            user=make_user(ALL_COMMERCE_PERMS),
            slots={"rfq_query": "RFQ-17"},
            attachments=[],
        )
    finally:
        if saved is not None:
            register_resource(saved)

    assert draft.valid is True
    assert draft.payload == {}
    assert draft.commit_target == {
        "method": "POST",
        "endpoint": "/purchase/orders/from-rfq/17",
        "permission": "purchase_management:orders:create",
        "additional_permissions": ["rfq_management:read"],
        "entity_id": 17,
    }


def test_purchase_order_resolves_currency_codes_to_ids():
    saved_currency = get_resource("currency")
    register_resource(ResourceSpec(
        key="currency",
        read_permission="currencies:read",
        provider=FakeProvider([
            Candidate(id=1, match_text="IRT", label="IRT - Toman", data={"code": "IRT"}),
        ]),
    ))
    try:
        draft = purchase_tools.PurchaseAssistantToolSet().build_draft(
            intent="add_purchase_order",
            db=None,
            user=make_user(ALL_COMMERCE_PERMS),
            slots={
                "title": "Direct pump PO",
                "currency": "IRT",
                "base_currency": "IRT",
            },
            attachments=[],
        )
    finally:
        if saved_currency is not None:
            register_resource(saved_currency)

    assert draft.valid is True
    assert draft.payload["currency_id"] == 1
    assert draft.payload["base_currency_id"] == 1
    assert draft.commit_target == {
        "method": "POST",
        "endpoint": "/purchase/orders",
        "permission": "purchase_management:orders:create",
    }


def test_update_purchase_order_resolves_supplier_and_currency_text():
    saved_supplier = get_resource("supplier")
    saved_currency = get_resource("currency")
    register_resource(ResourceSpec(
        key="supplier",
        read_permission="supplier_management:search",
        provider=FakeProvider([
            Candidate(id=44, match_text="ACME", label="SUP-44 - ACME", data={})
        ]),
    ))
    register_resource(ResourceSpec(
        key="currency",
        read_permission="currencies:read",
        provider=FakeProvider([
            Candidate(id=1, match_text="IRT", label="IRT - Toman", data={"code": "IRT"}),
        ]),
    ))
    try:
        draft = purchase_tools.PurchaseAssistantToolSet().build_draft(
            intent="update_purchase_order",
            db=None,
            user=make_user(ALL_COMMERCE_PERMS),
            slots={
                "purchase_order_id": 12,
                "supplier": "ACME",
                "currency": "IRT",
                "base_currency": "IRT",
            },
            attachments=[],
        )
    finally:
        if saved_supplier is not None:
            register_resource(saved_supplier)
        if saved_currency is not None:
            register_resource(saved_currency)

    assert draft.valid is True
    assert draft.payload["supplier_id"] == 44
    assert draft.payload["currency_id"] == 1
    assert draft.payload["base_currency_id"] == 1
    assert draft.commit_target["endpoint"] == "/purchase/orders/12"


def test_rfq_from_mr_and_supplier_names_resolve_to_ids():
    saved_mr = get_resource("material_requisition")
    saved_supplier = get_resource("supplier")
    register_resource(ResourceSpec(
        key="material_requisition",
        read_permission="requisition_management:search",
        provider=FakeProvider([
            Candidate(
                id=31,
                match_text="MR-31",
                label="MR-31 - approved",
                data={"requisition_id": 31, "mr_number": "MR-31"},
            )
        ]),
    ))
    register_resource(ResourceSpec(
        key="supplier",
        read_permission="supplier_management:search",
        provider=FakeProvider([
            Candidate(
                id=44,
                match_text="ACME",
                label="SUP-44 - ACME",
                data={"supplier_id": 44, "name": "ACME"},
            )
        ]),
    ))
    try:
        draft = rfq_tools.RFQAssistantToolSet().build_draft(
            intent="add_rfq",
            db=None,
            user=make_user(ALL_COMMERCE_PERMS),
            slots={
                "title": "Pump parts RFQ",
                "deadline_date": "2026-08-10",
                "mr_query": "MR-31",
                "supplier_name": "ACME",
            },
            attachments=[],
        )
    finally:
        if saved_mr is not None:
            register_resource(saved_mr)
        if saved_supplier is not None:
            register_resource(saved_supplier)

    assert draft.valid is True
    assert draft.payload["mr_id"] == 31
    assert draft.payload["supplier_ids"] == [44]
    assert "items" not in draft.payload


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


def test_stock_adjustment_resolves_locations_and_currency_text():
    saved_item = get_resource("material_item")
    saved_location = get_resource("storage_location")
    saved_currency = get_resource("currency")
    register_resource(ResourceSpec(
        key="material_item",
        read_permission="material_management:search",
        provider=FakeProvider([
            Candidate(id=99, match_text="Pump seal", label="PUMP-SEAL - Pump seal", data={})
        ]),
    ))
    register_resource(ResourceSpec(
        key="storage_location",
        read_permission="warehouse_management:stock:read",
        provider=FakeProvider([
            Candidate(id=7, match_text="Main Bin", label="MAIN-BIN - Main Bin", data={}),
        ]),
    ))
    register_resource(ResourceSpec(
        key="currency",
        read_permission="currencies:read",
        provider=FakeProvider([
            Candidate(id=1, match_text="IRT", label="IRT - Toman", data={"code": "IRT"}),
        ]),
    ))
    try:
        draft = warehouse_tools.WarehouseAssistantToolSet().build_draft(
            intent="add_stock_adjustment",
            db=None,
            user=make_user(ALL_COMMERCE_PERMS),
            slots={
                "item_name": "Pump seal",
                "to_location": "Main Bin",
                "quantity": "3",
                "unit_cost": "100",
                "currency": "IRT",
                "unit_cost_base": "100",
                "base_currency": "IRT",
                "exchange_rate_used": "1",
            },
            attachments=[],
        )
    finally:
        if saved_item is not None:
            register_resource(saved_item)
        if saved_location is not None:
            register_resource(saved_location)
        if saved_currency is not None:
            register_resource(saved_currency)

    assert draft.valid is True
    assert draft.payload["item_id"] == 99
    assert draft.payload["to_location_id"] == 7
    assert draft.payload["currency_id"] == 1
    assert draft.payload["base_currency_id"] == 1


def test_update_goods_receipt_resolves_warehouse_text():
    saved_warehouse = get_resource("warehouse")
    register_resource(ResourceSpec(
        key="warehouse",
        read_permission="warehouse_management:stock:read",
        provider=FakeProvider([
            Candidate(id=3, match_text="Main Warehouse", label="MAIN - Main Warehouse", data={})
        ]),
    ))
    try:
        draft = goods_receipt_tools.GoodsReceiptAssistantToolSet().build_draft(
            intent="update_goods_receipt",
            db=None,
            user=make_user(ALL_COMMERCE_PERMS),
            slots={"goods_receipt_id": 8, "warehouse": "Main Warehouse"},
            attachments=[],
        )
    finally:
        if saved_warehouse is not None:
            register_resource(saved_warehouse)

    assert draft.valid is True
    assert draft.payload["warehouse_id"] == 3
    assert draft.commit_target["endpoint"] == "/goods-receipts/8"


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


def test_vlm_extracted_commerce_slots_build_material_requisition_draft(monkeypatch):
    captured_router_call = {}
    saved = get_resource("material_item")
    register_resource(ResourceSpec(
        key="material_item",
        read_permission="material_management:search",
        provider=FakeProvider([
            Candidate(
                id=99,
                match_text="Pump seal",
                label="PUMP-SEAL - Pump seal",
                data={"item_id": 99, "item_code": "PUMP-SEAL", "name": "Pump seal"},
            )
        ]),
        create_permission="material_management:create",
        create_endpoint="/materials",
        suggestion_from=lambda raw, slots: {"name": raw, "item_code": raw},
    ))

    async def fake_classify(**kwargs):
        captured_router_call.update(kwargs)
        return {
            "intent": "add_material_requisition",
            "language": "fa",
            "slots": {
                "needed_by_date": "2026-08-01",
                "reason": "پمپ تعمیر شود",
                "item_name": "Pump seal",
                "quantity": "2",
            },
            "clarify_question": None,
        }

    monkeypatch.setattr(router_mod, "classify", fake_classify)
    image_blocks = [
        {
            "type": "image_url",
            "image_url": {
                "url": "data:image/png;base64,AAAA",
                "detail": "low",
            },
        }
    ]
    try:
        result = asyncio.run(
            build_assistant_graph().ainvoke(
                {
                    "user": make_user(ALL_COMMERCE_PERMS),
                    "db": None,
                    "question": "از روی عکس یک درخواست کالا بساز",
                    "attachments": [123],
                    "image_blocks": image_blocks,
                    "slots": {},
                    "step_count": 0,
                }
            )
        )
    finally:
        if saved is not None:
            register_resource(saved)

    assert captured_router_call["has_attachments"] is True
    assert captured_router_call["image_blocks"] == image_blocks
    draft = result.get("pending_draft")
    assert draft is not None
    assert draft["target_module"] == "requisition_management"
    assert draft["target_action"] == "create_material_requisition"
    assert draft["payload"]["needed_by_date"] == "2026-08-01"
    assert draft["payload"]["reason"] == "پمپ تعمیر شود"
    assert draft["payload"]["items"] == [{"quantity": "2", "item_id": 99}]
    assert draft["commit_target"] == {
        "method": "POST",
        "endpoint": "/requisitions",
        "permission": "requisition_management:create",
    }
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
