from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from Models import User


ZERO = Decimal("0")


class ReportingValidationError(ValueError):
    pass


class ReportingNotFoundError(ValueError):
    pass


def _tenant_id(current_user: User) -> int:
    company_id = getattr(current_user, "company_id", None)

    if company_id is None:
        raise ReportingValidationError(
            "Current user does not belong to a company"
        )

    return int(company_id)


def validate_date_range(
    date_from: date | None,
    date_to: date | None,
) -> tuple[date | None, date | None]:
    if date_from and date_to and date_from > date_to:
        raise ReportingValidationError("from cannot be after to")

    return date_from, date_to


def normalize_group_by(
    group_by: str | None,
    allowed: set[str],
    default: str,
) -> str:
    normalized = (group_by or default).strip().lower()

    if normalized not in allowed:
        raise ReportingValidationError(
            "group_by must be one of: " + ", ".join(sorted(allowed))
        )

    return normalized


def _decimal(value: Any) -> Decimal:
    if value is None:
        return ZERO

    return Decimal(str(value))


def _rows(
    db: Session,
    query: str,
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in db.execute(text(query), params).mappings().all()
    ]


def _row(
    db: Session,
    query: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    result = db.execute(text(query), params).mappings().first()

    if result is None:
        raise ReportingValidationError("Company was not found")

    return dict(result)


def _currency_context(
    db: Session,
    company_id: int,
    currency_id: int | None,
) -> tuple[int | None, str]:
    result = _row(
        db,
        """
        SELECT
            companies.base_currency_id,
            COALESCE(currencies.code, companies.base_currency, 'BASE') AS currency_code
        FROM companies
        LEFT JOIN currencies
          ON currencies.id = companies.base_currency_id
        WHERE companies.id = :company_id
        """,
        {"company_id": company_id},
    )

    base_currency_id = result["base_currency_id"]
    currency_code = str(result["currency_code"])

    if currency_id is not None and currency_id <= 0:
        raise ReportingValidationError("currency_id must be greater than zero")

    if (
        currency_id is not None
        and base_currency_id is not None
        and int(currency_id) != int(base_currency_id)
    ):
        raise ReportingValidationError(
            "Reports are aggregated only in the company base currency"
        )

    return (
        int(base_currency_id) if base_currency_id is not None else None,
        currency_code,
    )


def warehouse_kpis(
    db: Session,
    current_user: User,
    currency_id: int | None = None,
) -> list[dict[str, Any]]:
    company_id = _tenant_id(current_user)
    _, currency_code = _currency_context(db, company_id, currency_id)

    warehouse_row = _row(
        db,
        """
        SELECT COUNT(*) AS warehouse_count
        FROM warehouses
        WHERE company_id = :company_id
          AND is_active IS TRUE
        """,
        {"company_id": company_id},
    )
    stock_row = _row(
        db,
        """
        SELECT
            COUNT(*) AS stock_item_count,
            COALESCE(SUM(quantity_on_hand), 0) AS quantity_on_hand_total,
            COALESCE(SUM(quantity_on_hand * unit_cost_base), 0) AS inventory_value_base,
            COUNT(*) FILTER (
                WHERE reorder_point IS NOT NULL
                  AND quantity_available <= reorder_point
            ) AS low_stock_count
        FROM stock_items
        WHERE company_id = :company_id
        """,
        {"company_id": company_id},
    )

    return [
        {
            "key": "warehouse_count",
            "label": "Active Warehouses",
            "value": int(warehouse_row["warehouse_count"] or 0),
            "unit": "count",
            "trend": "neutral",
        },
        {
            "key": "stock_item_count",
            "label": "Stock Records",
            "value": int(stock_row["stock_item_count"] or 0),
            "unit": "count",
            "trend": "neutral",
        },
        {
            "key": "low_stock_count",
            "label": "Low Stock Alerts",
            "value": int(stock_row["low_stock_count"] or 0),
            "unit": "count",
            "trend": "neutral",
        },
        {
            "key": "quantity_on_hand_total",
            "label": "Quantity On Hand",
            "value": _decimal(stock_row["quantity_on_hand_total"]),
            "unit": "units",
            "trend": "neutral",
        },
        {
            "key": "inventory_value_base",
            "label": "Inventory Value",
            "value": _decimal(stock_row["inventory_value_base"]),
            "unit": currency_code,
            "trend": "neutral",
        },
    ]


def purchase_kpis(
    db: Session,
    current_user: User,
    date_from: date | None = None,
    date_to: date | None = None,
    currency_id: int | None = None,
) -> list[dict[str, Any]]:
    company_id = _tenant_id(current_user)
    date_from, date_to = validate_date_range(date_from, date_to)
    _, currency_code = _currency_context(db, company_id, currency_id)

    conditions = [
        "po.company_id = :company_id",
        "po.status <> 'cancelled'",
    ]
    params: dict[str, Any] = {"company_id": company_id}

    if date_from is not None:
        conditions.append("po.created_at::date >= :date_from")
        params["date_from"] = date_from

    if date_to is not None:
        conditions.append("po.created_at::date <= :date_to")
        params["date_to"] = date_to

    order_filter = " AND ".join(conditions)

    order_row = _row(
        db,
        f"""
        WITH po_totals AS (
            SELECT
                po.id,
                po.approval_status,
                COALESCE(
                    (
                        SELECT SUM(
                                line.ordered_quantity
                                * line.unit_price_base
                            )
                            FROM purchase_order_lines line
                            WHERE line.purchase_order_id = po.id
                    ),
                    0
                ) + COALESCE(
                    (
                        SELECT SUM(cost.amount_base)
                        FROM purchase_order_costs cost
                        WHERE cost.purchase_order_id = po.id
                    ),
                    0
                ) AS total_base
            FROM purchase_orders po
            WHERE {order_filter}
        )
        SELECT
            COUNT(*) AS purchase_order_count,
            COUNT(*) FILTER (
                WHERE approval_status = 'approved'
            ) AS approved_order_count,
            COALESCE(SUM(total_base), 0) AS committed_spend_base,
            COALESCE(AVG(total_base), 0) AS average_order_value_base
        FROM po_totals
        """,
        params,
    )

    cycle_conditions = [
        "mr.company_id = :company_id",
        "grn.status = 'posted'",
    ]
    cycle_params: dict[str, Any] = {"company_id": company_id}

    if date_from is not None:
        cycle_conditions.append("grn.receipt_date >= :date_from")
        cycle_params["date_from"] = date_from

    if date_to is not None:
        cycle_conditions.append("grn.receipt_date <= :date_to")
        cycle_params["date_to"] = date_to

    cycle_filter = " AND ".join(cycle_conditions)

    cycle_row = _row(
        db,
        f"""
        WITH completed_cycles AS (
            SELECT
                mr.id,
                MIN(grn.receipt_date) AS completed_on,
                GREATEST(
                    EXTRACT(
                        EPOCH FROM (
                            MIN(grn.receipt_date)::timestamp - mr.created_at
                        )
                    ) / 86400,
                    0
                ) AS cycle_days
            FROM material_requisitions mr
            JOIN rfqs rfq
              ON rfq.mr_id = mr.id
            JOIN purchase_orders po
              ON po.source_rfq_id = rfq.id
            JOIN goods_receipt_notes grn
              ON grn.purchase_order_id = po.id
            WHERE {cycle_filter}
            GROUP BY mr.id, mr.created_at
        )
        SELECT
            COUNT(*) AS completed_cycle_count,
            COALESCE(AVG(cycle_days), 0) AS average_cycle_days
        FROM completed_cycles
        """,
        cycle_params,
    )

    return [
        {
            "key": "purchase_order_count",
            "label": "Purchase Orders",
            "value": int(order_row["purchase_order_count"] or 0),
            "unit": "count",
            "trend": "neutral",
        },
        {
            "key": "approved_order_count",
            "label": "Approved Purchase Orders",
            "value": int(order_row["approved_order_count"] or 0),
            "unit": "count",
            "trend": "neutral",
        },
        {
            "key": "committed_spend_base",
            "label": "Committed Spend",
            "value": _decimal(order_row["committed_spend_base"]),
            "unit": currency_code,
            "trend": "neutral",
        },
        {
            "key": "average_order_value_base",
            "label": "Average Purchase Order Value",
            "value": _decimal(order_row["average_order_value_base"]),
            "unit": currency_code,
            "trend": "neutral",
        },
        {
            "key": "completed_procurement_cycles",
            "label": "Completed Procurement Cycles",
            "value": int(cycle_row["completed_cycle_count"] or 0),
            "unit": "count",
            "trend": "neutral",
        },
        {
            "key": "average_procurement_cycle_days",
            "label": "Average Procurement Cycle",
            "value": _decimal(cycle_row["average_cycle_days"]),
            "unit": "days",
            "trend": "neutral",
        },
    ]


def warehouse_report(
    db: Session,
    current_user: User,
    name: str,
    date_from: date | None = None,
    date_to: date | None = None,
    group_by: str | None = None,
    currency_id: int | None = None,
) -> dict[str, Any]:
    company_id = _tenant_id(current_user)
    validate_date_range(date_from, date_to)
    _, currency_code = _currency_context(db, company_id, currency_id)
    report_name = name.strip().lower()

    if report_name == "stock-valuation":
        if date_from is not None or date_to is not None:
            raise ReportingValidationError(
                "stock-valuation is a current-state report and does not support from/to"
            )

        normalized_group_by = normalize_group_by(
            group_by,
            {"warehouse"},
            "warehouse",
        )

        rows = _rows(
            db,
            """
            SELECT
                CONCAT(warehouse.code, ' — ', warehouse.name) AS label,
                COALESCE(
                    SUM(stock.quantity_on_hand * stock.unit_cost_base),
                    0
                ) AS value
            FROM stock_items stock
            JOIN storage_locations location
              ON location.id = stock.storage_location_id
            JOIN warehouse_zones zone
              ON zone.id = location.zone_id
            JOIN warehouses warehouse
              ON warehouse.id = zone.warehouse_id
            WHERE stock.company_id = :company_id
            GROUP BY warehouse.id, warehouse.code, warehouse.name
            ORDER BY value DESC, warehouse.code ASC
            """,
            {"company_id": company_id},
        )

        return {
            "chart_type": "bar",
            "x": [str(row["label"]) for row in rows],
            "series": [
                {
                    "name": "Inventory Value",
                    "data": [_decimal(row["value"]) for row in rows],
                }
            ],
            "unit": currency_code,
            "metadata": {
                "group_by": normalized_group_by,
                "basis": "current_weighted_average_cost",
            },
        }

    if report_name == "low-stock":
        if date_from is not None or date_to is not None:
            raise ReportingValidationError(
                "low-stock is a current-state report and does not support from/to"
            )

        normalized_group_by = normalize_group_by(
            group_by,
            {"warehouse"},
            "warehouse",
        )

        rows = _rows(
            db,
            """
            SELECT
                CONCAT(
                    warehouse.code,
                    ' — ',
                    item.item_code,
                    ' — ',
                    item.name
                ) AS label,
                stock.quantity_available,
                stock.reorder_point
            FROM stock_items stock
            JOIN items item
              ON item.id = stock.item_id
            JOIN storage_locations location
              ON location.id = stock.storage_location_id
            JOIN warehouse_zones zone
              ON zone.id = location.zone_id
            JOIN warehouses warehouse
              ON warehouse.id = zone.warehouse_id
            WHERE stock.company_id = :company_id
              AND stock.reorder_point IS NOT NULL
              AND stock.quantity_available <= stock.reorder_point
            ORDER BY warehouse.code ASC, item.item_code ASC
            """,
            {"company_id": company_id},
        )

        return {
            "chart_type": "table",
            "x": [str(row["label"]) for row in rows],
            "series": [
                {
                    "name": "Available Quantity",
                    "data": [
                        _decimal(row["quantity_available"])
                        for row in rows
                    ],
                },
                {
                    "name": "Reorder Point",
                    "data": [
                        _decimal(row["reorder_point"])
                        for row in rows
                    ],
                },
            ],
            "unit": "units",
            "metadata": {
                "group_by": normalized_group_by,
                "row_count": len(rows),
            },
        }

    raise ReportingNotFoundError("Unknown warehouse report")


def purchase_report(
    db: Session,
    current_user: User,
    name: str,
    date_from: date | None = None,
    date_to: date | None = None,
    group_by: str | None = None,
    currency_id: int | None = None,
) -> dict[str, Any]:
    company_id = _tenant_id(current_user)
    date_from, date_to = validate_date_range(date_from, date_to)
    _, currency_code = _currency_context(db, company_id, currency_id)
    report_name = name.strip().lower()

    if report_name == "spend-by-supplier":
        normalized_group_by = normalize_group_by(
            group_by,
            {"supplier", "month"},
            "supplier",
        )

        conditions = [
            "po.company_id = :company_id",
            "po.status <> 'cancelled'",
        ]
        params: dict[str, Any] = {"company_id": company_id}

        if date_from is not None:
            conditions.append("po.created_at::date >= :date_from")
            params["date_from"] = date_from

        if date_to is not None:
            conditions.append("po.created_at::date <= :date_to")
            params["date_to"] = date_to

        order_filter = " AND ".join(conditions)

        if normalized_group_by == "supplier":
            label_sql = (
                "COALESCE(NULLIF(supplier_name, ''), 'Unassigned')"
            )
            chart_type = "bar"
        else:
            label_sql = "TO_CHAR(DATE_TRUNC('month', po.created_at), 'YYYY-MM')"
            chart_type = "line"

        rows = _rows(
            db,
            f"""
            WITH po_totals AS (
                SELECT
                    po.id,
                    supplier.name AS supplier_name,
                    po.created_at,
                    COALESCE(
                        (
                            SELECT SUM(
                                line.ordered_quantity
                                * line.unit_price_base
                            )
                            FROM purchase_order_lines line
                            WHERE line.purchase_order_id = po.id
                        ),
                        0
                    ) + COALESCE(
                        (
                            SELECT SUM(cost.amount_base)
                            FROM purchase_order_costs cost
                            WHERE cost.purchase_order_id = po.id
                        ),
                        0
                    ) AS total_base
                FROM purchase_orders po
                JOIN suppliers AS supplier
                  ON supplier.id = po.supplier_id
                WHERE {order_filter}
            )
            SELECT
                {label_sql} AS label,
                COALESCE(SUM(total_base), 0) AS value
            FROM po_totals po
            GROUP BY label
            ORDER BY label ASC
            """,
            params,
        )

        return {
            "chart_type": chart_type,
            "x": [str(row["label"]) for row in rows],
            "series": [
                {
                    "name": "Committed Spend",
                    "data": [_decimal(row["value"]) for row in rows],
                }
            ],
            "unit": currency_code,
            "metadata": {
                "group_by": normalized_group_by,
                "date_basis": "purchase_order_created_at",
            },
        }

    if report_name == "procurement-cycle":
        normalized_group_by = normalize_group_by(
            group_by,
            {"month", "requisition"},
            "month",
        )

        conditions = [
            "mr.company_id = :company_id",
            "grn.status = 'posted'",
        ]
        params: dict[str, Any] = {"company_id": company_id}

        if date_from is not None:
            conditions.append("grn.receipt_date >= :date_from")
            params["date_from"] = date_from

        if date_to is not None:
            conditions.append("grn.receipt_date <= :date_to")
            params["date_to"] = date_to

        cycle_filter = " AND ".join(conditions)

        if normalized_group_by == "month":
            select_label = (
                "TO_CHAR(DATE_TRUNC('month', completed_on), 'YYYY-MM')"
            )
            group_clause = "label"
            aggregation = "AVG(cycle_days)"
            chart_type = "bar"
        else:
            select_label = "mr_number"
            group_clause = "label"
            aggregation = "AVG(cycle_days)"
            chart_type = "bar"

        rows = _rows(
            db,
            f"""
            WITH completed_cycles AS (
                SELECT
                    mr.mr_number,
                    MIN(grn.receipt_date)::timestamp AS completed_on,
                    GREATEST(
                        EXTRACT(
                            EPOCH FROM (
                                MIN(grn.receipt_date)::timestamp - mr.created_at
                            )
                        ) / 86400,
                        0
                    ) AS cycle_days
                FROM material_requisitions mr
                JOIN rfqs rfq
                  ON rfq.mr_id = mr.id
                JOIN purchase_orders po
                  ON po.source_rfq_id = rfq.id
                JOIN goods_receipt_notes grn
                  ON grn.purchase_order_id = po.id
                WHERE {cycle_filter}
                GROUP BY mr.id, mr.mr_number, mr.created_at
            )
            SELECT
                {select_label} AS label,
                COALESCE({aggregation}, 0) AS value
            FROM completed_cycles
            GROUP BY {group_clause}
            ORDER BY label ASC
            """,
            params,
        )

        return {
            "chart_type": chart_type,
            "x": [str(row["label"]) for row in rows],
            "series": [
                {
                    "name": "Procurement Cycle",
                    "data": [_decimal(row["value"]) for row in rows],
                }
            ],
            "unit": "days",
            "metadata": {
                "group_by": normalized_group_by,
                "date_basis": "first_posted_grn_receipt_date",
            },
        }

    if report_name == "grn-vs-po-variance":
        normalized_group_by = normalize_group_by(
            group_by,
            {"purchase_order"},
            "purchase_order",
        )

        conditions = [
            "po.company_id = :company_id",
            "po.status <> 'cancelled'",
        ]
        params: dict[str, Any] = {"company_id": company_id}

        if date_from is not None:
            conditions.append("po.created_at::date >= :date_from")
            params["date_from"] = date_from

        if date_to is not None:
            conditions.append("po.created_at::date <= :date_to")
            params["date_to"] = date_to

        order_filter = " AND ".join(conditions)

        rows = _rows(
            db,
            f"""
            WITH ordered_totals AS (
                SELECT
                    line.purchase_order_id,
                    SUM(
                        line.ordered_quantity
                    ) AS ordered_quantity
                FROM purchase_order_lines line
                GROUP BY line.purchase_order_id
            ),
            received_totals AS (
                SELECT
                    line.purchase_order_id,
                    SUM(
                        receipt_item.accepted_quantity
                    ) AS received_quantity
                FROM goods_receipt_items receipt_item
                JOIN goods_receipt_notes receipt_note
                  ON receipt_note.id
                     = receipt_item.goods_receipt_note_id
                JOIN purchase_phase_allocations allocation
                  ON allocation.id
                     = receipt_item.purchase_phase_allocation_id
                JOIN purchase_order_lines line
                  ON line.id
                     = allocation.purchase_order_line_id
                WHERE receipt_note.status = 'posted'
                GROUP BY line.purchase_order_id
            )
            SELECT
                po.reference_number AS label,
                COALESCE(
                    ordered_totals.ordered_quantity,
                    0
                ) AS ordered_quantity,
                COALESCE(
                    received_totals.received_quantity,
                    0
                ) AS received_quantity
            FROM purchase_orders po
            LEFT JOIN ordered_totals
              ON ordered_totals.purchase_order_id
                 = po.id
            LEFT JOIN received_totals
              ON received_totals.purchase_order_id
                 = po.id
            WHERE {order_filter}
            ORDER BY po.reference_number ASC
            """,
            params,
        )

        ordered = [
            _decimal(row["ordered_quantity"])
            for row in rows
        ]
        received = [
            _decimal(row["received_quantity"])
            for row in rows
        ]

        return {
            "chart_type": "bar",
            "x": [str(row["label"]) for row in rows],
            "series": [
                {
                    "name": "Ordered Quantity",
                    "data": ordered,
                },
                {
                    "name": "Received Quantity",
                    "data": received,
                },
                {
                    "name": "Outstanding Quantity",
                    "data": [
                        max(order_value - received_value, ZERO)
                        for order_value, received_value in zip(
                            ordered,
                            received,
                        )
                    ],
                },
            ],
            "unit": "units",
            "metadata": {
                "group_by": normalized_group_by,
                "date_basis": "purchase_order_created_at",
            },
        }

    raise ReportingNotFoundError("Unknown purchase report")
