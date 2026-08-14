from __future__ import annotations

from types import SimpleNamespace

from assistant.module_interface import (
    Candidate,
    ResourceSpec,
    get_resource,
    register_resource,
)
from assistant.tests.fakes import ALL_COMMERCE_PERMS, FakeDB, FakeProvider, make_user
import material_management.assistant_tools as material_tools
from model_management.services import (
    _field_match_score,
    _model_identifier_match,
    find_model_candidates_for_material_reference,
)
import requisition_management.assistant_tools as requisition_tools


def test_material_resolution_passes_structured_model_filters(monkeypatch):
    captured = {}

    def fake_search(**kwargs):
        captured.update(kwargs)
        return ["matched-item"]

    monkeypatch.setattr(material_tools, "search_item_hits", fake_search)

    result = material_tools._search_items_for_resolution(
        db=None,
        current_user=make_user(ALL_COMMERCE_PERMS),
        query_text="electromotor",
        context={
            "manufacturer": "Siemens",
            "model_name": "H42L",
            "model_type": "electromotor",
        },
    )

    assert result == ["matched-item"]
    assert captured["manufacturer"] == "Siemens"
    assert captured["model_name"] == "H42L"
    assert captured["model_type"] == "electromotor"
    assert captured["item_type"] == "equipment"


def test_model_reference_scoring_tolerates_small_manufacturer_typo():
    assert _field_match_score("simense", "Siemens", 8.0) > 0


def test_model_reference_infers_equipment_across_languages():
    assert (
        material_tools._requested_item_type(
            "پمپ",
            {
                "manufacturer": "Siemens",
                "model_name": "J30L",
                "model_type": "pump",
            },
            None,
        )
        == "equipment"
    )


def test_model_identifier_matching_rejects_unrelated_same_manufacturer_models():
    assert _model_identifier_match("J30L", "J30-L") == ("exact", 1.0)
    assert _model_identifier_match("J30L", "J30L-A")[0] == "similar"
    assert _model_identifier_match("J30L", "H420L")[0] is None
    assert _model_identifier_match("J30L", "1LA7 050")[0] is None


def test_ranked_model_candidates_keep_only_exact_or_similar_model_codes():
    db = FakeDB()
    db.set_all(
        "ManagedModel",
        [
            SimpleNamespace(
                id=1,
                manufacturer="Siemens",
                model="H420L",
                type="electromotor",
            ),
            SimpleNamespace(
                id=2,
                manufacturer="Siemens",
                model="J30-L",
                type="pump",
            ),
            SimpleNamespace(
                id=3,
                manufacturer="Siemens",
                model="J30L-A",
                type="pump",
            ),
        ],
    )

    candidates = find_model_candidates_for_material_reference(
        db,
        make_user(ALL_COMMERCE_PERMS),
        query_text="پمپ",
        manufacturer="Siemens",
        model_name="J30L",
        model_type="pump",
    )

    assert [candidate["id"] for candidate in candidates] == [2, 3]
    assert candidates[0]["match_kind"] == "exact"
    assert candidates[1]["match_kind"] == "similar"


def test_missing_material_lists_models_and_offers_create_model(monkeypatch):
    monkeypatch.setattr(
        material_tools,
        "_model_candidates",
        lambda *args, **kwargs: [
            {
                "id": 42,
                "manufacturer": "Siemens",
                "model": "H42L",
                "type": "electromotor",
                "match_score": 20,
            }
        ],
    )

    suggestion = material_tools._missing_material_suggestion(
        None,
        make_user(ALL_COMMERCE_PERMS),
        "complete Siemens H42L electromotor",
        {
            "item_name": "electromotor",
            "manufacturer": "Siemens",
            "model_name": "H42L",
            "model_type": "electromotor",
            "item_type": "equipment",
        },
    )

    assert suggestion["requires_model_selection"] is True
    assert suggestion["model_candidates"][0]["id"] == 42
    assert suggestion["create_model_suggestion"] == {
        "resource": "managed_model",
        "method": "POST",
        "endpoint": "/models/",
        "permission": "models:create",
        "payload": {
            "manufacturer": "Siemens",
            "model": "H42L",
            "type": "electromotor",
        },
    }
    assert "Choose the correct model" in suggestion["message"]


def test_selected_model_builds_linked_material_suggestion(monkeypatch):
    monkeypatch.setattr(
        material_tools,
        "_model_candidates",
        lambda *args, **kwargs: [
            {
                "id": 42,
                "manufacturer": "Siemens",
                "model": "H42L",
                "type": "electromotor",
                "match_kind": "selected",
                "match_score": 100,
            }
        ],
    )

    suggestion = material_tools._missing_material_suggestion(
        None,
        make_user(ALL_COMMERCE_PERMS),
        "electromotor",
        {
            "selected_model_id": 42,
            "item_name": "electromotor",
            "item_type": "equipment",
        },
    )

    assert suggestion["payload"] == {
        "name": "electromotor",
        "model_id": 42,
        "model_name": "Siemens H42L",
        "item_type": "equipment",
    }
    assert suggestion["matched_model"]["id"] == 42
    assert "create a material item" in suggestion["message"]


