from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy.orm import Session

from Models import User
from goods_receipt_management.services import (
    list_goods_receipts,
    search_goods_receipts,
)
from material_management.services import list_items
from purchase_management.services import export_purchase_order_rows
from requisition_management.services import (
    list_requisitions,
    search_requisitions,
)
from rfq_management.services import list_rfqs, search_rfqs
from supplier_management.services import list_suppliers
from warehouse_management.services import (
    export_stock_movement_rows,
    export_stock_rows,
)


MAX_EXPORT_ROWS = 10000


class ExportValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ExportDataset:
    module: str
    entity: str
    title: str
    columns: tuple[tuple[str, str], ...]
    fetcher: Callable[[Session, User, dict[str, Any]], list[dict[str, Any]]]


def _company_id(current_user: User) -> int:
    company_id = getattr(current_user, "company_id", None)

    if company_id is None:
        raise ExportValidationError("Current user does not belong to a company")

    return int(company_id)


def _text(value: Any, key: str) -> str | None:
    if value is None:
        return None

    normalized = str(value).strip()

    if not normalized:
        return None

    if len(normalized) > 255:
        raise ExportValidationError(f"{key} is too long")

    return normalized


def _positive_int(value: Any, key: str) -> int | None:
    if value is None or value == "":
        return None

    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ExportValidationError(f"{key} must be an integer") from exc

    if parsed <= 0:
        raise ExportValidationError(f"{key} must be greater than zero")

    return parsed


def _boolean(value: Any, key: str) -> bool | None:
    if value is None or value == "":
        return None

    if isinstance(value, bool):
        return value

    normalized = str(value).strip().lower()

    if normalized in {"true", "1", "yes"}:
        return True

    if normalized in {"false", "0", "no"}:
        return False

    raise ExportValidationError(f"{key} must be true or false")


def _date_value(value: Any, key: str) -> str | None:
    if value is None or value == "":
        return None

    if isinstance(value, datetime):
        return value.date().isoformat()

    if isinstance(value, date):
        return value.isoformat()

    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise ExportValidationError(f"{key} must use YYYY-MM-DD") from exc


def _limit(value: Any) -> int:
    if value is None or value == "":
        return MAX_EXPORT_ROWS

    parsed = _positive_int(value, "limit")

    if parsed is None:
        return MAX_EXPORT_ROWS

    if parsed > MAX_EXPORT_ROWS:
        raise ExportValidationError(
            f"limit cannot exceed {MAX_EXPORT_ROWS}"
        )

    return parsed


def _unknown_filters(filters: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(filters) - allowed)

    if unknown:
        raise ExportValidationError(
            "Unsupported filters: " + ", ".join(unknown)
        )


def _reject_query_filter_mix(
    filters: dict[str, Any],
    incompatible_fields: tuple[str, ...],
) -> None:
    query = _text(filters.get("query"), "query")

    if query is None:
        return

    supplied = [
        field
        for field in incompatible_fields
        if filters.get(field) not in (None, "")
    ]

    if supplied:
        raise ExportValidationError(
            "query cannot be combined with: " + ", ".join(supplied)
        )


def _normalize_supplier_filters(filters: dict[str, Any]) -> dict[str, Any]:
    _unknown_filters(
        filters,
        {"query", "status", "supplier_type", "limit"},
    )

    return {
        "query": _text(filters.get("query"), "query"),
        "status": _text(filters.get("status"), "status"),
        "supplier_type": _text(filters.get("supplier_type"), "supplier_type"),
        "limit": _limit(filters.get("limit")),
    }


def _normalize_material_filters(filters: dict[str, Any]) -> dict[str, Any]:
    _unknown_filters(
        filters,
        {"query", "category_id", "item_type", "is_active", "limit"},
    )

    return {
        "query": _text(filters.get("query"), "query"),
        "category_id": _positive_int(filters.get("category_id"), "category_id"),
        "item_type": _text(filters.get("item_type"), "item_type"),
        "is_active": _boolean(filters.get("is_active"), "is_active"),
        "limit": _limit(filters.get("limit")),
    }


