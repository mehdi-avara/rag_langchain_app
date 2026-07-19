from decimal import Decimal
from typing import get_args

import pytest
from pydantic import ValidationError

from purchase_management.schemas import (
    PurchaseOrderCostUpdate,
    PurchaseOrderLineMutationCreate,
    PurchaseOrderLineMutationUpdate,
)


def line_payload():
    return {
        "item_id": 1,
        "ordered_quantity": Decimal("5"),
        "unit_id": 2,
        "line_description": "Line",
        "unit_price": Decimal("10"),
        "currency_id": 3,
        "exchange_rate_used": Decimal("1"),
        "notes": None,
        "allocations": [
            {
                "phase_id": 4,
                "allocated_quantity": Decimal("5"),
            }
        ],
    }


def test_line_create_requires_balanced_allocations():
    payload = PurchaseOrderLineMutationCreate(
        **line_payload()
    )

    assert payload.allocations[0].phase_id == 4

    invalid = line_payload()
    invalid["allocations"][0][
        "allocated_quantity"
    ] = Decimal("4")

    with pytest.raises(ValidationError):
        PurchaseOrderLineMutationCreate(
            **invalid
        )


def test_line_create_rejects_duplicate_phases():
    payload = line_payload()
    payload["allocations"] = [
        {
            "phase_id": 4,
            "allocated_quantity": Decimal("2"),
        },
        {
            "phase_id": 4,
            "allocated_quantity": Decimal("3"),
        },
    ]

    with pytest.raises(ValidationError):
        PurchaseOrderLineMutationCreate(
            **payload
        )


def test_line_update_preserves_omitted_fields():
    payload = PurchaseOrderLineMutationUpdate(
        line_description=None,
        notes=None,
    )

    values = payload.model_dump(
        exclude_unset=True
    )

    assert values == {
        "line_description": None,
        "notes": None,
    }


def test_cost_update_preserves_explicit_null_description():
    payload = PurchaseOrderCostUpdate(
        description=None,
    )

    assert payload.model_dump(
        exclude_unset=True
    ) == {
        "description": None,
    }


def test_commercial_mutation_openapi_contract():
    from api import app

    paths = app.openapi()["paths"]

    line_collection = (
        "/purchase/orders/{po_id}/lines"
    )
    line_resource = (
        "/purchase/orders/{po_id}/lines/"
        "{line_id}"
    )
    cost_resource = (
        "/purchase/orders/{po_id}/costs/"
        "{cost_id}"
    )

    assert "post" in paths[line_collection]
    assert "patch" in paths[line_resource]
    assert "delete" in paths[line_resource]
    assert "patch" in paths[cost_resource]
    assert "delete" in paths[cost_resource]
