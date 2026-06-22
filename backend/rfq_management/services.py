from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from Models.user import User
from core.exceptions.error_codes import (
    QUOTATION_RESPONSE_ALREADY_EXISTS,
    QUOTATION_RESPONSE_HAS_NO_ITEMS,
    QUOTATION_RESPONSE_ITEM_ALREADY_EXISTS,
    QUOTATION_RESPONSE_ITEM_NOT_FOUND,
    QUOTATION_RESPONSE_NOT_EDITABLE,
    QUOTATION_RESPONSE_NOT_FOUND,
    RFQ_HAS_NO_ITEMS,
    RFQ_HAS_NO_SUPPLIERS,
    RFQ_INVALID_QUOTE_MONEY,
    RFQ_INVALID_STATUS_TRANSITION,
    RFQ_ITEM_NOT_FOUND,
    RFQ_MR_ALREADY_LINKED,
    RFQ_MR_HAS_NO_ITEMS,
    RFQ_MR_ITEM_UNAVAILABLE,
    RFQ_MR_NOT_APPROVED,
    RFQ_NOT_EDITABLE,
    RFQ_NOT_FOUND,
    RFQ_NUMBER_GENERATION_FAILED,
    RFQ_SUPPLIER_ALREADY_EXISTS,
    RFQ_SUPPLIER_NOT_FOUND,
    RFQ_WINNER_ALREADY_SELECTED,
    RFQ_WINNING_QUOTATION_CURRENCY_MISMATCH,
    RFQ_WINNING_QUOTATION_INCOMPLETE,
    RFQ_WINNING_QUOTATION_NOT_SELECTED,
    RFQ_WINNING_QUOTATION_SUPPLIER_MISSING,
    USER_HAS_NO_COMPANY,
)

from .models import (
    QuotationResponse,
    QuotationResponseItem,
    RFQItem,
    RFQStatus,
    RFQSupplier,
    RFQSupplierResponseStatus,
    RequestForQuotation,
)


def _raise(status_code: int, code: str, message: str):
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def tenant_id(current_user: User) -> int:
    if current_user.company_id is None:
        _raise(
            status.HTTP_403_FORBIDDEN,
            USER_HAS_NO_COMPANY,
            "Current user does not belong to a company",
        )
    return current_user.company_id


def _rfq_query(db: Session):
    return db.query(RequestForQuotation).options(
        selectinload(RequestForQuotation.suppliers),
        selectinload(RequestForQuotation.items),
        selectinload(RequestForQuotation.responses).selectinload(
            QuotationResponse.items
        ),
    )


def _next_rfq_number(db: Session, company_id: int) -> str:
    year = datetime.utcnow().year
    highest = 0

    rows = (
        db.query(RequestForQuotation.rfq_number)
        .filter(
            RequestForQuotation.company_id == company_id,
            RequestForQuotation.rfq_number.like(f"RFQ-{year}-%"),
        )
        .all()
    )

    for (rfq_number,) in rows:
        match = re.fullmatch(rf"RFQ-{year}-(\d+)", rfq_number or "")
        if match:
            highest = max(highest, int(match.group(1)))

    return f"RFQ-{year}-{highest + 1:04d}"


def get_rfq_or_404(
    db: Session,
    current_user: User,
    rfq_id: int,
) -> RequestForQuotation:
    rfq = (
        _rfq_query(db)
        .filter(
            RequestForQuotation.id == rfq_id,
            RequestForQuotation.company_id == tenant_id(current_user),
        )
        .first()
    )

    if rfq is None:
        _raise(status.HTTP_404_NOT_FOUND, RFQ_NOT_FOUND, "RFQ not found")

    return rfq


def _assert_draft(rfq: RequestForQuotation) -> None:
    if rfq.status != RFQStatus.DRAFT.value:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            RFQ_NOT_EDITABLE,
            "Only draft RFQs can be modified",
        )


def _assert_sent(rfq: RequestForQuotation) -> None:
    if rfq.status != RFQStatus.SENT.value:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            QUOTATION_RESPONSE_NOT_EDITABLE,
            "Quotation responses are allowed only for sent RFQs",
        )


