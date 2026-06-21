from decimal import Decimal

import pytest
from pydantic import ValidationError

from warehouse_management.schemas import (
    StockMovementCreate,
    StockThresholdUpdate,
    WarehouseCreate,
)


def test_warehouse_code_is_normalized():
    payload = WarehouseCreate(
        code=" main-01 ",
        name="Main Warehouse",
    )

    assert payload.code == "MAIN-01"


def test_receipt_requires_destination_location():
    with pytest.raises(ValidationError):
        StockMovementCreate(
            movement_type="receipt",
            item_id=1,
            quantity=Decimal("1"),
            unit_cost=Decimal("10"),
            currency_id=1,
            unit_cost_base=Decimal("10"),
            base_currency_id=1,
            exchange_rate_used=Decimal("1"),
        )


def test_transfer_requires_distinct_locations():
    with pytest.raises(ValidationError):
        StockMovementCreate(
            movement_type="transfer_out",
            item_id=1,
            from_location_id=10,
            to_location_id=10,
            quantity=Decimal("1"),
            unit_cost=Decimal("10"),
            currency_id=1,
            unit_cost_base=Decimal("10"),
            base_currency_id=1,
            exchange_rate_used=Decimal("1"),
        )


def test_stock_threshold_rejects_invalid_range():
    with pytest.raises(ValidationError):
        StockThresholdUpdate(
            min_level=Decimal("11"),
            max_level=Decimal("10"),
        )
