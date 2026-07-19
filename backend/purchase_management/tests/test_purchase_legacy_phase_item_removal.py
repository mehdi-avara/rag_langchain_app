from pathlib import Path

import Models
from api import app
from goods_receipt_management.models import (
    GoodsReceiptItem,
)
from purchase_management.models import (
    PurchasePhase,
)


def test_legacy_phase_item_model_is_removed():
    assert not hasattr(
        Models,
        "PurchasePhaseItem",
    )
    assert (
        "PurchasePhaseItem"
        not in Models.__all__
    )
    assert not hasattr(
        PurchasePhase,
        "items",
    )


def test_grn_uses_allocation_only():
    columns = {
        column.name
        for column
        in GoodsReceiptItem.__table__.columns
    }

    assert (
        "purchase_phase_allocation_id"
        in columns
    )
    assert (
        "purchase_phase_item_id"
        not in columns
    )


def test_legacy_phase_item_route_is_removed():
    assert not Path(
        "purchase_management/routes/items.py"
    ).exists()

    paths = app.openapi()["paths"]

    assert not any(
        "/phases/{phase_id}/items"
        in path
        for path in paths
    )


def test_openapi_has_no_legacy_phase_item_fields():
    schemas = app.openapi()[
        "components"
    ]["schemas"]

    assert (
        "PurchasePhaseItemRead"
        not in schemas
    )
    assert (
        "PurchasePhaseItemCreate"
        not in schemas
    )
    assert (
        "PurchasePhaseItemUpdate"
        not in schemas
    )

    phase_fields = set(
        schemas["PurchasePhaseRead"][
            "properties"
        ]
    )
    grn_item_fields = set(
        schemas["GoodsReceiptItemRead"][
            "properties"
        ]
    )

    assert "items" not in phase_fields
    assert (
        "purchase_phase_item_id"
        not in grn_item_fields
    )


def test_active_services_have_no_legacy_phase_item_logic():
    active_paths = [
        Path(
            "purchase_management/services.py"
        ),
        Path(
            "goods_receipt_management/services.py"
        ),
        Path(
            "business_management/services.py"
        ),
    ]

    for path in active_paths:
        source = path.read_text(
            encoding="utf-8"
        )

        assert "PurchasePhaseItem" not in source
        assert (
            "purchase_phase_item_id"
            not in source
        )