def _get_rfq_supplier_or_404(
    db: Session,
    rfq: RequestForQuotation,
    supplier_id: int,
) -> RFQSupplier:
    rfq_supplier = (
        db.query(RFQSupplier)
        .filter(
            RFQSupplier.rfq_id == rfq.id,
            RFQSupplier.supplier_id == supplier_id,
        )
        .first()
    )

    if rfq_supplier is None:
        _raise(
            status.HTTP_404_NOT_FOUND,
            RFQ_SUPPLIER_NOT_FOUND,
            "Supplier is not invited to this RFQ",
        )

    return rfq_supplier


def _get_rfq_item_or_404(
    db: Session,
    rfq: RequestForQuotation,
    rfq_item_id: int,
) -> RFQItem:
    rfq_item = (
        db.query(RFQItem)
        .filter(
            RFQItem.id == rfq_item_id,
            RFQItem.rfq_id == rfq.id,
        )
        .first()
    )

    if rfq_item is None:
        _raise(
            status.HTTP_404_NOT_FOUND,
            RFQ_ITEM_NOT_FOUND,
            "RFQ item not found",
        )

    return rfq_item


def _get_response_or_404(
    db: Session,
    rfq: RequestForQuotation,
    quotation_response_id: int,
) -> QuotationResponse:
    response = (
        db.query(QuotationResponse)
        .options(selectinload(QuotationResponse.items))
        .filter(
            QuotationResponse.id == quotation_response_id,
            QuotationResponse.rfq_id == rfq.id,
        )
        .first()
    )

    if response is None:
        _raise(
            status.HTTP_404_NOT_FOUND,
            QUOTATION_RESPONSE_NOT_FOUND,
            "Quotation response not found",
        )

    return response


def _validate_winning_quotation_for_purchase(
    rfq: RequestForQuotation,
    winning_response: QuotationResponse,
) -> QuotationResponseItem:
    if not winning_response.items:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            QUOTATION_RESPONSE_HAS_NO_ITEMS,
            "A quotation response without items cannot be selected",
        )

    if winning_response.supplier_id is None:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            RFQ_WINNING_QUOTATION_SUPPLIER_MISSING,
            "The winning quotation response no longer has a supplier reference",
        )

    rfq_items_by_id = {
        item.id: item
        for item in rfq.items
    }
    response_items_by_rfq_item_id = {
        item.rfq_item_id: item
        for item in winning_response.items
    }

    if (
        not rfq_items_by_id
        or set(rfq_items_by_id) != set(response_items_by_rfq_item_id)
    ):
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            RFQ_WINNING_QUOTATION_INCOMPLETE,
            "The winning quotation response must cover every RFQ item exactly once",
        )

    currency_ids = {
        item.currency_id
        for item in winning_response.items
    }
    base_currency_ids = {
        item.base_currency_id
        for item in winning_response.items
    }
    exchange_rates = {
        item.exchange_rate_used
        for item in winning_response.items
    }

    if (
        len(currency_ids) != 1
        or len(base_currency_ids) != 1
        or len(exchange_rates) != 1
    ):
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            RFQ_WINNING_QUOTATION_CURRENCY_MISMATCH,
            "All winning quotation items must use one currency, base currency, and exchange rate",
        )

    return winning_response.items[0]


def _get_response_item_or_404(
    db: Session,
    response: QuotationResponse,
    quotation_response_item_id: int,
) -> QuotationResponseItem:
    response_item = (
        db.query(QuotationResponseItem)
        .filter(
            QuotationResponseItem.id == quotation_response_item_id,
            QuotationResponseItem.quotation_response_id == response.id,
        )
        .first()
    )

    if response_item is None:
        _raise(
            status.HTTP_404_NOT_FOUND,
            QUOTATION_RESPONSE_ITEM_NOT_FOUND,
            "Quotation response item not found",
        )

    return response_item


def _resolve_supplier_reference(
    db: Session,
    current_user: User,
    supplier_id: int,
) -> dict[str, Any]:
    from supplier_management.services import get_supplier_or_404

    supplier = get_supplier_or_404(
        db=db,
        supplier_id=supplier_id,
        current_user=current_user,
    )

    return {
        "id": supplier.id,
        "code": supplier.code,
        "name": supplier.name,
    }