def test_multiple_similar_models_are_returned_without_guessing(monkeypatch):
    monkeypatch.setattr(
        material_tools,
        "_model_candidates",
        lambda *args, **kwargs: [
            {
                "id": 42,
                "manufacturer": "Siemens",
                "model": "H42L",
                "type": "motor",
                "match_score": 12,
            },
            {
                "id": 43,
                "manufacturer": "Siemens",
                "model": "H42L-A",
                "type": "motor",
                "match_score": 11,
            },
        ],
    )

    suggestion = material_tools._missing_material_suggestion(
        None,
        make_user(ALL_COMMERCE_PERMS),
        "Siemens H42L motor",
        {"manufacturer": "Siemens", "model_name": "H42L"},
    )

    assert suggestion["requires_model_selection"] is True
    assert len(suggestion["model_candidates"]) == 2
    assert suggestion["create_model_suggestion"] is not None
    assert "Choose the correct model" in suggestion["message"]


def test_selected_model_search_uses_exact_model_and_equipment_filters(monkeypatch):
    captured = {}

    def fake_list_items(*args, **kwargs):
        captured.update(kwargs)
        return ["matched-equipment"]

    monkeypatch.setattr(material_tools, "list_items", fake_list_items)

    result = material_tools._search_items_for_resolution(
        db=None,
        current_user=make_user(ALL_COMMERCE_PERMS),
        query_text="pump",
        context={
            "selected_model_id": 42,
            "item_type": "equipment",
        },
    )

    assert result == ["matched-equipment"]
    assert captured["model_id"] == 42
    assert captured["item_type"] == "equipment"
    assert captured["is_active"] is True


def test_selected_model_provider_resolves_a_single_orm_item_without_name_overlap():
    provider = material_tools._MaterialItemSearchProvider(
        lambda *args, **kwargs: [
            SimpleNamespace(
                id=77,
                item_code="PUMP-77",
                name="Pump",
                item_type="equipment",
                model_id=42,
            )
        ],
        material_tools._item_to_candidate,
    )

    candidates = provider.search(
        db=None,
        user=make_user(ALL_COMMERCE_PERMS),
        query="پمپ",
        context={"selected_model_id": 42},
    )

    assert candidates[0].id == 77
    assert candidates[0].match_text == "پمپ"


def test_resolved_requisition_item_removes_model_lookup_only_fields():
    saved = get_resource("material_item")
    register_resource(
        ResourceSpec(
            key="material_item",
            read_permission="material_management:search",
            provider=FakeProvider(
                [
                    Candidate(
                        id=77,
                        match_text="electromotor Siemens H42L",
                        label="EM-77 - electromotor - Siemens - H42L - equipment",
                    )
                ]
            ),
        )
    )
    try:
        draft = requisition_tools.RequisitionAssistantToolSet().build_draft(
            intent="add_material_requisition",
            db=None,
            user=make_user(ALL_COMMERCE_PERMS),
            slots={
                "reason": "replace failed motor",
                "items": [
                    {
                        "item_query": "electromotor",
                        "manufacturer": "Siemens",
                        "model_id": 42,
                        "model_name": "H42L",
                        "model_type": "electromotor",
                        "item_type": "equipment",
                        "quantity": "1",
                    }
                ],
            },
            attachments=[],
        )
    finally:
        if saved is not None:
            register_resource(saved)

    assert draft.valid is True
    assert draft.payload["items"] == [{"quantity": "1", "item_id": 77}]


def test_selected_model_id_continues_the_existing_requisition_item():
    captured = {}

    class ContextProvider:
        accepts_context = True

        def search(self, *, db, user, query, ids=None, limit=10, context=None):
            captured.update(context or {})
            return [
                Candidate(
                    id=77,
                    match_text=query,
                    label="PUMP-77 - Pump - equipment",
                )
            ]

    saved = get_resource("material_item")
    register_resource(
        ResourceSpec(
            key="material_item",
            read_permission="material_management:search",
            provider=ContextProvider(),
        )
    )
    try:
        draft = requisition_tools.RequisitionAssistantToolSet().build_draft(
            intent="add_material_requisition",
            db=None,
            user=make_user(ALL_COMMERCE_PERMS),
            slots={
                "reason": "buy requested pump",
                "model_id": 42,
                "items": [
                    {
                        "item_query": "pump",
                        "manufacturer": "Siemens",
                        "model_name": "J30L",
                        "model_type": "pump",
                        "item_type": "equipment",
                        "quantity": "1",
                    }
                ],
            },
            attachments=[],
        )
    finally:
        if saved is not None:
            register_resource(saved)

    assert captured["model_id"] == 42
    assert draft.valid is True
    assert draft.payload["items"] == [{"quantity": "1", "item_id": 77}]
