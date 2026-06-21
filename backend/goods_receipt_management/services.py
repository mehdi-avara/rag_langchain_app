from __future__ import annotations

import logging
import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from Models.user import User
from core.exceptions.error_codes import (
    GOODS_RECEIPT_HAS_NO_ITEMS,
    GOODS_RECEIPT_INVALID_QUANTITY,
    GOODS_RECEIPT_ITEM_MISMATCH,
    GOODS_RECEIPT_ITEM_NOT_FOUND,
    GOODS_RECEIPT_LEGACY_ITEM_MAPPING_REQUIRED,
    GOODS_RECEIPT_NOT_EDITABLE,
    GOODS_RECEIPT_NOT_FOUND,
    GOODS_RECEIPT_NUMBER_GENERATION_FAILED,
    GOODS_RECEIPT_PHASE_ITEM_ALREADY_EXISTS,
    GOODS_RECEIPT_POSTED_ONLY,
    GOODS_RECEIPT_REJECTION_REASON_REQUIRED,
    USER_HAS_NO_COMPANY,
)

from .models import GoodsReceiptItem, GoodsReceiptNote, GoodsReceiptStatus


logger = logging.getLogger(__name__)


def raise_error(status_code: int, code: str, message: str):
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def tenant_id(current_user: User) -> int:
    if current_user.company_id is None:
        raise_error(
            status.HTTP_403_FORBIDDEN,
            USER_HAS_NO_COMPANY,
            "Current user does not belong to a company",
        )

    return current_user.company_id


def grn_query(db: Session):
    return db.query(GoodsReceiptNote).options(
        selectinload(GoodsReceiptNote.items)
    )


def next_grn_number(db: Session, company_id: int) -> str:
    year = datetime.utcnow().year
    highest = 0

    rows = (
        db.query(GoodsReceiptNote.grn_number)
        .filter(
            GoodsReceiptNote.company_id == company_id,
            GoodsReceiptNote.grn_number.like(f"GRN-{year}-%"),
        )
        .all()
    )

    for (grn_number,) in rows:
        match = re.fullmatch(rf"GRN-{year}-(\d+)", grn_number or "")
        if match:
            highest = max(highest, int(match.group(1)))

    return f"GRN-{year}-{highest + 1:04d}"


def get_goods_receipt_or_404(
    db: Session,
    current_user: User,
    goods_receipt_id: int,
) -> GoodsReceiptNote:
    goods_receipt = (
        grn_query(db)
        .filter(
            GoodsReceiptNote.id == goods_receipt_id,
            GoodsReceiptNote.company_id == tenant_id(current_user),
        )
        .first()
    )

    if goods_receipt is None:
        raise_error(
            status.HTTP_404_NOT_FOUND,
            GOODS_RECEIPT_NOT_FOUND,
            "Goods receipt note not found",
        )

    return goods_receipt


def get_goods_receipt_for_post_or_404(
    db: Session,
    current_user: User,
    goods_receipt_id: int,
) -> GoodsReceiptNote:
    goods_receipt = (
        grn_query(db)
        .filter(
            GoodsReceiptNote.id == goods_receipt_id,
            GoodsReceiptNote.company_id == tenant_id(current_user),
        )
        .with_for_update()
        .first()
    )

    if goods_receipt is None:
        raise_error(
            status.HTTP_404_NOT_FOUND,
            GOODS_RECEIPT_NOT_FOUND,
            "Goods receipt note not found",
        )

    return goods_receipt


def get_goods_receipt_item_or_404(
    db: Session,
    goods_receipt: GoodsReceiptNote,
    goods_receipt_item_id: int,
) -> GoodsReceiptItem:
    goods_receipt_item = (
        db.query(GoodsReceiptItem)
        .filter(
            GoodsReceiptItem.id == goods_receipt_item_id,
            GoodsReceiptItem.goods_receipt_note_id == goods_receipt.id,
        )
        .first()
    )

    if goods_receipt_item is None:
        raise_error(
            status.HTTP_404_NOT_FOUND,
            GOODS_RECEIPT_ITEM_NOT_FOUND,
            "Goods receipt item not found",
        )

    return goods_receipt_item


