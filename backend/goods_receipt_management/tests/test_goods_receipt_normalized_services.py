from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import goods_receipt_management.services as services
from goods_receipt_management.models import (
    GoodsReceiptStatus,
)


class FakeSession:
    def __init__(self):
        self.flushes = 0
        self.commits = 0
        self.rollbacks = 0

    def flush(self):
        self.flushes += 1

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def allocation_source():
    return {
        "id": 41,
        "purchase_order_line_id": 12,
        "item_id": 101,
        "item_code": "BRG-001",
        "item_name": "Bearing",
        "unit_id": 7,
        "unit_code": "PCS",
        "quantity": Decimal("4"),
        "received_quantity": Decimal("0"),
        "unit_price": Decimal("12.5"),
        "currency_id": 1,
        "unit_price_base": Decimal("12.5"),
        "base_currency_id": 1,
        "exchange_rate_used": Decimal("1"),
    }


def test_build_item_uses_allocation(monkeypatch):
    monkeypatch.setattr(
        services,
        "phase_allocation_reference_for_grn",
        lambda **kwargs: allocation_source(),
    )

    item = services.build_goods_receipt_item(
        db=None,
        current_user=SimpleNamespace(
            id=2,
            company_id=1,
        ),
        goods_receipt_note_id=9,
        purchase_order_id=3,
        purchase_phase_id=5,
        data={
            "purchase_phase_allocation_id": 41,
            "item_id": 101,
            "received_quantity": Decimal("4"),
            "accepted_quantity": Decimal("3"),
            "rejected_quantity": Decimal("1"),
            "rejection_reason": "Damaged",
            "storage_location_id": None,
            "notes": None,
        },
    )

    assert item.purchase_phase_allocation_id == 41
    assert item.item_id == 101
    assert item.unit_cost == Decimal("12.5")


def test_build_item_rejects_material_mismatch(
    monkeypatch,
):
    monkeypatch.setattr(
        services,
        "phase_allocation_reference_for_grn",
        lambda **kwargs: allocation_source(),
    )

    with pytest.raises(HTTPException) as exc_info:
        services.build_goods_receipt_item(
            db=None,
            current_user=SimpleNamespace(
                id=2,
                company_id=1,
            ),
            goods_receipt_note_id=9,
            purchase_order_id=3,
            purchase_phase_id=5,
            data={
                "purchase_phase_allocation_id": 41,
                "item_id": 999,
                "received_quantity": Decimal("1"),
                "accepted_quantity": Decimal("1"),
                "rejected_quantity": Decimal("0"),
                "rejection_reason": None,
                "storage_location_id": None,
                "notes": None,
            },
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == (
        "GOODS_RECEIPT_ITEM_MISMATCH"
    )


def test_post_flushes_posted_state_before_apply(
    monkeypatch,
):
    db = FakeSession()
    item = SimpleNamespace(
        purchase_phase_allocation_id=41,
        item_id=101,
        received_quantity=Decimal("2"),
        accepted_quantity=Decimal("2"),
        rejected_quantity=Decimal("0"),
        rejection_reason=None,
        storage_location_id=None,
    )
    receipt = SimpleNamespace(
        id=8,
        status=GoodsReceiptStatus.DRAFT.value,
        items=[item],
        purchase_order_id=3,
        purchase_phase_id=5,
        receipt_date=date(2026, 7, 18),
        warehouse_id=None,
    )
    calls = []

    monkeypatch.setattr(
        services,
        "get_goods_receipt_for_post_or_404",
        lambda **kwargs: receipt,
    )
    monkeypatch.setattr(
        services,
        "validate_warehouse_references_for_post",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "purchase_management.services.apply_goods_receipt",
        lambda **kwargs: calls.append(
            {
                "status": receipt.status,
                "items": kwargs["receipt_items"],
            }
        ),
    )
    monkeypatch.setattr(
        services,
        "dispatch_warehouse_grn_event",
        lambda goods_receipt_id: None,
    )
    monkeypatch.setattr(
        services,
        "get_goods_receipt_or_404",
        lambda **kwargs: receipt,
    )

    result = services.post_goods_receipt(
        db=db,
        current_user=SimpleNamespace(
            id=2,
            company_id=1,
        ),
        goods_receipt_id=8,
    )

    assert result is receipt
    assert receipt.status == GoodsReceiptStatus.POSTED.value
    assert calls == [
        {
            "status": GoodsReceiptStatus.POSTED.value,
            "items": [
                {
                    "purchase_phase_allocation_id": 41,
                    "accepted_quantity": Decimal("2"),
                }
            ],
        }
    ]
    assert db.flushes == 1
    assert db.commits == 1
    assert db.rollbacks == 0


def test_post_rolls_back_when_apply_fails(
    monkeypatch,
):
    db = FakeSession()
    item = SimpleNamespace(
        purchase_phase_allocation_id=41,
        item_id=101,
        received_quantity=Decimal("2"),
        accepted_quantity=Decimal("2"),
        rejected_quantity=Decimal("0"),
        rejection_reason=None,
        storage_location_id=None,
    )
    receipt = SimpleNamespace(
        id=8,
        status=GoodsReceiptStatus.DRAFT.value,
        items=[item],
        purchase_order_id=3,
        purchase_phase_id=5,
        receipt_date=date(2026, 7, 18),
        warehouse_id=None,
    )

    monkeypatch.setattr(
        services,
        "get_goods_receipt_for_post_or_404",
        lambda **kwargs: receipt,
    )
    monkeypatch.setattr(
        services,
        "validate_warehouse_references_for_post",
        lambda **kwargs: None,
    )

    def fail_apply(**kwargs):
        raise RuntimeError("over receipt")

    monkeypatch.setattr(
        "purchase_management.services.apply_goods_receipt",
        fail_apply,
    )

    with pytest.raises(
        RuntimeError,
        match="over receipt",
    ):
        services.post_goods_receipt(
            db=db,
            current_user=SimpleNamespace(
                id=2,
                company_id=1,
            ),
            goods_receipt_id=8,
        )

    assert db.flushes == 1
    assert db.commits == 0
    assert db.rollbacks == 1