def _resolve_item_reference(
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


def _build_rfq_supplier(
    db: Session,
    current_user: User,
    rfq_id: int,
    supplier_id: int,
) -> RFQSupplier:
    reference = _resolve_supplier_reference(db, current_user, supplier_id)

    return RFQSupplier(
        rfq_id=rfq_id,
        supplier_id=reference["id"],
        supplier_code=reference["code"],
        supplier_name=reference["name"],
        response_status=RFQSupplierResponseStatus.PENDING.value,
    )


def _build_rfq_item(
    db: Session,
    current_user: User,
    rfq_id: int,
    data: dict[str, Any],
) -> RFQItem:
    reference = _resolve_item_reference(
        db=db,
        current_user=current_user,
        item_id=data["item_id"],
    )

    return RFQItem(
        rfq_id=rfq_id,
        item_id=reference["id"],
        item_code=reference["item_code"],
        item_name=reference["name"],
        unit_id=reference["unit_id"],
        unit_code=reference["unit_code"],
        quantity=data["quantity"],
        specifications=data.get("specifications"),
    )


def _get_approved_mr_for_rfq(
    db: Session,
    current_user: User,
    mr_id: int,
):
    from requisition_management.services import get_requisition_or_404

    requisition = get_requisition_or_404(
        db=db,
        current_user=current_user,
        requisition_id=mr_id,
    )

    if requisition.status != "approved":
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            RFQ_MR_NOT_APPROVED,
            "Only approved material requisitions can create RFQs",
        )

    if not requisition.items:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            RFQ_MR_HAS_NO_ITEMS,
            "The material requisition has no items",
        )

    existing = (
        db.query(RequestForQuotation.id)
        .filter(
            RequestForQuotation.company_id == tenant_id(current_user),
            RequestForQuotation.mr_id == requisition.id,
        )
        .first()
    )

    if existing is not None:
        _raise(
            status.HTTP_409_CONFLICT,
            RFQ_MR_ALREADY_LINKED,
            "This material requisition already has an RFQ",
        )

    return requisition