def _normalize_requisition_filters(filters: dict[str, Any]) -> dict[str, Any]:
    _unknown_filters(
        filters,
        {
            "query",
            "status",
            "priority",
            "requested_by_user_id",
            "department_id",
            "limit",
        },
    )
    _reject_query_filter_mix(
        filters,
        (
            "status",
            "priority",
            "requested_by_user_id",
            "department_id",
        ),
    )

    return {
        "query": _text(filters.get("query"), "query"),
        "status": _text(filters.get("status"), "status"),
        "priority": _text(filters.get("priority"), "priority"),
        "requested_by_user_id": _positive_int(
            filters.get("requested_by_user_id"),
            "requested_by_user_id",
        ),
        "department_id": _positive_int(
            filters.get("department_id"),
            "department_id",
        ),
        "limit": _limit(filters.get("limit")),
    }


def _normalize_rfq_filters(filters: dict[str, Any]) -> dict[str, Any]:
    _unknown_filters(filters, {"query", "status", "mr_id", "limit"})
    _reject_query_filter_mix(filters, ("status", "mr_id"))

    return {
        "query": _text(filters.get("query"), "query"),
        "status": _text(filters.get("status"), "status"),
        "mr_id": _positive_int(filters.get("mr_id"), "mr_id"),
        "limit": _limit(filters.get("limit")),
    }


def _normalize_grn_filters(filters: dict[str, Any]) -> dict[str, Any]:
    _unknown_filters(
        filters,
        {
            "query",
            "status",
            "purchase_order_id",
            "purchase_phase_id",
            "receipt_date_from",
            "receipt_date_to",
            "limit",
        },
    )
    _reject_query_filter_mix(
        filters,
        (
            "status",
            "purchase_order_id",
            "purchase_phase_id",
            "receipt_date_from",
            "receipt_date_to",
        ),
    )

    normalized = {
        "query": _text(filters.get("query"), "query"),
        "status": _text(filters.get("status"), "status"),
        "purchase_order_id": _positive_int(
            filters.get("purchase_order_id"),
            "purchase_order_id",
        ),
        "purchase_phase_id": _positive_int(
            filters.get("purchase_phase_id"),
            "purchase_phase_id",
        ),
        "receipt_date_from": _date_value(
            filters.get("receipt_date_from"),
            "receipt_date_from",
        ),
        "receipt_date_to": _date_value(
            filters.get("receipt_date_to"),
            "receipt_date_to",
        ),
        "limit": _limit(filters.get("limit")),
    }

    if (
        normalized["receipt_date_from"]
        and normalized["receipt_date_to"]
        and normalized["receipt_date_from"] > normalized["receipt_date_to"]
    ):
        raise ExportValidationError(
            "receipt_date_from cannot be after receipt_date_to"
        )

    return normalized


def _normalize_warehouse_stock_filters(filters: dict[str, Any]) -> dict[str, Any]:
    _unknown_filters(
        filters,
        {
            "query",
            "item_id",
            "warehouse_id",
            "storage_location_id",
            "low_stock_only",
            "limit",
        },
    )

    return {
        "query": _text(filters.get("query"), "query"),
        "item_id": _positive_int(filters.get("item_id"), "item_id"),
        "warehouse_id": _positive_int(
            filters.get("warehouse_id"),
            "warehouse_id",
        ),
        "storage_location_id": _positive_int(
            filters.get("storage_location_id"),
            "storage_location_id",
        ),
        "low_stock_only": _boolean(
            filters.get("low_stock_only"),
            "low_stock_only",
        )
        or False,
        "limit": _limit(filters.get("limit")),
    }


