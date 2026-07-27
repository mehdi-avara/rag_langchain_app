from __future__ import annotations

import logging
from decimal import Decimal
from typing import Iterable

from fastapi import HTTPException, status
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from core.exceptions.error_codes import (
    FINANCIAL_RECEIPT_ALLOCATION_CURRENCY_MISMATCH,
    FINANCIAL_RECEIPT_ALLOCATION_EXCEEDS_RECEIPT,
    FINANCIAL_RECEIPT_ALLOCATION_SUPPLIER_MISMATCH,
    FINANCIAL_RECEIPT_DIRECTION_INVALID_FOR_PURCHASE,
    FINANCIAL_RECEIPT_HAS_ALLOCATIONS,
    FINANCIAL_RECEIPT_PURCHASE_COMPANY_MISMATCH,
    PURCHASE_COST_PAYMENT_ALLOCATION_NOT_FOUND,
    PURCHASE_ORDER_COST_ALLOCATION_EXCEEDS_COST,
    FINANCIAL_RECEIPT_ALLOCATION_AMOUNT_TOO_SMALL,
)
from Models import User
from shared.currency.services import (
    get_currency_or_404,
    quantize_exchange_rate,
    quantize_money,
)

from .models import (
    FinancialDirection,
    FinancialReceipt,
    PurchaseCostPaymentAllocation,
)


logger = logging.getLogger(__name__)


def finance_error(
    status_code: int,
    code: str,
    message: str,
):
    raise HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
        },
    )


def tenant_id(
    current_user: User,
) -> int:
    company_id = getattr(
        current_user,
        "company_id",
        None,
    )

    if company_id is None:
        finance_error(
            status.HTTP_403_FORBIDDEN,
            FINANCIAL_RECEIPT_PURCHASE_COMPANY_MISMATCH,
            (
                "Current user does not "
                "belong to a company"
            ),
        )

    return int(company_id)


def get_receipt_for_allocation(
    db: Session,
    current_user: User,
    receipt_id: int,
    *,
    lock: bool = False,
) -> FinancialReceipt:
    query = (
        db.query(FinancialReceipt)
        .filter(
            FinancialReceipt.id == receipt_id,
            FinancialReceipt.company_id
            == tenant_id(current_user),
        )
    )

    if lock:
        query = query.with_for_update()

    receipt = query.first()

    if receipt is None:
        finance_error(
            status.HTTP_404_NOT_FOUND,
            "FINANCIAL_RECEIPT_NOT_FOUND",
            "Financial receipt not found",
        )

    return receipt


def _lock_cost(
    db: Session,
    cost_id: int,
) -> None:
    db.execute(
        text(
            "SELECT pg_advisory_xact_lock(:key)"
        ),
        {
            "key": 1_300_000_000
            + int(cost_id),
        },
    )


def _purchase_cost_reference(
    db: Session,
    current_user: User,
    cost_id: int,
) -> dict:
    from purchase_management.services import (
        get_purchase_cost_reference_for_finance,
    )

    return (
        get_purchase_cost_reference_for_finance(
            db=db,
            current_user=current_user,
            cost_id=cost_id,
        )
    )


def _receipt_allocated_base(
    db: Session,
    receipt_id: int,
) -> Decimal:
    value = (
        db.query(
            func.coalesce(
                func.sum(
                    PurchaseCostPaymentAllocation
                    .allocated_amount_base
                ),
                0,
            )
        )
        .filter(
            PurchaseCostPaymentAllocation
            .financial_receipt_id
            == receipt_id,
        )
        .scalar()
    )

    return Decimal(str(value or 0))


def _cost_allocated_base(
    db: Session,
    company_id: int,
    cost_id: int,
) -> Decimal:
    value = (
        db.query(
            func.coalesce(
                func.sum(
                    PurchaseCostPaymentAllocation
                    .allocated_amount_base
                ),
                0,
            )
        )
        .filter(
            PurchaseCostPaymentAllocation
            .company_id
            == company_id,
            PurchaseCostPaymentAllocation
            .purchase_order_cost_id
            == cost_id,
        )
        .scalar()
    )

    return Decimal(str(value or 0))