def assert_draft(goods_receipt: GoodsReceiptNote) -> None:
    if goods_receipt.status != GoodsReceiptStatus.DRAFT.value:
        raise_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            GOODS_RECEIPT_NOT_EDITABLE,
            "Only draft goods receipt notes can be modified",
        )


def validate_quantities(values: dict[str, Any]) -> None:
    received_quantity = Decimal(str(values["received_quantity"]))
    accepted_quantity = Decimal(str(values["accepted_quantity"]))
    rejected_quantity = Decimal(str(values["rejected_quantity"]))
    rejection_reason = (values.get("rejection_reason") or "").strip()

    if received_quantity <= 0:
        raise_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            GOODS_RECEIPT_INVALID_QUANTITY,
            "received_quantity must be greater than zero",
        )

    if accepted_quantity < 0 or rejected_quantity < 0:
        raise_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            GOODS_RECEIPT_INVALID_QUANTITY,
            "accepted_quantity and rejected_quantity cannot be negative",
        )

    if accepted_quantity + rejected_quantity != received_quantity:
        raise_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            GOODS_RECEIPT_INVALID_QUANTITY,
            "accepted_quantity plus rejected_quantity must equal received_quantity",
        )

    if rejected_quantity > 0 and not rejection_reason:
        raise_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            GOODS_RECEIPT_REJECTION_REASON_REQUIRED,
            "rejection_reason is required when rejected_quantity is greater than zero",
        )


def phase_reference_for_grn(
    db: Session,
    current_user: User,
    purchase_phase_id: int,
) -> dict[str, Any]:
    from purchase_management.services import get_phase_reference_for_goods_receipt

    return get_phase_reference_for_goods_receipt(
        db=db,
        current_user=current_user,
        purchase_phase_id=purchase_phase_id,
    )


def phase_item_reference_for_grn(
    db: Session,
    current_user: User,
    purchase_order_id: int,
    purchase_phase_id: int,
    purchase_phase_item_id: int,
) -> dict[str, Any]:
    from purchase_management.services import (
        get_phase_item_reference_for_goods_receipt,
    )

    return get_phase_item_reference_for_goods_receipt(
        db=db,
        current_user=current_user,
        purchase_order_id=purchase_order_id,
        purchase_phase_id=purchase_phase_id,
        purchase_phase_item_id=purchase_phase_item_id,
    )


def resolve_material_reference(
    db: Session,
    current_user: User,
    item_id: int,
) -> dict[str, Any]:
    from material_management.services import get_item_reference

    return get_item_reference(
        db=db,
        current_user=current_user,
        item_id=item_id,
    )


def build_goods_receipt_item(
    db: Session,
    current_user: User,
    goods_receipt_note_id: int,
    purchase_order_id: int,
    purchase_phase_id: int,
    data: dict[str, Any],
) -> GoodsReceiptItem:
    validate_quantities(data)

    source = phase_item_reference_for_grn(
        db=db,
        current_user=current_user,
        purchase_order_id=purchase_order_id,
        purchase_phase_id=purchase_phase_id,
        purchase_phase_item_id=data["purchase_phase_item_id"],
    )

    accepted_quantity = Decimal(str(data["accepted_quantity"]))
    supplied_item_id = data.get("item_id")
    resolved_item_id = source["item_id"]
    item_code = source["item_code"]
    item_name = source["item_name"]
    unit_code = source["unit_code"]

    if source["item_id"] is None:
        if supplied_item_id is None and accepted_quantity > 0:
            raise_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                GOODS_RECEIPT_LEGACY_ITEM_MAPPING_REQUIRED,
                "A legacy free-text purchase line needs item_id when accepting stock",
            )

        if supplied_item_id is not None:
            material = resolve_material_reference(
                db=db,
                current_user=current_user,
                item_id=supplied_item_id,
            )
            resolved_item_id = material["id"]
            item_code = material["item_code"]
            item_name = material["name"]
            unit_code = material["unit_code"]

    elif supplied_item_id is not None and supplied_item_id != source["item_id"]:
        raise_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            GOODS_RECEIPT_ITEM_MISMATCH,
            "item_id must match the referenced purchase phase item",
        )

    return GoodsReceiptItem(
        goods_receipt_note_id=goods_receipt_note_id,
        purchase_phase_item_id=source["id"],
        item_id=resolved_item_id,
        item_code=item_code,
        item_name=item_name,
        unit_code=unit_code,
        received_quantity=data["received_quantity"],
        accepted_quantity=data["accepted_quantity"],
        rejected_quantity=data["rejected_quantity"],
        rejection_reason=data.get("rejection_reason"),
        storage_location_id=data.get("storage_location_id"),
        unit_cost=source["unit_price"],
        currency_id=source["currency_id"],
        unit_cost_base=source["unit_price_base"],
        base_currency_id=source["base_currency_id"],
        exchange_rate_used=source["exchange_rate_used"],
        notes=data.get("notes"),
    )