def _mr_items_to_rfq_data(
    db: Session,
    current_user: User,
    requisition,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for requisition_item in requisition.items:
        if requisition_item.item_id is None:
            _raise(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                RFQ_MR_ITEM_UNAVAILABLE,
                "A material requisition item no longer has an active material reference",
            )

        rows.append(
            {
                "item_id": requisition_item.item_id,
                "quantity": requisition_item.quantity,
                "specifications": requisition_item.notes,
            }
        )

    return rows


def create_rfq(
    db: Session,
    current_user: User,
    data: dict[str, Any],
) -> RequestForQuotation:
    company_id = tenant_id(current_user)
    mr_id = data.get("mr_id")
    mr_items: list[dict[str, Any]] = []

    if mr_id is not None:
        requisition = _get_approved_mr_for_rfq(
            db=db,
            current_user=current_user,
            mr_id=mr_id,
        )
        mr_items = _mr_items_to_rfq_data(
            db=db,
            current_user=current_user,
            requisition=requisition,
        )

    items_data = mr_items if mr_id is not None else data.get("items", [])

    for _ in range(5):
        try:
            rfq = RequestForQuotation(
                company_id=company_id,
                rfq_number=_next_rfq_number(db, company_id),
                mr_id=mr_id,
                title=str(data["title"]).strip(),
                description=data.get("description"),
                deadline_date=data["deadline_date"],
                status=RFQStatus.DRAFT.value,
                created_by_user_id=current_user.id,
            )
            db.add(rfq)
            db.flush()

            for supplier_id in data.get("supplier_ids", []):
                db.add(
                    _build_rfq_supplier(
                        db=db,
                        current_user=current_user,
                        rfq_id=rfq.id,
                        supplier_id=supplier_id,
                    )
                )

            for item_data in items_data:
                db.add(
                    _build_rfq_item(
                        db=db,
                        current_user=current_user,
                        rfq_id=rfq.id,
                        data=item_data,
                    )
                )

            db.commit()
            return get_rfq_or_404(db, current_user, rfq.id)

        except IntegrityError as exc:
            db.rollback()
            text = str(exc.orig)

            if "uq_rfqs_company_number" in text:
                continue

            if "uq_rfqs_company_mr" in text:
                _raise(
                    status.HTTP_409_CONFLICT,
                    RFQ_MR_ALREADY_LINKED,
                    "This material requisition already has an RFQ",
                )

            raise

        except Exception:
            db.rollback()
            raise

    _raise(
        status.HTTP_409_CONFLICT,
        RFQ_NUMBER_GENERATION_FAILED,
        "Could not generate a unique RFQ number",
    )


def list_rfqs(
    db: Session,
    current_user: User,
    rfq_status: Optional[str] = None,
    mr_id: Optional[int] = None,
    page: int = 1,
    size: int = 20,
) -> list[RequestForQuotation]:
    query = _rfq_query(db).filter(
        RequestForQuotation.company_id == tenant_id(current_user)
    )

    if rfq_status:
        query = query.filter(RequestForQuotation.status == rfq_status)

    if mr_id:
        query = query.filter(RequestForQuotation.mr_id == mr_id)

    return (
        query.order_by(RequestForQuotation.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )


def search_rfqs(
    db: Session,
    current_user: User,
    query_text: str,
    page: int = 1,
    size: int = 20,
) -> list[RequestForQuotation]:
    pattern = f"%{query_text.strip()}%"

    query = (
        _rfq_query(db)
        .outerjoin(RFQItem, RFQItem.rfq_id == RequestForQuotation.id)
        .outerjoin(RFQSupplier, RFQSupplier.rfq_id == RequestForQuotation.id)
        .filter(
            RequestForQuotation.company_id == tenant_id(current_user),
            or_(
                RequestForQuotation.rfq_number.ilike(pattern),
                RequestForQuotation.title.ilike(pattern),
                RequestForQuotation.description.ilike(pattern),
                RFQItem.item_name.ilike(pattern),
                RFQItem.item_code.ilike(pattern),
                RFQSupplier.supplier_name.ilike(pattern),
                RFQSupplier.supplier_code.ilike(pattern),
            ),
        )
        .distinct()
    )

    return (
        query.order_by(RequestForQuotation.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )


def update_rfq(
    db: Session,
    current_user: User,
    rfq_id: int,
    data: dict[str, Any],
) -> RequestForQuotation:
    rfq = get_rfq_or_404(db, current_user, rfq_id)
    _assert_draft(rfq)

    if "title" in data:
        rfq.title = str(data["title"]).strip()

    if "description" in data:
        rfq.description = data["description"]

    if "deadline_date" in data:
        rfq.deadline_date = data["deadline_date"]

    db.commit()
    return get_rfq_or_404(db, current_user, rfq.id)


def delete_rfq(
    db: Session,
    current_user: User,
    rfq_id: int,
) -> None:
    rfq = get_rfq_or_404(db, current_user, rfq_id)
    _assert_draft(rfq)
    db.delete(rfq)
    db.commit()


def add_rfq_supplier(
    db: Session,
    current_user: User,
    rfq_id: int,
    supplier_id: int,
) -> RFQSupplier:
    rfq = get_rfq_or_404(db, current_user, rfq_id)
    _assert_draft(rfq)

    existing = (
        db.query(RFQSupplier.id)
        .filter(
            RFQSupplier.rfq_id == rfq.id,
            RFQSupplier.supplier_id == supplier_id,
        )
        .first()
    )

    if existing is not None:
        _raise(
            status.HTTP_409_CONFLICT,
            RFQ_SUPPLIER_ALREADY_EXISTS,
            "Supplier is already invited to this RFQ",
        )

    rfq_supplier = _build_rfq_supplier(
        db=db,
        current_user=current_user,
        rfq_id=rfq.id,
        supplier_id=supplier_id,
    )

    db.add(rfq_supplier)
    db.commit()
    db.refresh(rfq_supplier)
    return rfq_supplier


def delete_rfq_supplier(
    db: Session,
    current_user: User,
    rfq_id: int,
    supplier_id: int,
) -> None:
    rfq = get_rfq_or_404(db, current_user, rfq_id)
    _assert_draft(rfq)

    rfq_supplier = _get_rfq_supplier_or_404(
        db=db,
        rfq=rfq,
        supplier_id=supplier_id,
    )

    db.delete(rfq_supplier)
    db.commit()


def add_rfq_item(
    db: Session,
    current_user: User,
    rfq_id: int,
    data: dict[str, Any],
) -> RFQItem:
    rfq = get_rfq_or_404(db, current_user, rfq_id)
    _assert_draft(rfq)

    rfq_item = _build_rfq_item(
        db=db,
        current_user=current_user,
        rfq_id=rfq.id,
        data=data,
    )

    db.add(rfq_item)
    db.commit()
    db.refresh(rfq_item)
    return rfq_item


def update_rfq_item(
    db: Session,
    current_user: User,
    rfq_id: int,
    rfq_item_id: int,
    data: dict[str, Any],
) -> RFQItem:
    rfq = get_rfq_or_404(db, current_user, rfq_id)
    _assert_draft(rfq)

    rfq_item = _get_rfq_item_or_404(
        db=db,
        rfq=rfq,
        rfq_item_id=rfq_item_id,
    )

    if "item_id" in data:
        reference = _resolve_item_reference(
            db=db,
            current_user=current_user,
            item_id=data["item_id"],
        )
        rfq_item.item_id = reference["id"]
        rfq_item.item_code = reference["item_code"]
        rfq_item.item_name = reference["name"]
        rfq_item.unit_id = reference["unit_id"]
        rfq_item.unit_code = reference["unit_code"]

    if "quantity" in data:
        rfq_item.quantity = data["quantity"]

    if "specifications" in data:
        rfq_item.specifications = data["specifications"]

    db.commit()
    db.refresh(rfq_item)
    return rfq_item


def delete_rfq_item(
    db: Session,
    current_user: User,
    rfq_id: int,
    rfq_item_id: int,
) -> None:
    rfq = get_rfq_or_404(db, current_user, rfq_id)
    _assert_draft(rfq)

    rfq_item = _get_rfq_item_or_404(
        db=db,
        rfq=rfq,
        rfq_item_id=rfq_item_id,
    )

    db.delete(rfq_item)
    db.commit()


def get_rfq_transition_target(
    current_status: str,
    action: str,
) -> Optional[str]:
    transitions = {
        "send": {
            RFQStatus.DRAFT.value: RFQStatus.SENT.value,
        },
        "close": {
            RFQStatus.SENT.value: RFQStatus.CLOSED.value,
        },
        "cancel": {
            RFQStatus.DRAFT.value: RFQStatus.CANCELLED.value,
            RFQStatus.SENT.value: RFQStatus.CANCELLED.value,
        },
    }

    return transitions.get(action, {}).get(current_status)


def transition_rfq(
    db: Session,
    current_user: User,
    rfq_id: int,
    action: str,
) -> RequestForQuotation:
    rfq = get_rfq_or_404(db, current_user, rfq_id)
    normalized_action = action.strip().lower()

    if normalized_action == "send":
        if not rfq.items:
            _raise(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                RFQ_HAS_NO_ITEMS,
                "An RFQ must contain at least one item before sending",
            )

        if not rfq.suppliers:
            _raise(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                RFQ_HAS_NO_SUPPLIERS,
                "An RFQ must contain at least one supplier before sending",
            )

    target_status = get_rfq_transition_target(rfq.status, normalized_action)

    if target_status is None:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            RFQ_INVALID_STATUS_TRANSITION,
            f"Cannot apply action '{normalized_action}' from status '{rfq.status}'",
        )

    rfq.status = target_status

    if normalized_action == "send":
        sent_at = datetime.utcnow()
        for rfq_supplier in rfq.suppliers:
            rfq_supplier.sent_at = sent_at
            rfq_supplier.response_status = RFQSupplierResponseStatus.PENDING.value

    db.commit()
    return get_rfq_or_404(db, current_user, rfq.id)


def _validate_quote_money(
    db: Session,
    values: dict[str, Any],
) -> None:
    fields = (
        "unit_price",
        "currency_id",
        "unit_price_base",
        "base_currency_id",
        "exchange_rate_used",
    )

    if any(values.get(field) is None for field in fields):
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            RFQ_INVALID_QUOTE_MONEY,
            "Quotation monetary fields must be provided together",
        )

    from shared.currency.services import get_currency_or_404

    get_currency_or_404(db, values["currency_id"])
    get_currency_or_404(db, values["base_currency_id"])


def _build_response_item(
    db: Session,
    rfq: RequestForQuotation,
    quotation_response_id: int,
    data: dict[str, Any],
) -> QuotationResponseItem:
    _get_rfq_item_or_404(
        db=db,
        rfq=rfq,
        rfq_item_id=data["rfq_item_id"],
    )
    _validate_quote_money(db, data)

    return QuotationResponseItem(
        quotation_response_id=quotation_response_id,
        rfq_item_id=data["rfq_item_id"],
        unit_price=data["unit_price"],
        currency_id=data["currency_id"],
        unit_price_base=data["unit_price_base"],
        base_currency_id=data["base_currency_id"],
        exchange_rate_used=data["exchange_rate_used"],
        lead_time_days=data.get("lead_time_days"),
        notes=data.get("notes"),
    )


def create_quotation_response(
    db: Session,
    current_user: User,
    rfq_id: int,
    data: dict[str, Any],
) -> QuotationResponse:
    rfq = get_rfq_or_404(db, current_user, rfq_id)
    _assert_sent(rfq)

    supplier_reference = _resolve_supplier_reference(
        db=db,
        current_user=current_user,
        supplier_id=data["supplier_id"],
    )

    rfq_supplier = _get_rfq_supplier_or_404(
        db=db,
        rfq=rfq,
        supplier_id=supplier_reference["id"],
    )

    if rfq_supplier.response_status == RFQSupplierResponseStatus.DECLINED.value:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            QUOTATION_RESPONSE_NOT_EDITABLE,
            "A declined supplier cannot submit a quotation response",
        )

    existing = (
        db.query(QuotationResponse.id)
        .filter(
            QuotationResponse.rfq_id == rfq.id,
            QuotationResponse.supplier_id == supplier_reference["id"],
        )
        .first()
    )

    if existing is not None:
        _raise(
            status.HTTP_409_CONFLICT,
            QUOTATION_RESPONSE_ALREADY_EXISTS,
            "This supplier already has a quotation response for the RFQ",
        )

    response = QuotationResponse(
        rfq_id=rfq.id,
        supplier_id=supplier_reference["id"],
        supplier_code=supplier_reference["code"],
        supplier_name=supplier_reference["name"],
        received_at=data.get("received_at") or datetime.utcnow(),
        valid_until=data.get("valid_until"),
        payment_terms=data.get("payment_terms"),
        delivery_days=data.get("delivery_days"),
        notes=data.get("notes"),
    )
    rfq.responses.append(response)
    db.add(response)
    db.flush()

    for item_data in data["items"]:
        response.items.append(
            _build_response_item(
                db=db,
                rfq=rfq,
                quotation_response_id=response.id,
                data=item_data,
            )
        )

    rfq_supplier.response_status = RFQSupplierResponseStatus.RESPONDED.value

    db.commit()
    return _get_response_or_404(db, rfq, response.id)