def _existing_receipt_supplier_ids(
    db: Session,
    current_user: User,
    receipt_id: int,
) -> set[int]:
    cost_ids = [
        int(value)
        for (value,) in (
            db.query(
                PurchaseCostPaymentAllocation
                .purchase_order_cost_id
            )
            .filter(
                PurchaseCostPaymentAllocation
                .financial_receipt_id
                == receipt_id,
            )
            .distinct()
            .all()
        )
    ]

    return {
        int(
            _purchase_cost_reference(
                db=db,
                current_user=current_user,
                cost_id=cost_id,
            )["supplier_id"]
        )
        for cost_id in cost_ids
    }


def _validate_receipt_context(
    receipt: FinancialReceipt,
) -> None:
    direction = getattr(
        receipt.direction,
        "value",
        receipt.direction,
    )

    if (
        direction
        != FinancialDirection.OUTPUT.value
    ):
        finance_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            (
                FINANCIAL_RECEIPT_DIRECTION_INVALID_FOR_PURCHASE
            ),
            (
                "Only output receipts may "
                "be allocated to purchase costs"
            ),
        )

    if (
        receipt.currency_id is None
        or receipt.base_currency_id is None
        or receipt.amount_base is None
        or receipt.exchange_rate_used is None
    ):
        finance_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            FINANCIAL_RECEIPT_ALLOCATION_CURRENCY_MISMATCH,
            (
                "Receipt canonical money "
                "fields are incomplete"
            ),
        )


def _prepare_allocation(
    db: Session,
    current_user: User,
    receipt: FinancialReceipt,
    *,
    purchase_order_cost_id: int,
    allocated_amount,
    currency_id: int | None,
    exchange_rate_used,
) -> tuple[dict, dict]:
    cost_id = int(
        purchase_order_cost_id
    )

    _lock_cost(
        db=db,
        cost_id=cost_id,
    )

    reference = _purchase_cost_reference(
        db=db,
        current_user=current_user,
        cost_id=cost_id,
    )

    company_id = tenant_id(
        current_user
    )

    if (
        int(reference["company_id"])
        != company_id
        or int(receipt.company_id)
        != company_id
    ):
        finance_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            FINANCIAL_RECEIPT_PURCHASE_COMPANY_MISMATCH,
            (
                "Receipt and purchase cost "
                "must belong to the same company"
            ),
        )

    normalized_currency_id = int(
        currency_id
        if currency_id is not None
        else receipt.currency_id
    )

    if (
        normalized_currency_id
        != int(receipt.currency_id)
    ):
        finance_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            FINANCIAL_RECEIPT_ALLOCATION_CURRENCY_MISMATCH,
            (
                "Allocation currency must "
                "match the receipt currency"
            ),
        )

    target_currency_id = reference.get(
        "target_currency_id"
    )

    if (
        target_currency_id is not None
        and int(target_currency_id)
        != normalized_currency_id
    ):
        finance_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            FINANCIAL_RECEIPT_ALLOCATION_CURRENCY_MISMATCH,
            (
                "Receipt and purchase cost "
                "currencies are incompatible"
            ),
        )

    receipt_rate = quantize_exchange_rate(
        receipt.exchange_rate_used
    )

    supplied_rate = (
        receipt_rate
        if exchange_rate_used is None
        else quantize_exchange_rate(
            exchange_rate_used
        )
    )

    if supplied_rate != receipt_rate:
        finance_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            FINANCIAL_RECEIPT_ALLOCATION_CURRENCY_MISMATCH,
            (
                "Allocation exchange rate "
                "must match the frozen "
                "receipt exchange rate"
            ),
        )

    currency = get_currency_or_404(
        db=db,
        currency_id=normalized_currency_id,
    )

    base_currency = get_currency_or_404(
        db=db,
        currency_id=int(
            receipt.base_currency_id
        ),
    )

    amount = quantize_money(
        allocated_amount,
        currency.decimal_places,
    )

    if amount <= 0:
        finance_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            FINANCIAL_RECEIPT_ALLOCATION_AMOUNT_TOO_SMALL,
            (
                "Allocated amount must remain "
                "positive after currency rounding"
            ),
        )

    amount_base = quantize_money(
        amount * receipt_rate,
        base_currency.decimal_places,
    )

    if amount_base <= 0:
        finance_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            FINANCIAL_RECEIPT_ALLOCATION_AMOUNT_TOO_SMALL,
            (
                "Allocated amount is too small "
                "after base-currency conversion"
            ),
        )

    return (
        {
            "purchase_order_cost_id": (
                cost_id
            ),
            "allocated_amount": amount,
            "currency_id": (
                normalized_currency_id
            ),
            "allocated_amount_base": (
                amount_base
            ),
            "exchange_rate_used": (
                receipt_rate
            ),
        },
        reference,
    )