def _normalize_warehouse_movement_filters(filters: dict[str, Any]) -> dict[str, Any]:
    _unknown_filters(
        filters,
        {
            "item_id",
            "warehouse_id",
            "reference_type",
            "reference_id",
            "limit",
        },
    )

    return {
        "item_id": _positive_int(filters.get("item_id"), "item_id"),
        "warehouse_id": _positive_int(
            filters.get("warehouse_id"),
            "warehouse_id",
        ),
        "reference_type": _text(
            filters.get("reference_type"),
            "reference_type",
        ),
        "reference_id": _positive_int(
            filters.get("reference_id"),
            "reference_id",
        ),
        "limit": _limit(filters.get("limit")),
    }


def _normalize_purchase_filters(filters: dict[str, Any]) -> dict[str, Any]:
    _unknown_filters(
        filters,
        {"query", "status", "approval_status", "limit"},
    )

    return {
        "query": _text(filters.get("query"), "query"),
        "status": _text(filters.get("status"), "status"),
        "approval_status": _text(
            filters.get("approval_status"),
            "approval_status",
        ),
        "limit": _limit(filters.get("limit")),
    }


def _as_decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def _fetch_suppliers(
    db: Session,
    current_user: User,
    filters: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = list_suppliers(
        db=db,
        current_user=current_user,
        query_text=filters["query"],
        supplier_status=filters["status"],
        supplier_type=filters["supplier_type"],
        limit=filters["limit"],
        offset=0,
    )

    return [
        {
            "code": row.code,
            "name": row.name,
            "supplier_type": row.supplier_type,
            "status": row.status,
            "country": row.country,
            "city": row.city,
            "tax_id": row.tax_id,
            "website": row.website,
            "created_at": row.created_at,
        }
        for row in rows
    ]


def _fetch_material_items(
    db: Session,
    current_user: User,
    filters: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = list_items(
        db=db,
        current_user=current_user,
        query_text=filters["query"],
        category_id=filters["category_id"],
        item_type=filters["item_type"],
        is_active=filters["is_active"],
        limit=filters["limit"],
        offset=0,
    )

    return [
        {
            "item_code": row.item_code,
            "name": row.name,
            "category_code": row.category.code if row.category else None,
            "category_name": row.category.name if row.category else None,
            "unit_code": row.unit.code if row.unit else None,
            "item_type": row.item_type,
            "is_active": row.is_active,
            "is_critical": row.is_critical,
            "lead_time_days": row.lead_time_days,
            "created_at": row.created_at,
        }
        for row in rows
    ]


def _fetch_requisitions(
    db: Session,
    current_user: User,
    filters: dict[str, Any],
) -> list[dict[str, Any]]:
    if filters["query"]:
        rows = search_requisitions(
            db=db,
            current_user=current_user,
            query_text=filters["query"],
            page=1,
            size=filters["limit"],
        )
    else:
        rows = list_requisitions(
            db=db,
            current_user=current_user,
            requisition_status=filters["status"],
            priority=filters["priority"],
            requested_by_user_id=filters["requested_by_user_id"],
            department_id=filters["department_id"],
            page=1,
            size=filters["limit"],
        )

    return [
        {
            "mr_number": row.mr_number,
            "status": row.status,
            "priority": row.priority,
            "requested_by_user_id": row.requested_by_user_id,
            "department_id": row.department_id,
            "legacy_department_id": row.legacy_department_id,
            "needed_by_date": row.needed_by_date,
            "reason": row.reason,
            "item_count": len(row.items or []),
            "requested_quantity": sum(
                (_as_decimal(item.quantity) for item in row.items or []),
                Decimal("0"),
            ),
            "created_at": row.created_at,
        }
        for row in rows
    ]


def _fetch_rfqs(
    db: Session,
    current_user: User,
    filters: dict[str, Any],
) -> list[dict[str, Any]]:
    if filters["query"]:
        rows = search_rfqs(
            db=db,
            current_user=current_user,
            query_text=filters["query"],
            page=1,
            size=filters["limit"],
        )
    else:
        rows = list_rfqs(
            db=db,
            current_user=current_user,
            rfq_status=filters["status"],
            mr_id=filters["mr_id"],
            page=1,
            size=filters["limit"],
        )

    return [
        {
            "rfq_number": row.rfq_number,
            "title": row.title,
            "status": row.status,
            "mr_id": row.mr_id,
            "deadline_date": row.deadline_date,
            "supplier_count": len(row.suppliers or []),
            "item_count": len(row.items or []),
            "response_count": len(row.responses or []),
            "created_at": row.created_at,
        }
        for row in rows
    ]


def _fetch_goods_receipts(
    db: Session,
    current_user: User,
    filters: dict[str, Any],
) -> list[dict[str, Any]]:
    date_from = (
        date.fromisoformat(filters["receipt_date_from"])
        if filters["receipt_date_from"]
        else None
    )
    date_to = (
        date.fromisoformat(filters["receipt_date_to"])
        if filters["receipt_date_to"]
        else None
    )

    if filters["query"]:
        rows = search_goods_receipts(
            db=db,
            current_user=current_user,
            query_text=filters["query"],
            page=1,
            size=filters["limit"],
        )
    else:
        rows = list_goods_receipts(
            db=db,
            current_user=current_user,
            goods_receipt_status=filters["status"],
            purchase_order_id=filters["purchase_order_id"],
            purchase_phase_id=filters["purchase_phase_id"],
            receipt_date_from=date_from,
            receipt_date_to=date_to,
            page=1,
            size=filters["limit"],
        )

    return [
        {
            "grn_number": row.grn_number,
            "status": row.status,
            "receipt_date": row.receipt_date,
            "purchase_order_id": row.purchase_order_id,
            "purchase_phase_id": row.purchase_phase_id,
            "warehouse_id": row.warehouse_id,
            "delivery_note_number": row.delivery_note_number,
            "item_count": len(row.items or []),
            "accepted_quantity": sum(
                (_as_decimal(item.accepted_quantity) for item in row.items or []),
                Decimal("0"),
            ),
            "rejected_quantity": sum(
                (_as_decimal(item.rejected_quantity) for item in row.items or []),
                Decimal("0"),
            ),
            "accepted_value_base": sum(
                (
                    _as_decimal(item.accepted_quantity)
                    * _as_decimal(item.unit_cost_base)
                    for item in row.items or []
                ),
                Decimal("0"),
            ),
            "created_at": row.created_at,
        }
        for row in rows
    ]


def _fetch_warehouse_stock(
    db: Session,
    current_user: User,
    filters: dict[str, Any],
) -> list[dict[str, Any]]:
    return export_stock_rows(
        db=db,
        current_user=current_user,
        query_text=filters["query"],
        item_id=filters["item_id"],
        warehouse_id=filters["warehouse_id"],
        storage_location_id=filters["storage_location_id"],
        low_stock_only=filters["low_stock_only"],
        limit=filters["limit"],
    )


def _fetch_warehouse_movements(
    db: Session,
    current_user: User,
    filters: dict[str, Any],
) -> list[dict[str, Any]]:
    return export_stock_movement_rows(
        db=db,
        current_user=current_user,
        item_id=filters["item_id"],
        warehouse_id=filters["warehouse_id"],
        reference_type=filters["reference_type"],
        reference_id=filters["reference_id"],
        limit=filters["limit"],
    )


def _fetch_purchase_orders(
    db: Session,
    current_user: User,
    filters: dict[str, Any],
) -> list[dict[str, Any]]:
    return export_purchase_order_rows(
        db=db,
        current_user=current_user,
        query_text=filters["query"],
        po_status=filters["status"],
        approval_status=filters["approval_status"],
        limit=filters["limit"],
    )


DATASETS: dict[tuple[str, str], ExportDataset] = {
    (
        "supplier_management",
        "suppliers",
    ): ExportDataset(
        module="supplier_management",
        entity="suppliers",
        title="Suppliers",
        columns=(
            ("code", "Code"),
            ("name", "Name"),
            ("supplier_type", "Type"),
            ("status", "Status"),
            ("country", "Country"),
            ("city", "City"),
            ("tax_id", "Tax ID"),
            ("website", "Website"),
            ("created_at", "Created At"),
        ),
        fetcher=_fetch_suppliers,
    ),
    (
        "material_management",
        "items",
    ): ExportDataset(
        module="material_management",
        entity="items",
        title="Material Items",
        columns=(
            ("item_code", "Item Code"),
            ("name", "Name"),
            ("category_code", "Category Code"),
            ("category_name", "Category"),
            ("unit_code", "Unit"),
            ("item_type", "Item Type"),
            ("is_active", "Active"),
            ("is_critical", "Critical"),
            ("lead_time_days", "Lead Time Days"),
            ("created_at", "Created At"),
        ),
        fetcher=_fetch_material_items,
    ),
    (
        "requisition_management",
        "requisitions",
    ): ExportDataset(
        module="requisition_management",
        entity="requisitions",
        title="Material Requisitions",
        columns=(
            ("mr_number", "MR Number"),
            ("status", "Status"),
            ("priority", "Priority"),
            ("requested_by_user_id", "Requester ID"),
            ("department_id", "Department ID"),
            ("legacy_department_id", "Legacy Department ID"),
            ("needed_by_date", "Needed By"),
            ("reason", "Reason"),
            ("item_count", "Item Count"),
            ("requested_quantity", "Requested Quantity"),
            ("created_at", "Created At"),
        ),
        fetcher=_fetch_requisitions,
    ),
    (
        "rfq_management",
        "rfqs",
    ): ExportDataset(
        module="rfq_management",
        entity="rfqs",
        title="Requests for Quotation",
        columns=(
            ("rfq_number", "RFQ Number"),
            ("title", "Title"),
            ("status", "Status"),
            ("mr_id", "MR ID"),
            ("deadline_date", "Deadline"),
            ("supplier_count", "Supplier Count"),
            ("item_count", "Item Count"),
            ("response_count", "Response Count"),
            ("created_at", "Created At"),
        ),
        fetcher=_fetch_rfqs,
    ),
    (
        "goods_receipt_management",
        "goods_receipts",
    ): ExportDataset(
        module="goods_receipt_management",
        entity="goods_receipts",
        title="Goods Receipt Notes",
        columns=(
            ("grn_number", "GRN Number"),
            ("status", "Status"),
            ("receipt_date", "Receipt Date"),
            ("purchase_order_id", "Purchase Order ID"),
            ("purchase_phase_id", "Purchase Phase ID"),
            ("warehouse_id", "Warehouse ID"),
            ("delivery_note_number", "Delivery Note"),
            ("item_count", "Item Count"),
            ("accepted_quantity", "Accepted Quantity"),
            ("rejected_quantity", "Rejected Quantity"),
            ("accepted_value_base", "Accepted Value Base"),
            ("created_at", "Created At"),
        ),
        fetcher=_fetch_goods_receipts,
    ),
    (
        "warehouse_management",
        "stock",
    ): ExportDataset(
        module="warehouse_management",
        entity="stock",
        title="Warehouse Stock",
        columns=(
            ("warehouse_code", "Warehouse Code"),
            ("warehouse_name", "Warehouse"),
            ("zone_code", "Zone"),
            ("storage_location_code", "Storage Location"),
            ("item_code", "Item Code"),
            ("item_name", "Item Name"),
            ("quantity_on_hand", "Quantity On Hand"),
            ("quantity_reserved", "Quantity Reserved"),
            ("quantity_available", "Quantity Available"),
            ("reorder_point", "Reorder Point"),
            ("unit_cost_base", "Unit Cost Base"),
            ("inventory_value_base", "Inventory Value Base"),
            ("low_stock", "Low Stock"),
            ("updated_at", "Updated At"),
        ),
        fetcher=_fetch_warehouse_stock,
    ),
    (
        "warehouse_management",
        "movements",
    ): ExportDataset(
        module="warehouse_management",
        entity="movements",
        title="Warehouse Movements",
        columns=(
            ("movement_number", "Movement Number"),
            ("movement_type", "Movement Type"),
            ("item_id", "Item ID"),
            ("quantity", "Quantity"),
            ("unit_cost_base", "Unit Cost Base"),
            ("movement_value_base", "Movement Value Base"),
            ("reference_type", "Reference Type"),
            ("reference_id", "Reference ID"),
            ("movement_date", "Movement Date"),
            ("notes", "Notes"),
        ),
        fetcher=_fetch_warehouse_movements,
    ),
    (
        "purchase_management",
        "orders",
    ): ExportDataset(
        module="purchase_management",
        entity="orders",
        title="Purchase Orders",
        columns=(
            ("reference_number", "PO Number"),
            ("title", "Title"),
            ("supplier_name", "Supplier"),
            ("status", "Status"),
            ("approval_status", "Approval Status"),
            ("rfq_id", "RFQ ID"),
            ("phase_count", "Phase Count"),
            ("item_count", "Item Count"),
            ("total_in_base", "Total Base"),
            ("additional_costs_base", "Additional Costs Base"),
            ("grand_total_base", "Grand Total Base"),
            ("created_at", "Created At"),
        ),
        fetcher=_fetch_purchase_orders,
    ),
}


NORMALIZERS: dict[tuple[str, str], Callable[[dict[str, Any]], dict[str, Any]]] = {
    ("supplier_management", "suppliers"): _normalize_supplier_filters,
    ("material_management", "items"): _normalize_material_filters,
    ("requisition_management", "requisitions"): _normalize_requisition_filters,
    ("rfq_management", "rfqs"): _normalize_rfq_filters,
    ("goods_receipt_management", "goods_receipts"): _normalize_grn_filters,
    ("warehouse_management", "stock"): _normalize_warehouse_stock_filters,
    ("warehouse_management", "movements"): _normalize_warehouse_movement_filters,
    ("purchase_management", "orders"): _normalize_purchase_filters,
}


def get_dataset(module: str, entity: str) -> ExportDataset:
    dataset = DATASETS.get((module, entity))

    if dataset is None:
        raise ExportValidationError("Unsupported export dataset")

    return dataset


def normalize_filters(
    module: str,
    entity: str,
    filters: dict[str, Any] | None,
) -> dict[str, Any]:
    if filters is None:
        filters = {}

    if not isinstance(filters, dict):
        raise ExportValidationError("filters must be an object")

    normalizer = NORMALIZERS.get((module, entity))

    if normalizer is None:
        raise ExportValidationError("Unsupported export dataset")

    return normalizer(filters)


def resolve_columns(
    module: str,
    entity: str,
    requested_columns: list[str] | None,
) -> list[str]:
    dataset = get_dataset(module, entity)
    allowed_columns = {key for key, _ in dataset.columns}

    if not requested_columns:
        return [key for key, _ in dataset.columns]

    unknown = sorted(set(requested_columns) - allowed_columns)

    if unknown:
        raise ExportValidationError(
            "Unsupported columns: " + ", ".join(unknown)
        )

    return requested_columns


def column_labels(
    module: str,
    entity: str,
    columns: list[str],
) -> dict[str, str]:
    dataset = get_dataset(module, entity)
    labels = dict(dataset.columns)

    return {column: labels[column] for column in columns}


def fetch_export_rows(
    db: Session,
    current_user: User,
    module: str,
    entity: str,
    filters: dict[str, Any],
) -> list[dict[str, Any]]:
    dataset = get_dataset(module, entity)
    normalized_filters = normalize_filters(module, entity, filters)

    return dataset.fetcher(db, current_user, normalized_filters)