def update_quotation_response(
    db: Session,
    current_user: User,
    rfq_id: int,
    quotation_response_id: int,
    data: dict[str, Any],
) -> QuotationResponse:
    rfq = get_rfq_or_404(db, current_user, rfq_id)
    _assert_sent(rfq)

    response = _get_response_or_404(
        db=db,
        rfq=rfq,
        quotation_response_id=quotation_response_id,
    )

    if response.is_winner:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            QUOTATION_RESPONSE_NOT_EDITABLE,
            "The winning quotation response cannot be modified",
        )

    for key, value in data.items():
        setattr(response, key, value)

    db.commit()
    return _get_response_or_404(db, rfq, response.id)


def delete_quotation_response(
    db: Session,
    current_user: User,
    rfq_id: int,
    quotation_response_id: int,
) -> None:
    rfq = get_rfq_or_404(db, current_user, rfq_id)
    _assert_sent(rfq)

    response = _get_response_or_404(
        db=db,
        rfq=rfq,
        quotation_response_id=quotation_response_id,
    )

    if response.is_winner:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            QUOTATION_RESPONSE_NOT_EDITABLE,
            "The winning quotation response cannot be deleted",
        )

    if response.supplier_id is not None:
        rfq_supplier = _get_rfq_supplier_or_404(
            db=db,
            rfq=rfq,
            supplier_id=response.supplier_id,
        )
        rfq_supplier.response_status = RFQSupplierResponseStatus.PENDING.value

    db.delete(response)
    db.commit()