def list_purchase_cost_allocations(
    db: Session,
    current_user: User,
    receipt_id: int,
) -> list[
    PurchaseCostPaymentAllocation
]:
    receipt = get_receipt_for_allocation(
        db=db,
        current_user=current_user,
        receipt_id=receipt_id,
    )

    return (
        db.query(
            PurchaseCostPaymentAllocation
        )
        .filter(
            PurchaseCostPaymentAllocation
            .financial_receipt_id
            == receipt.id,
            PurchaseCostPaymentAllocation
            .company_id
            == tenant_id(current_user),
        )
        .order_by(
            PurchaseCostPaymentAllocation
            .created_at.asc(),
            PurchaseCostPaymentAllocation
            .id.asc(),
        )
        .all()
    )


def create_purchase_cost_allocations(
    db: Session,
    current_user: User,
    receipt_id: int,
    allocations: Iterable,
    *,
    commit: bool = True,
) -> list[
    PurchaseCostPaymentAllocation
]:
    receipt = get_receipt_for_allocation(
        db=db,
        current_user=current_user,
        receipt_id=receipt_id,
        lock=True,
    )

    _validate_receipt_context(
        receipt
    )

    payloads = list(allocations)

    if not payloads:
        return []

    existing_supplier_ids = (
        _existing_receipt_supplier_ids(
            db=db,
            current_user=current_user,
            receipt_id=receipt.id,
        )
    )

    prepared: list[
        tuple[dict, dict]
    ] = []

    batch_supplier_ids: set[int] = set()
    batch_cost_totals: dict[
        int,
        Decimal,
    ] = {}

    for payload in payloads:
        data = (
            payload.model_dump()
            if hasattr(payload, "model_dump")
            else dict(payload)
        )

        values, reference = (
            _prepare_allocation(
                db=db,
                current_user=current_user,
                receipt=receipt,
                purchase_order_cost_id=data[
                    "purchase_order_cost_id"
                ],
                allocated_amount=data[
                    "allocated_amount"
                ],
                currency_id=data.get(
                    "currency_id"
                ),
                exchange_rate_used=data.get(
                    "exchange_rate_used"
                ),
            )
        )

        supplier_id = int(
            reference["supplier_id"]
        )

        batch_supplier_ids.add(
            supplier_id
        )

        cost_id = int(
            values[
                "purchase_order_cost_id"
            ]
        )

        batch_cost_totals[cost_id] = (
            batch_cost_totals.get(
                cost_id,
                Decimal("0"),
            )
            + Decimal(
                str(
                    values[
                        "allocated_amount_base"
                    ]
                )
            )
        )

        prepared.append(
            (
                values,
                reference,
            )
        )

    all_supplier_ids = (
        existing_supplier_ids
        | batch_supplier_ids
    )

    if len(all_supplier_ids) > 1:
        finance_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            FINANCIAL_RECEIPT_ALLOCATION_SUPPLIER_MISMATCH,
            (
                "One receipt may only cover "
                "purchase costs for one supplier"
            ),
        )

    existing_receipt_base = (
        _receipt_allocated_base(
            db=db,
            receipt_id=receipt.id,
        )
    )

    batch_receipt_base = sum(
        (
            Decimal(
                str(
                    values[
                        "allocated_amount_base"
                    ]
                )
            )
            for values, _ in prepared
        ),
        Decimal("0"),
    )

    receipt_limit = Decimal(
        str(receipt.amount_base)
    )

    if (
        existing_receipt_base
        + batch_receipt_base
        > receipt_limit
    ):
        finance_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            FINANCIAL_RECEIPT_ALLOCATION_EXCEEDS_RECEIPT,
            (
                "Allocations exceed the "
                "receipt amount"
            ),
        )

    references_by_cost = {
        int(
            values[
                "purchase_order_cost_id"
            ]
        ): reference
        for values, reference in prepared
    }

    for cost_id, batch_base in (
        batch_cost_totals.items()
    ):
        existing_cost_base = (
            _cost_allocated_base(
                db=db,
                company_id=tenant_id(
                    current_user
                ),
                cost_id=cost_id,
            )
        )

        target_base = Decimal(
            str(
                references_by_cost[
                    cost_id
                ]["target_amount_base"]
            )
        )

        if (
            existing_cost_base
            + batch_base
            > target_base
        ):
            finance_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_COST_ALLOCATION_EXCEEDS_COST,
                (
                    "Allocation exceeds the "
                    "purchase-cost target"
                ),
            )

    created = []

    for values, _ in prepared:
        allocation = (
            PurchaseCostPaymentAllocation(
                company_id=tenant_id(
                    current_user
                ),
                financial_receipt_id=(
                    receipt.id
                ),
                created_by_user_id=(
                    current_user.id
                ),
                **values,
            )
        )

        db.add(allocation)
        created.append(allocation)

    if commit:
        db.commit()

        for allocation in created:
            db.refresh(allocation)
    else:
        db.flush()

    return created


