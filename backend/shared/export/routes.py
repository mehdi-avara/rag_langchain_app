from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from Models import User
from db.init_db import get_db
from deps import require_permission

from .schemas import ExportRequest, ExportTaskOut
from .services import queue_export


router = APIRouter(tags=["exports"])


@router.post(
    "/supplier_management/suppliers/export",
    response_model=ExportTaskOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def export_suppliers(
    payload: ExportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("supplier_management:read")
    ),
    _export_permission: User = Depends(
        require_permission("supplier_management:export")
    ),
):
    return queue_export(
        db,
        current_user,
        "supplier_management",
        "suppliers",
        payload,
    )


@router.post(
    "/materials/items/export",
    response_model=ExportTaskOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def export_material_items(
    payload: ExportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("material_management:read")
    ),
    _export_permission: User = Depends(
        require_permission("material_management:export")
    ),
):
    return queue_export(
        db,
        current_user,
        "material_management",
        "items",
        payload,
    )


@router.post(
    "/requisitions/export",
    response_model=ExportTaskOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def export_requisitions(
    payload: ExportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("requisition_management:read")
    ),
    _export_permission: User = Depends(
        require_permission("requisition_management:export")
    ),
):
    return queue_export(
        db,
        current_user,
        "requisition_management",
        "requisitions",
        payload,
    )


@router.post(
    "/rfqs/export",
    response_model=ExportTaskOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def export_rfqs(
    payload: ExportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("rfq_management:read")
    ),
    _export_permission: User = Depends(
        require_permission("rfq_management:export")
    ),
):
    return queue_export(
        db,
        current_user,
        "rfq_management",
        "rfqs",
        payload,
    )


@router.post(
    "/goods-receipts/export",
    response_model=ExportTaskOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def export_goods_receipts(
    payload: ExportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("goods_receipt_management:read")
    ),
    _export_permission: User = Depends(
        require_permission("goods_receipt_management:export")
    ),
):
    return queue_export(
        db,
        current_user,
        "goods_receipt_management",
        "goods_receipts",
        payload,
    )


@router.post(
    "/warehouse/stock/export",
    response_model=ExportTaskOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def export_warehouse_stock(
    payload: ExportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:stock:read")
    ),
    _export_permission: User = Depends(
        require_permission("warehouse_management:export")
    ),
):
    return queue_export(
        db,
        current_user,
        "warehouse_management",
        "stock",
        payload,
    )


@router.post(
    "/warehouse/movements/export",
    response_model=ExportTaskOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def export_warehouse_movements(
    payload: ExportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:movements:read")
    ),
    _export_permission: User = Depends(
        require_permission("warehouse_management:export")
    ),
):
    return queue_export(
        db,
        current_user,
        "warehouse_management",
        "movements",
        payload,
    )


@router.post(
    "/purchase/orders/export",
    response_model=ExportTaskOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def export_purchase_orders(
    payload: ExportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("purchase_management:orders:read")
    ),
    _export_permission: User = Depends(
        require_permission("purchase_management:export")
    ),
):
    return queue_export(
        db,
        current_user,
        "purchase_management",
        "orders",
        payload,
    )