def create_goods_receipt(
    db: Session,
    current_user: User,
    data: dict[str, Any],
) -> GoodsReceiptNote:
    company_id = tenant_id(current_user)
    phase_reference = phase_reference_for_grn(
        db=db,
        current_user=current_user,
        purchase_phase_id=data["purchase_phase_id"],
    )

    for _ in range(5):
        try:
            goods_receipt = GoodsReceiptNote(
                company_id=company_id,
                grn_number=next_grn_number(db, company_id),
                purchase_order_id=phase_reference["purchase_order_id"],
                purchase_phase_id=phase_reference["purchase_phase_id"],
                received_by_user_id=current_user.id,
                receipt_date=data["receipt_date"],
                delivery_note_number=data.get("delivery_note_number"),
                warehouse_id=data.get("warehouse_id"),
                status=GoodsReceiptStatus.DRAFT.value,
                notes=data.get("notes"),
            )
            db.add(goods_receipt)
            db.flush()

            for item_data in data.get("items", []):
                db.add(
                    build_goods_receipt_item(
                        db=db,
                        current_user=current_user,
                        goods_receipt_note_id=goods_receipt.id,
                        purchase_order_id=goods_receipt.purchase_order_id,
                        purchase_phase_id=goods_receipt.purchase_phase_id,
                        data=item_data,
                    )
                )

            db.commit()

            return get_goods_receipt_or_404(
                db=db,
                current_user=current_user,
                goods_receipt_id=goods_receipt.id,
            )

        except IntegrityError as exc:
            db.rollback()
            text = str(exc.orig)

            if "uq_grn_company_number" in text:
                continue

            if "uq_grn_items_phase_item" in text:
                raise_error(
                    status.HTTP_409_CONFLICT,
                    GOODS_RECEIPT_PHASE_ITEM_ALREADY_EXISTS,
                    "A purchase phase item can appear only once in a goods receipt",
                )

            raise

        except Exception:
            db.rollback()
            raise

    raise_error(
        status.HTTP_409_CONFLICT,
        GOODS_RECEIPT_NUMBER_GENERATION_FAILED,
        "Could not generate a unique goods receipt number",
    )


def list_goods_receipts(
    db: Session,
    current_user: User,
    goods_receipt_status: Optional[str] = None,
    purchase_order_id: Optional[int] = None,
    purchase_phase_id: Optional[int] = None,
    receipt_date_from=None,
    receipt_date_to=None,
    page: int = 1,
    size: int = 20,
) -> list[GoodsReceiptNote]:
    query = grn_query(db).filter(
        GoodsReceiptNote.company_id == tenant_id(current_user)
    )

    if goods_receipt_status:
        query = query.filter(GoodsReceiptNote.status == goods_receipt_status)

    if purchase_order_id:
        query = query.filter(
            GoodsReceiptNote.purchase_order_id == purchase_order_id
        )

    if purchase_phase_id:
        query = query.filter(
            GoodsReceiptNote.purchase_phase_id == purchase_phase_id
        )

    if receipt_date_from:
        query = query.filter(
            GoodsReceiptNote.receipt_date >= receipt_date_from
        )

    if receipt_date_to:
        query = query.filter(
            GoodsReceiptNote.receipt_date <= receipt_date_to
        )

    return (
        query.order_by(
            GoodsReceiptNote.receipt_date.desc(),
            GoodsReceiptNote.created_at.desc(),
        )
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )


def search_goods_receipts(
    db: Session,
    current_user: User,
    query_text: str,
    page: int = 1,
    size: int = 20,
) -> list[GoodsReceiptNote]:
    pattern = f"%{query_text.strip()}%"

    query = (
        grn_query(db)
        .outerjoin(
            GoodsReceiptItem,
            GoodsReceiptItem.goods_receipt_note_id == GoodsReceiptNote.id,
        )
        .filter(
            GoodsReceiptNote.company_id == tenant_id(current_user),
            or_(
                GoodsReceiptNote.grn_number.ilike(pattern),
                GoodsReceiptNote.delivery_note_number.ilike(pattern),
                GoodsReceiptNote.notes.ilike(pattern),
                GoodsReceiptItem.item_name.ilike(pattern),
                GoodsReceiptItem.item_code.ilike(pattern),
            ),
        )
        .distinct()
    )

    return (
        query.order_by(
            GoodsReceiptNote.receipt_date.desc(),
            GoodsReceiptNote.created_at.desc(),
        )
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )


def update_goods_receipt(
    db: Session,
    current_user: User,
    goods_receipt_id: int,
    data: dict[str, Any],
) -> GoodsReceiptNote:
    goods_receipt = get_goods_receipt_or_404(
        db=db,
        current_user=current_user,
        goods_receipt_id=goods_receipt_id,
    )
    assert_draft(goods_receipt)

    for field in (
        "receipt_date",
        "delivery_note_number",
        "warehouse_id",
        "notes",
    ):
        if field in data:
            setattr(goods_receipt, field, data[field])

    db.commit()

    return get_goods_receipt_or_404(
        db=db,
        current_user=current_user,
        goods_receipt_id=goods_receipt.id,
    )


def delete_goods_receipt(
    db: Session,
    current_user: User,
    goods_receipt_id: int,
) -> None:
    goods_receipt = get_goods_receipt_or_404(
        db=db,
        current_user=current_user,
        goods_receipt_id=goods_receipt_id,
    )
    assert_draft(goods_receipt)

    db.delete(goods_receipt)
    db.commit()


def add_goods_receipt_item(
    db: Session,
    current_user: User,
    goods_receipt_id: int,
    data: dict[str, Any],
) -> GoodsReceiptItem:
    goods_receipt = get_goods_receipt_or_404(
        db=db,
        current_user=current_user,
        goods_receipt_id=goods_receipt_id,
    )
    assert_draft(goods_receipt)

    exists = (
        db.query(GoodsReceiptItem.id)
        .filter(
            GoodsReceiptItem.goods_receipt_note_id == goods_receipt.id,
            GoodsReceiptItem.purchase_phase_item_id
            == data["purchase_phase_item_id"],
        )
        .first()
    )

    if exists is not None:
        raise_error(
            status.HTTP_409_CONFLICT,
            GOODS_RECEIPT_PHASE_ITEM_ALREADY_EXISTS,
            "A purchase phase item can appear only once in a goods receipt",
        )

    goods_receipt_item = build_goods_receipt_item(
        db=db,
        current_user=current_user,
        goods_receipt_note_id=goods_receipt.id,
        purchase_order_id=goods_receipt.purchase_order_id,
        purchase_phase_id=goods_receipt.purchase_phase_id,
        data=data,
    )

    db.add(goods_receipt_item)
    db.commit()
    db.refresh(goods_receipt_item)

    return goods_receipt_item