def get_purchase_cost_allocation(
    db: Session,
    current_user: User,
    receipt_id: int,
    allocation_id: int,
    *,
    lock: bool = False,
) -> PurchaseCostPaymentAllocation:
    receipt = get_receipt_for_allocation(
        db=db,
        current_user=current_user,
        receipt_id=receipt_id,
        lock=lock,
    )

    query = (
        db.query(
            PurchaseCostPaymentAllocation
        )
        .filter(
            PurchaseCostPaymentAllocation.id
            == allocation_id,
            PurchaseCostPaymentAllocation
            .financial_receipt_id
            == receipt.id,
            PurchaseCostPaymentAllocation
            .company_id
            == tenant_id(current_user),
        )
    )

    if lock:
        query = query.with_for_update()

    allocation = query.first()

    if allocation is None:
        finance_error(
            status.HTTP_404_NOT_FOUND,
            PURCHASE_COST_PAYMENT_ALLOCATION_NOT_FOUND,
            (
                "Purchase-cost payment "
                "allocation not found"
            ),
        )

    return allocation


def delete_purchase_cost_allocation(
    db: Session,
    current_user: User,
    receipt_id: int,
    allocation_id: int,
) -> None:
    allocation = (
        get_purchase_cost_allocation(
            db=db,
            current_user=current_user,
            receipt_id=receipt_id,
            allocation_id=allocation_id,
            lock=True,
        )
    )

    audit_payload = {
        "allocation_id": allocation.id,
        "receipt_id": (
            allocation.financial_receipt_id
        ),
        "purchase_order_cost_id": (
            allocation.purchase_order_cost_id
        ),
        "allocated_amount": str(
            allocation.allocated_amount
        ),
        "allocated_amount_base": str(
            allocation.allocated_amount_base
        ),
        "deleted_by_user_id": (
            current_user.id
        ),
        "company_id": (
            allocation.company_id
        ),
    }

    db.delete(allocation)
    db.commit()

    logger.info(
        "purchase_cost_payment_allocation_deleted",
        extra={
            "purchase_cost_allocation_audit": (
                audit_payload
            )
        },
    )


def receipt_has_purchase_cost_allocations(
    db: Session,
    receipt_id: int,
) -> bool:
    return (
        db.query(
            PurchaseCostPaymentAllocation.id
        )
        .filter(
            PurchaseCostPaymentAllocation
            .financial_receipt_id
            == receipt_id,
        )
        .first()
        is not None
    )


def assert_receipt_financial_edit_allowed(
    db: Session,
    receipt: FinancialReceipt,
    changed_fields: set[str],
) -> None:
    protected_fields = {
        "amount",
        "currency",
        "currency_id",
        "base_currency",
        "base_currency_id",
        "exchange_rate_to_base",
        "exchange_rate_used",
        "base_amount",
        "amount_base",
        "direction",
        "receipt_date",
        "credit_card_id",
        "customer_id",
        "counterparty_name",
    }

    if not (
        changed_fields
        & protected_fields
    ):
        return

    if receipt_has_purchase_cost_allocations(
        db=db,
        receipt_id=receipt.id,
    ):
        finance_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            FINANCIAL_RECEIPT_HAS_ALLOCATIONS,
            (
                "Allocated receipt financial "
                "fields cannot be changed"
            ),
        )


def assert_receipt_delete_allowed(
    db: Session,
    receipt: FinancialReceipt,
) -> None:
    if receipt_has_purchase_cost_allocations(
        db=db,
        receipt_id=receipt.id,
    ):
        finance_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            FINANCIAL_RECEIPT_HAS_ALLOCATIONS,
            (
                "A receipt with purchase-cost "
                "allocations cannot be deleted"
            ),
        )
