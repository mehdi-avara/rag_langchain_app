from __future__ import annotations

from decimal import Decimal

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from .models import (
    GoodsReceiptItem,
    GoodsReceiptNote,
    GoodsReceiptStatus,
)


ZERO = Decimal("0")


def get_allocation_receipt_usage(
    db: Session,
    allocation_ids: list[int],
) -> dict[int, dict]:
    normalized_ids = sorted(
        {
            int(allocation_id)
            for allocation_id in allocation_ids
        }
    )

    if not normalized_ids:
        return {}

    rows = (
        db.query(
            GoodsReceiptItem
            .purchase_phase_allocation_id,
            func.coalesce(
                func.sum(
                    case(
                        (
                            GoodsReceiptNote.status
                            == GoodsReceiptStatus
                            .POSTED.value,
                            GoodsReceiptItem
                            .accepted_quantity,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label(
                "posted_accepted_quantity"
            ),
            func.count(
                GoodsReceiptItem.id
            ).label("receipt_line_count"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            GoodsReceiptNote.status
                            != GoodsReceiptStatus
                            .POSTED.value,
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label(
                "non_posted_line_count"
            ),
        )
        .join(
            GoodsReceiptNote,
            GoodsReceiptNote.id
            == GoodsReceiptItem
            .goods_receipt_note_id,
        )
        .filter(
            GoodsReceiptItem
            .purchase_phase_allocation_id
            .in_(normalized_ids)
        )
        .group_by(
            GoodsReceiptItem
            .purchase_phase_allocation_id
        )
        .all()
    )

    usage = {
        allocation_id: {
            "posted_accepted_quantity": ZERO,
            "receipt_line_count": 0,
            "non_posted_line_count": 0,
        }
        for allocation_id in normalized_ids
    }

    for row in rows:
        allocation_id = int(row[0])

        usage[allocation_id] = {
            "posted_accepted_quantity": Decimal(
                str(row[1] or 0)
            ),
            "receipt_line_count": int(
                row[2] or 0
            ),
            "non_posted_line_count": int(
                row[3] or 0
            ),
        }

    return usage