def update_goods_receipt_item(
    db: Session,
    current_user: User,
    goods_receipt_id: int,
    goods_receipt_item_id: int,
    data: dict[str, Any],
) -> GoodsReceiptItem:
    goods_receipt = get_goods_receipt_or_404(
        db=db,
        current_user=current_user,
        goods_receipt_id=goods_receipt_id,
    )
    assert_draft(goods_receipt)

    goods_receipt_item = get_goods_receipt_item_or_404(
        db=db,
        goods_receipt=goods_receipt,
        goods_receipt_item_id=goods_receipt_item_id,
    )

    merged_values = {
        "received_quantity": data.get(
            "received_quantity",
            goods_receipt_item.received_quantity,
        ),
        "accepted_quantity": data.get(
            "accepted_quantity",
            goods_receipt_item.accepted_quantity,
        ),
        "rejected_quantity": data.get(
            "rejected_quantity",
            goods_receipt_item.rejected_quantity,
        ),
        "rejection_reason": data.get(
            "rejection_reason",
            goods_receipt_item.rejection_reason,
        ),
    }
    validate_quantities(merged_values)

    if "item_id" in data:
        source = phase_item_reference_for_grn(
            db=db,
            current_user=current_user,
            purchase_order_id=goods_receipt.purchase_order_id,
            purchase_phase_id=goods_receipt.purchase_phase_id,
            purchase_phase_item_id=goods_receipt_item.purchase_phase_item_id,
        )

        if source["item_id"] is not None:
            if data["item_id"] != source["item_id"]:
                raise_error(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    GOODS_RECEIPT_ITEM_MISMATCH,
                    "item_id must match the referenced purchase phase item",
                )
        else:
            if data["item_id"] is None:
                raise_error(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    GOODS_RECEIPT_LEGACY_ITEM_MAPPING_REQUIRED,
                    "item_id cannot be cleared for a legacy purchase phase item",
                )

            material = resolve_material_reference(
                db=db,
                current_user=current_user,
                item_id=data["item_id"],
            )
            goods_receipt_item.item_id = material["id"]
            goods_receipt_item.item_code = material["item_code"]
            goods_receipt_item.item_name = material["name"]
            goods_receipt_item.unit_code = material["unit_code"]

    if (
        goods_receipt_item.item_id is None
        and Decimal(str(merged_values["accepted_quantity"])) > 0
    ):
        raise_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            GOODS_RECEIPT_LEGACY_ITEM_MAPPING_REQUIRED,
            "A legacy free-text purchase line needs item_id when accepting stock",
        )

    for field, value in merged_values.items():
        setattr(goods_receipt_item, field, value)

    if "storage_location_id" in data:
        goods_receipt_item.storage_location_id = data["storage_location_id"]

    if "notes" in data:
        goods_receipt_item.notes = data["notes"]

    db.commit()
    db.refresh(goods_receipt_item)

    return goods_receipt_item


def delete_goods_receipt_item(
    db: Session,
    current_user: User,
    goods_receipt_id: int,
    goods_receipt_item_id: int,
) -> None:
    goods_receipt = get_goods_receipt_or_404(
        db=db,
        current_user=current_user,
        goods_receipt_id=goods_receipt_id,
    )
    assert_draft(goods_receipt)

    goods_receipt_item = get_goods_receipt_item_or_404(
        db=db,
        goods_receipt=goods_receipt,
        goods_receipt_item_id=goods_receipt_item_id,
    )

    db.delete(goods_receipt_item)
    db.commit()


def dispatch_warehouse_grn_event(goods_receipt_id: int) -> None:
    try:
        from warehouse_management.tasks import on_grn_posted
    except ModuleNotFoundError as exc:
        if exc.name not in {
            "warehouse_management",
            "warehouse_management.tasks",
        }:
            raise

        logger.warning(
            "Warehouse module is unavailable; stock movement is deferred for GRN %s",
            goods_receipt_id,
        )
        return
    except ImportError:
        logger.warning(
            "Warehouse GRN task is unavailable; stock movement is deferred for GRN %s",
            goods_receipt_id,
            exc_info=True,
        )
        return

    try:
        on_grn_posted.delay(goods_receipt_id)
    except Exception:
        logger.warning(
            "Could not dispatch warehouse receipt event for GRN %s",
            goods_receipt_id,
            exc_info=True,
        )


