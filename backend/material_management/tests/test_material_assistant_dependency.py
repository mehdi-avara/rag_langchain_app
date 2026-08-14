from __future__ import annotations

from assistant.module_interface import (
    Candidate,
    ResourceSpec,
    get_resource,
    register_resource,
)
from assistant.tests.fakes import ALL_COMMERCE_PERMS, FakeProvider, make_user
import material_management.assistant_tools as material_tools
from model_management.services import _field_match_score
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


def test_missing_material_suggestion_links_the_existing_model(monkeypatch):
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

    assert suggestion["payload"] == {
        "name": "electromotor",
        "model_id": 42,
        "model_name": "Siemens H42L",
        "item_type": "equipment",
    }
    assert suggestion["matched_model"]["id"] == 42
    assert "create a material item" in suggestion["message"]


def test_missing_material_does_not_guess_between_models(monkeypatch):
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

    assert suggestion["suppress_create"] is True
    assert len(suggestion["model_matches"]) == 2
    assert "multiple possible equipment models" in suggestion["message"]


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
