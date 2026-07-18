from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

import Models
from api import app
from purchase_management.models import (
    PurchasePhase,
    PurchasePhaseSplitEvent,
)
from purchase_management.permissions import (
    PERMISSIONS,
)
from purchase_management.schemas import (
    PurchasePhaseSplitRequest,
)
from purchase_management.services import (
    _purchase_split_request_hash,
)


def test_split_schema_rejects_duplicate_allocations():
    with pytest.raises(ValidationError):
        PurchasePhaseSplitRequest(
            expected_delivery_date=datetime(
                2026,
                8,
                15,
            ),
            reason="Supplier schedule",
            moves=[
                {
                    "from_phase_allocation_id": 5,
                    "quantity": Decimal("1"),
                },
                {
                    "from_phase_allocation_id": 5,
                    "quantity": Decimal("2"),
                },
            ],
        )


def test_split_request_hash_is_order_independent():
    first = {
        "title": "Later delivery",
        "expected_delivery_date": datetime(
            2026,
            8,
            15,
        ),
        "reason": "Supplier schedule",
        "moves": [
            {
                "from_phase_allocation_id": 8,
                "quantity": Decimal("2"),
            },
            {
                "from_phase_allocation_id": 4,
                "quantity": Decimal("1"),
            },
        ],
    }
    second = {
        **first,
        "moves": list(
            reversed(first["moves"])
        ),
    }

    assert (
        _purchase_split_request_hash(first)
        == _purchase_split_request_hash(second)
    )


def test_split_permission_is_registered():
    names = {
        permission[0]
        for permission in PERMISSIONS
    }

    assert (
        "purchase_management:phases:split"
        in names
    )


def test_split_models_have_database_guards():
    phase_constraint_names = {
        constraint.name
        for constraint
        in PurchasePhase.__table__.constraints
    }
    event_constraint_names = {
        constraint.name
        for constraint
        in PurchasePhaseSplitEvent
        .__table__.constraints
    }

    assert (
        "uq_purchase_phases_order_phase_number"
        in phase_constraint_names
    )
    assert (
        "uq_purchase_phase_split_events_scope_key"
        in event_constraint_names
    )
    assert (
        Models.PurchasePhaseSplitEvent
        is PurchasePhaseSplitEvent
    )


def test_split_routes_replace_public_phase_creation():
    paths = app.openapi()["paths"]

    assert (
        "/purchase/orders/{po_id}/split-candidates"
        in paths
    )
    assert (
        "/purchase/orders/{po_id}/phases/split"
        in paths
    )
    assert (
        "post"
        in paths[
            "/purchase/orders/{po_id}/phases/split"
        ]
    )

    phase_collection = paths[
        "/purchase/orders/{po_id}/phases"
    ]

    assert "get" in phase_collection
    assert "post" not in phase_collection

    assert (
        "/purchase/orders/{po_id}/phases/"
        "{phase_id}/items"
        not in paths
    )
