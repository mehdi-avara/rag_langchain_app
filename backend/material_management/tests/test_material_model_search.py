from types import SimpleNamespace

import material_management.search.service as search_service
import material_management.services as material_services
import model_management.services as model_services
from material_management.assistant_tools import (
    MaterialAssistantToolSet,
    _item_to_candidate,
)
from material_management.schemas import ItemModelSummaryOut, ItemSearchHit


def _user():
    return SimpleNamespace(id=3, company_id=7)


def _item(model_id=9):
    return SimpleNamespace(
        id=5,
        company_id=7,
        item_code="MOTOR-H42L",
        name="Electromotor",
        description="Complete motor",
        category_id=2,
        unit_id=3,
        model_id=model_id,
        item_type="equipment",
        is_active=True,
        is_critical=False,
    )


def _model_summary(model_id=9):
    return ItemModelSummaryOut(
        id=model_id,
        manufacturer="Siemens",
        model="H42L",
        type="electromotor",
    )


def test_resolve_material_model_ids_uses_model_service_seam(monkeypatch):
    captured = {}

    def fake_find_model_ids(db, current_user, **filters):
        captured.update(filters)
        return [9]

    monkeypatch.setattr(model_services, "find_model_ids", fake_find_model_ids)

    result = material_services.resolve_material_model_ids(
        object(),
        _user(),
        model_id=9,
        model_name="H42L",
        manufacturer="Siemens",
        model_type="electromotor",
    )

    assert result == [9]
    assert captured == {
        "query_text": None,
        "ids": [9],
        "model_name": "H42L",
        "manufacturer": "Siemens",
        "model_type": "electromotor",
    }


def test_keyword_material_search_matches_and_returns_model_summary(monkeypatch):
    captured = {}

    def fake_resolve(db, current_user, **filters):
        if filters.get("query_text"):
            return [9]
        return [9]

    def fake_text_search(**kwargs):
        captured.update(kwargs)
        return [_item()]

    monkeypatch.setattr(search_service, "resolve_material_model_ids", fake_resolve)
    monkeypatch.setattr(search_service, "search_items_text", fake_text_search)
    monkeypatch.setattr(
        search_service,
        "item_model_summaries",
        lambda db, current_user, model_ids: {9: _model_summary()},
    )

    hits = search_service.search_item_hits(
        db=object(),
        current_user=_user(),
        query_text="H42L",
        mode="keyword",
        manufacturer="Siemens",
        model_type="electromotor",
    )

    assert captured["model_ids"] == [9]
    assert captured["matching_model_ids"] == [9]
    assert hits[0].model_id == 9
    assert hits[0].model is not None
    assert hits[0].model.manufacturer == "Siemens"
    assert hits[0].model.model == "H42L"


def test_material_search_returns_early_when_model_filter_has_no_match(monkeypatch):
    monkeypatch.setattr(
        search_service,
        "resolve_material_model_ids",
        lambda db, current_user, **filters: ([9] if filters.get("query_text") else []),
    )

    called = False

    def fake_text_search(**kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(search_service, "search_items_text", fake_text_search)

    hits = search_service.search_item_hits(
        db=object(),
        current_user=_user(),
        query_text="motor",
        mode="keyword",
        model_name="does-not-exist",
    )

    assert hits == []
    assert called is False


def test_assistant_material_result_displays_linked_model():
    hit = ItemSearchHit(
        item_id=5,
        company_id=7,
        item_code="MOTOR-H42L",
        name="Electromotor",
        description="Complete motor",
        category_id=2,
        unit_id=3,
        model_id=9,
        model=_model_summary(),
        item_type="equipment",
        is_active=True,
        is_critical=False,
        match_source="text",
    )

    candidate = _item_to_candidate(hit)
    assistant_item = MaterialAssistantToolSet()._item(
        MaterialAssistantToolSet.search_specs[0],
        hit,
    )

    assert "Siemens" in candidate.label
    assert "H42L" in candidate.label
    assert "Siemens" in assistant_item["title"]
    assert "H42L" in assistant_item["title"]
    assert assistant_item["data"]["model"]["type"] == "electromotor"
