from decimal import Decimal

from business_management.services import (
    _allocation_receipt_state,
)


def test_allocation_receipt_state_pending():
    assert (
        _allocation_receipt_state(
            Decimal("5"),
            Decimal("0"),
        )
        == "pending"
    )


def test_allocation_receipt_state_partial():
    assert (
        _allocation_receipt_state(
            Decimal("5"),
            Decimal("2"),
        )
        == "partially_received"
    )


def test_allocation_receipt_state_received():
    assert (
        _allocation_receipt_state(
            Decimal("5"),
            Decimal("5"),
        )
        == "received"
    )


def test_allocation_receipt_state_over_received():
    assert (
        _allocation_receipt_state(
            Decimal("5"),
            Decimal("6"),
        )
        == "received"
    )
