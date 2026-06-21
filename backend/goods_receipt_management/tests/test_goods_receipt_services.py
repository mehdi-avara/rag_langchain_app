from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from goods_receipt_management.models import GoodsReceiptStatus
from goods_receipt_management.schemas import (
    GoodsReceiptCreate,
    GoodsReceiptItemCreate,
)


def test_goods_receipt_status_values():
    assert GoodsReceiptStatus.DRAFT.value == "draft"
    assert GoodsReceiptStatus.POSTED.value == "posted"


def test_goods_receipt_item_accepts_balanced_quantities():
    item = GoodsReceiptItemCreate(
        purchase_phase_item_id=1,
        received_quantity=Decimal("10"),
        accepted_quantity=Decimal("8"),
        rejected_quantity=Decimal("2"),
        rejection_reason="Damaged packaging",
    )

    assert item.accepted_quantity == Decimal("8")
    assert item.rejected_quantity == Decimal("2")


def test_goods_receipt_item_rejects_unbalanced_quantities():
    with pytest.raises(ValidationError):
        GoodsReceiptItemCreate(
            purchase_phase_item_id=1,
            received_quantity=Decimal("10"),
            accepted_quantity=Decimal("9"),
            rejected_quantity=Decimal("0"),
        )


def test_goods_receipt_item_requires_rejection_reason():
    with pytest.raises(ValidationError):
        GoodsReceiptItemCreate(
            purchase_phase_item_id=1,
            received_quantity=Decimal("5"),
            accepted_quantity=Decimal("4"),
            rejected_quantity=Decimal("1"),
        )


def test_goods_receipt_rejects_duplicate_phase_items():
    with pytest.raises(ValidationError):
        GoodsReceiptCreate(
            purchase_phase_id=1,
            receipt_date=date(2026, 6, 21),
            items=[
                {
                    "purchase_phase_item_id": 1,
                    "received_quantity": Decimal("1"),
                    "accepted_quantity": Decimal("1"),
                    "rejected_quantity": Decimal("0"),
                },
                {
                    "purchase_phase_item_id": 1,
                    "received_quantity": Decimal("1"),
                    "accepted_quantity": Decimal("1"),
                    "rejected_quantity": Decimal("0"),
                },
            ],
        )
