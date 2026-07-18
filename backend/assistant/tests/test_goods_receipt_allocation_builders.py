from assistant.module_interface import get_resource
import goods_receipt_management.assistant_tools as grn_tools
import purchase_management.assistant_tools
from shared.commerce_assistant import (
    goods_receipt_items_from_slots,
    goods_receipt_required,
)


def test_goods_receipt_builder_uses_allocation_id():
    items = goods_receipt_items_from_slots(
        {
            "purchase_phase_allocation_id": 41,
            "received_quantity": "5",
            "accepted_quantity": "5",
            "rejected_quantity": "0",
        }
    )

    assert items == [
        {
            "purchase_phase_allocation_id": 41,
            "received_quantity": "5",
            "accepted_quantity": "5",
            "rejected_quantity": "0",
        }
    ]


def test_goods_receipt_required_requires_allocation():
    missing = goods_receipt_required(
        {
            "items": [
                {
                    "received_quantity": "1",
                    "accepted_quantity": "1",
                    "rejected_quantity": "0",
                }
            ]
        },
        {},
    )

    assert missing == [
        "purchase phase allocation"
    ]


def test_goods_receipt_toolset_resolves_allocations():
    create_spec = next(
        spec
        for spec in grn_tools.GoodsReceiptAssistantToolSet.write_specs
        if spec.intent == "add_goods_receipt"
    )

    fields = {
        reference.field
        for reference in create_spec.reference_fields
    }

    assert "purchase_phase_allocation_id" in fields
    assert "purchase_phase_item_id" not in fields
    assert (
        get_resource(
            "purchase_phase_allocation"
        )
        is not None
    )
