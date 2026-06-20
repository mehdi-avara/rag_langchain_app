from datetime import datetime
from types import SimpleNamespace

from material_management.services import (
    _import_bool,
    _import_specs,
    build_category_tree,
    item_searchable_text,
    item_to_out,
)


def make_category(category_id=1, parent_id=None, code="SPARE", name="Spare Parts"):
    return SimpleNamespace(
        id=category_id,
        company_id=7,
        parent_id=parent_id,
        code=code,
        name=name,
        description=None,
        created_by_user_id=3,
        created_at=datetime(2026, 6, 20, 10, 0, 0),
        updated_at=datetime(2026, 6, 20, 10, 0, 0),
    )


def make_unit():
    return SimpleNamespace(
        id=2,
        company_id=7,
        code="PCS",
        name="Piece",
        unit_type="count",
        created_by_user_id=3,
        created_at=datetime(2026, 6, 20, 10, 0, 0),
        updated_at=datetime(2026, 6, 20, 10, 0, 0),
    )


def test_category_tree_builds_parent_child_structure():
    root = make_category(category_id=1, code="ROOT", name="Root")
    child = make_category(category_id=2, parent_id=1, code="BOLT", name="Bolts")

    tree = build_category_tree([root, child])

    assert len(tree) == 1
    assert tree[0].id == 1
    assert tree[0].children[0].id == 2


def test_item_searchable_text_includes_specs_and_category():
    category = make_category()
    unit = make_unit()

    item = SimpleNamespace(
        item_code="BOLT-M12",
        name="Bolt M12",
        description="Stainless bolt",
        barcode=None,
        qr_code=None,
        item_type="spare_part",
        lead_time_days=10,
        specs={"diameter": "M12", "material": "SS304"},
        category=category,
        unit=unit,
        alternatives=[],
    )

    searchable = item_searchable_text(item)

    assert "BOLT-M12" in searchable
    assert "SS304" in searchable
    assert "Spare Parts" in searchable
    assert "PCS" in searchable


def test_item_to_out_maps_master_data_and_relations():
    category = make_category()
    unit = make_unit()

    item = SimpleNamespace(
        id=5,
        company_id=7,
        item_code="BOLT-M12",
        name="Bolt M12",
        description="Stainless bolt",
        category_id=category.id,
        unit_id=unit.id,
        model_id=None,
        specs={"diameter": "M12"},
        barcode=None,
        qr_code=None,
        item_type="spare_part",
        is_active=True,
        is_critical=True,
        lead_time_days=10,
        created_by_user_id=3,
        description_embedding=None,
        created_at=datetime(2026, 6, 20, 10, 0, 0),
        updated_at=datetime(2026, 6, 20, 10, 0, 0),
        category=category,
        unit=unit,
        alternatives=[],
        documents=[],
    )

    result = item_to_out(item)

    assert result.item_code == "BOLT-M12"
    assert result.category.code == "SPARE"
    assert result.unit.code == "PCS"
    assert result.embedding_status == "pending"


def test_import_parsers_handle_booleans_and_json_specs():
    assert _import_bool("yes", False) is True
    assert _import_bool("0", True) is False
    assert _import_specs('{"grade":"A4"}') == {"grade": "A4"}