def add_quotation_response_item(
    db: Session,
    current_user: User,
    rfq_id: int,
    quotation_response_id: int,
    data: dict[str, Any],
) -> QuotationResponseItem:
    rfq = get_rfq_or_404(db, current_user, rfq_id)
    _assert_sent(rfq)

    response = _get_response_or_404(
        db=db,
        rfq=rfq,
        quotation_response_id=quotation_response_id,
    )

    if response.is_winner:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            QUOTATION_RESPONSE_NOT_EDITABLE,
            "The winning quotation response cannot be modified",
        )

    existing = (
        db.query(QuotationResponseItem.id)
        .filter(
            QuotationResponseItem.quotation_response_id == response.id,
            QuotationResponseItem.rfq_item_id == data["rfq_item_id"],
        )
        .first()
    )

    if existing is not None:
        _raise(
            status.HTTP_409_CONFLICT,
            QUOTATION_RESPONSE_ITEM_ALREADY_EXISTS,
            "This RFQ item already has a quotation line for the supplier",
        )

    response_item = _build_response_item(
        db=db,
        rfq=rfq,
        quotation_response_id=response.id,
        data=data,
    )

    db.add(response_item)
    db.commit()
    db.refresh(response_item)
    return response_item


def update_quotation_response_item(
    db: Session,
    current_user: User,
    rfq_id: int,
    quotation_response_id: int,
    quotation_response_item_id: int,
    data: dict[str, Any],
) -> QuotationResponseItem:
    rfq = get_rfq_or_404(db, current_user, rfq_id)
    _assert_sent(rfq)

    response = _get_response_or_404(
        db=db,
        rfq=rfq,
        quotation_response_id=quotation_response_id,
    )

    if response.is_winner:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            QUOTATION_RESPONSE_NOT_EDITABLE,
            "The winning quotation response cannot be modified",
        )

    response_item = _get_response_item_or_404(
        db=db,
        response=response,
        quotation_response_item_id=quotation_response_item_id,
    )

    if "rfq_item_id" in data:
        _get_rfq_item_or_404(
            db=db,
            rfq=rfq,
            rfq_item_id=data["rfq_item_id"],
        )

        duplicate = (
            db.query(QuotationResponseItem.id)
            .filter(
                QuotationResponseItem.quotation_response_id == response.id,
                QuotationResponseItem.rfq_item_id == data["rfq_item_id"],
                QuotationResponseItem.id != response_item.id,
            )
            .first()
        )

        if duplicate is not None:
            _raise(
                status.HTTP_409_CONFLICT,
                QUOTATION_RESPONSE_ITEM_ALREADY_EXISTS,
                "This RFQ item already has a quotation line for the supplier",
            )

        response_item.rfq_item_id = data["rfq_item_id"]

    money_fields = (
        "unit_price",
        "currency_id",
        "unit_price_base",
        "base_currency_id",
        "exchange_rate_used",
    )

    if any(field in data for field in money_fields):
        merged_values = {
            field: data[field] if field in data else getattr(response_item, field)
            for field in money_fields
        }
        _validate_quote_money(db, merged_values)

        for field, value in merged_values.items():
            setattr(response_item, field, value)

    if "lead_time_days" in data:
        response_item.lead_time_days = data["lead_time_days"]

    if "notes" in data:
        response_item.notes = data["notes"]

    db.commit()
    db.refresh(response_item)
    return response_item