def post_goods_receipt(
    db: Session,
    current_user: User,
    goods_receipt_id: int,
) -> GoodsReceiptNote:
    goods_receipt = get_goods_receipt_for_post_or_404(
        db=db,
        current_user=current_user,
        goods_receipt_id=goods_receipt_id,
    )
    assert_draft(goods_receipt)

    if not goods_receipt.items:
        raise_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            GOODS_RECEIPT_HAS_NO_ITEMS,
            "A goods receipt note must contain at least one item before posting",
        )

    for goods_receipt_item in goods_receipt.items:
        validate_quantities(
            {
                "received_quantity": goods_receipt_item.received_quantity,
                "accepted_quantity": goods_receipt_item.accepted_quantity,
                "rejected_quantity": goods_receipt_item.rejected_quantity,
                "rejection_reason": goods_receipt_item.rejection_reason,
            }
        )

        if (
            Decimal(str(goods_receipt_item.accepted_quantity)) > 0
            and goods_receipt_item.item_id is None
        ):
            raise_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                GOODS_RECEIPT_LEGACY_ITEM_MAPPING_REQUIRED,
                "Accepted receipt items require a material item reference",
            )

    from purchase_management.services import apply_goods_receipt

    apply_goods_receipt(
        db=db,
        current_user=current_user,
        purchase_order_id=goods_receipt.purchase_order_id,
        purchase_phase_id=goods_receipt.purchase_phase_id,
        receipt_date=goods_receipt.receipt_date,
        receipt_items=[
            {
                "purchase_phase_item_id": item.purchase_phase_item_id,
                "accepted_quantity": item.accepted_quantity,
            }
            for item in goods_receipt.items
        ],
    )

    goods_receipt.status = GoodsReceiptStatus.POSTED.value
    db.commit()

    dispatch_warehouse_grn_event(goods_receipt.id)

    return get_goods_receipt_or_404(
        db=db,
        current_user=current_user,
        goods_receipt_id=goods_receipt.id,
    )


def get_posted_goods_receipt_for_warehouse(
    db: Session,
    goods_receipt_id: int,
) -> dict[str, Any]:
    goods_receipt = (
        grn_query(db)
        .filter(
            GoodsReceiptNote.id == goods_receipt_id,
            GoodsReceiptNote.status == GoodsReceiptStatus.POSTED.value,
        )
        .first()
    )

    if goods_receipt is None:
        raise_error(
            status.HTTP_404_NOT_FOUND,
            GOODS_RECEIPT_POSTED_ONLY,
            "Posted goods receipt note not found",
        )

    return {
        "id": goods_receipt.id,
        "company_id": goods_receipt.company_id,
        "grn_number": goods_receipt.grn_number,
        "purchase_order_id": goods_receipt.purchase_order_id,
        "purchase_phase_id": goods_receipt.purchase_phase_id,
        "receipt_date": goods_receipt.receipt_date,
        "warehouse_id": goods_receipt.warehouse_id,
        "items": [
            {
                "id": item.id,
                "purchase_phase_item_id": item.purchase_phase_item_id,
                "item_id": item.item_id,
                "item_code": item.item_code,
                "item_name": item.item_name,
                "unit_code": item.unit_code,
                "accepted_quantity": item.accepted_quantity,
                "storage_location_id": item.storage_location_id,
                "unit_cost": item.unit_cost,
                "currency_id": item.currency_id,
                "unit_cost_base": item.unit_cost_base,
                "base_currency_id": item.base_currency_id,
                "exchange_rate_used": item.exchange_rate_used,
            }
            for item in goods_receipt.items
            if Decimal(str(item.accepted_quantity)) > 0
        ],
    }
