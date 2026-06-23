from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.orm import Session

from Models.user import User

from ..models import GoodsReceiptItem, GoodsReceiptNote
from ..services import tenant_id


def search_goods_receipts_by_item_ids(
    db: Session,
    current_user: User,
    item_ids: Sequence[int],
    goods_receipt_ids: Sequence[int] | None,
    limit: int,
) -> list[GoodsReceiptNote]:
    if not item_ids:
        return []

    query = (
        db.query(GoodsReceiptNote)
        .join(
            GoodsReceiptItem,
            GoodsReceiptItem.goods_receipt_note_id
            == GoodsReceiptNote.id,
        )
        .filter(
            GoodsReceiptNote.company_id == tenant_id(current_user),
            GoodsReceiptItem.item_id.in_(list(item_ids)),
        )
        .distinct()
    )

    if goods_receipt_ids:
        query = query.filter(
            GoodsReceiptNote.id.in_(list(goods_receipt_ids))
        )

    return (
        query.order_by(
            GoodsReceiptNote.receipt_date.desc(),
            GoodsReceiptNote.created_at.desc(),
        )
        .limit(limit)
        .all()
    )