def delete_quotation_response_item(
    db: Session,
    current_user: User,
    rfq_id: int,
    quotation_response_id: int,
    quotation_response_item_id: int,
) -> None:
    rfq = get_rfq_or_404(db, current_user, rfq_id)
    _assert_sent(rfq)

    response = _get_response_or_404(
        db=db,
        rfq=rfq,
        quotation_response_id=quotation_response_id,
    )

    if response.is_winner:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            QUOTATION_RESPONSE_NOT_EDITABLE,
            "The winning quotation response cannot be modified",
        )

    response_item = _get_response_item_or_404(
        db=db,
        response=response,
        quotation_response_item_id=quotation_response_item_id,
    )

    db.delete(response_item)
    db.commit()


def select_winning_quotation(
    db: Session,
    current_user: User,
    rfq_id: int,
    quotation_response_id: int,
) -> RequestForQuotation:
    rfq = get_rfq_or_404(db, current_user, rfq_id)
    _assert_sent(rfq)

    response = _get_response_or_404(
        db=db,
        rfq=rfq,
        quotation_response_id=quotation_response_id,
    )

    _validate_winning_quotation_for_purchase(
        rfq=rfq,
        winning_response=response,
    )

    winner_exists = any(existing.is_winner for existing in rfq.responses)

    if winner_exists:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            RFQ_WINNER_ALREADY_SELECTED,
            "This RFQ already has a winning quotation",
        )

    response.is_winner = True
    response.selected_by_user_id = current_user.id
    response.selected_at = datetime.utcnow()
    rfq.status = RFQStatus.CLOSED.value

    db.commit()
    return get_rfq_or_404(db, current_user, rfq.id)


def get_rfq_comparison(
    db: Session,
    current_user: User,
    rfq_id: int,
) -> dict[str, Any]:
    rfq = get_rfq_or_404(db, current_user, rfq_id)

    responses_by_supplier_id = {
        response.supplier_id: response
        for response in rfq.responses
        if response.supplier_id is not None
    }

    suppliers = []

    for rfq_supplier in rfq.suppliers:
        response = responses_by_supplier_id.get(rfq_supplier.supplier_id)

        suppliers.append(
            {
                "rfq_supplier_id": rfq_supplier.id,
                "supplier_id": rfq_supplier.supplier_id,
                "supplier_code": rfq_supplier.supplier_code,
                "supplier_name": rfq_supplier.supplier_name,
                "response_status": rfq_supplier.response_status,
                "response_id": response.id if response else None,
                "received_at": response.received_at if response else None,
                "valid_until": response.valid_until if response else None,
                "payment_terms": response.payment_terms if response else None,
                "delivery_days": response.delivery_days if response else None,
                "is_winner": response.is_winner if response else False,
            }
        )

    items = []

    for rfq_item in rfq.items:
        quotes = []

        for response in rfq.responses:
            for response_item in response.items:
                if response_item.rfq_item_id != rfq_item.id:
                    continue

                quotes.append(
                    {
                        "quotation_response_id": response.id,
                        "supplier_id": response.supplier_id,
                        "supplier_code": response.supplier_code,
                        "supplier_name": response.supplier_name,
                        "is_winner": response.is_winner,
                        "unit_price": response_item.unit_price,
                        "currency_id": response_item.currency_id,
                        "unit_price_base": response_item.unit_price_base,
                        "base_currency_id": response_item.base_currency_id,
                        "exchange_rate_used": response_item.exchange_rate_used,
                        "lead_time_days": response_item.lead_time_days,
                        "notes": response_item.notes,
                    }
                )

        items.append(
            {
                "rfq_item_id": rfq_item.id,
                "item_id": rfq_item.item_id,
                "item_code": rfq_item.item_code,
                "item_name": rfq_item.item_name,
                "unit_code": rfq_item.unit_code,
                "quantity": rfq_item.quantity,
                "specifications": rfq_item.specifications,
                "quotes": quotes,
            }
        )

    return {
        "rfq_id": rfq.id,
        "rfq_number": rfq.rfq_number,
        "mr_id": rfq.mr_id,
        "title": rfq.title,
        "deadline_date": rfq.deadline_date,
        "status": rfq.status,
        "suppliers": suppliers,
        "items": items,
    }

def get_winning_quotation_reference_for_purchase(
    db: Session,
    current_user: User,
    rfq_id: int,
) -> dict[str, Any]:
    rfq = get_rfq_or_404(
        db=db,
        current_user=current_user,
        rfq_id=rfq_id,
    )

    winning_response = next(
        (
            response
            for response in rfq.responses
            if response.is_winner
        ),
        None,
    )

    if winning_response is None:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            RFQ_WINNING_QUOTATION_NOT_SELECTED,
            "A winning quotation response must be selected before creating a purchase order",
        )

    first_quote_item = _validate_winning_quotation_for_purchase(
        rfq=rfq,
        winning_response=winning_response,
    )
    response_items_by_rfq_item_id = {
        item.rfq_item_id: item
        for item in winning_response.items
    }
    items: list[dict[str, Any]] = []

    for rfq_item in rfq.items:
        if rfq_item.item_id is None:
            _raise(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                RFQ_WINNING_QUOTATION_INCOMPLETE,
                "An RFQ item no longer has a material reference",
            )

        quote_item = response_items_by_rfq_item_id[rfq_item.id]

        items.append(
            {
                "item_id": rfq_item.item_id,
                "item_code": rfq_item.item_code,
                "item_name": rfq_item.item_name,
                "unit_code": rfq_item.unit_code,
                "quantity": rfq_item.quantity,
                "unit_price": quote_item.unit_price,
                "currency_id": quote_item.currency_id,
                "unit_price_base": quote_item.unit_price_base,
                "base_currency_id": quote_item.base_currency_id,
                "exchange_rate_used": quote_item.exchange_rate_used,
                "notes": quote_item.notes,
            }
        )

    return {
        "rfq_id": rfq.id,
        "rfq_number": rfq.rfq_number,
        "mr_id": rfq.mr_id,
        "title": rfq.title,
        "description": rfq.description,
        "supplier_id": winning_response.supplier_id,
        "supplier_name": winning_response.supplier_name,
        "winning_quotation_response_id": winning_response.id,
        "currency_id": first_quote_item.currency_id,
        "base_currency_id": first_quote_item.base_currency_id,
        "exchange_rate_used": first_quote_item.exchange_rate_used,
        "delivery_days": winning_response.delivery_days,
        "items": items,
    }
