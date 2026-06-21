from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from Models import User
from db.init_db import get_db
from deps import require_permission

from ..schemas import (
    StockCountCreate,
    StockCountLineCreate,
    StockCountLineRead,
    StockCountLineUpdate,
    StockCountRead,
    StockItemRead,
    StockItemSearchRead,
    StockMovementCreate,
    StockMovementRead,
    StockThresholdUpdate,
    StorageLocationCreate,
    StorageLocationRead,
    StorageLocationUpdate,
    WarehouseCreate,
    WarehouseRead,
    WarehouseSearchRequest,
    WarehouseSummaryRead,
    WarehouseUpdate,
    ZoneCreate,
    ZoneRead,
    ZoneUpdate,
)
from ..services import (
    add_stock_count_line,
    create_manual_stock_movement,
    create_stock_count,
    create_storage_location,
    create_warehouse,
    create_zone,
    get_low_stock_items,
    get_stock_count_or_404,
    get_warehouse_or_404,
    list_stock_count_lines,
    list_stock_counts,
    list_stock_items,
    list_stock_movements,
    list_storage_locations,
    list_warehouses,
    list_zones,
    post_stock_count,
    search_stock_items,
    start_stock_count,
    update_stock_count_line,
    update_stock_thresholds,
    update_storage_location,
    update_warehouse,
    update_zone,
    warehouse_summary,
)


router = APIRouter(prefix="/warehouse")


@router.post(
    "",
    response_model=WarehouseRead,
    status_code=status.HTTP_201_CREATED,
)
def create_warehouse_endpoint(
    payload: WarehouseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:locations:manage")
    ),
):
    return create_warehouse(
        db=db,
        current_user=current_user,
        data=payload.model_dump(),
    )


@router.get("", response_model=list[WarehouseRead])
def list_warehouses_endpoint(
    active_only: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:locations:read")
    ),
):
    return list_warehouses(
        db=db,
        current_user=current_user,
        active_only=active_only,
    )


@router.get("/warehouses/{warehouse_id}", response_model=WarehouseRead)
def get_warehouse_endpoint(
    warehouse_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:locations:read")
    ),
):
    return get_warehouse_or_404(
        db=db,
        current_user=current_user,
        warehouse_id=warehouse_id,
    )


@router.patch("/warehouses/{warehouse_id}", response_model=WarehouseRead)
def update_warehouse_endpoint(
    warehouse_id: int,
    payload: WarehouseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:locations:manage")
    ),
):
    return update_warehouse(
        db=db,
        current_user=current_user,
        warehouse_id=warehouse_id,
        data=payload.model_dump(exclude_unset=True),
    )


@router.post(
    "/warehouses/{warehouse_id}/zones",
    response_model=ZoneRead,
    status_code=status.HTTP_201_CREATED,
)
def create_zone_endpoint(
    warehouse_id: int,
    payload: ZoneCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:locations:manage")
    ),
):
    return create_zone(
        db=db,
        current_user=current_user,
        warehouse_id=warehouse_id,
        data=payload.model_dump(),
    )


@router.get("/warehouses/{warehouse_id}/zones", response_model=list[ZoneRead])
def list_zones_endpoint(
    warehouse_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:locations:read")
    ),
):
    return list_zones(
        db=db,
        current_user=current_user,
        warehouse_id=warehouse_id,
    )


@router.patch("/zones/{zone_id}", response_model=ZoneRead)
def update_zone_endpoint(
    zone_id: int,
    payload: ZoneUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:locations:manage")
    ),
):
    return update_zone(
        db=db,
        current_user=current_user,
        zone_id=zone_id,
        data=payload.model_dump(exclude_unset=True),
    )


@router.post(
    "/locations",
    response_model=StorageLocationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_storage_location_endpoint(
    payload: StorageLocationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:locations:manage")
    ),
):
    return create_storage_location(
        db=db,
        current_user=current_user,
        data=payload.model_dump(),
    )


@router.get("/locations/list", response_model=list[StorageLocationRead])
def list_storage_locations_endpoint(
    warehouse_id: Optional[int] = Query(None, gt=0),
    zone_id: Optional[int] = Query(None, gt=0),
    active_only: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:locations:read")
    ),
):
    return list_storage_locations(
        db=db,
        current_user=current_user,
        warehouse_id=warehouse_id,
        zone_id=zone_id,
        active_only=active_only,
    )


@router.patch(
    "/locations/{storage_location_id}",
    response_model=StorageLocationRead,
)
def update_storage_location_endpoint(
    storage_location_id: int,
    payload: StorageLocationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:locations:manage")
    ),
):
    return update_storage_location(
        db=db,
        current_user=current_user,
        storage_location_id=storage_location_id,
        data=payload.model_dump(exclude_unset=True),
    )


@router.get("/stock/list", response_model=list[StockItemRead])
def list_stock_items_endpoint(
    item_id: Optional[int] = Query(None, gt=0),
    warehouse_id: Optional[int] = Query(None, gt=0),
    storage_location_id: Optional[int] = Query(None, gt=0),
    low_stock_only: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:stock:read")
    ),
):
    return list_stock_items(
        db=db,
        current_user=current_user,
        item_id=item_id,
        warehouse_id=warehouse_id,
        storage_location_id=storage_location_id,
        low_stock_only=low_stock_only,
    )


@router.patch(
    "/stock/{stock_item_id}/thresholds",
    response_model=StockItemRead,
)
def update_stock_thresholds_endpoint(
    stock_item_id: int,
    payload: StockThresholdUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:stock:manage")
    ),
):
    return update_stock_thresholds(
        db=db,
        current_user=current_user,
        stock_item_id=stock_item_id,
        data=payload.model_dump(exclude_unset=True),
    )


@router.get("/stock/low", response_model=list[StockItemRead])
def get_low_stock_items_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:stock:read")
    ),
):
    return get_low_stock_items(
        db=db,
        current_user=current_user,
    )


@router.post(
    "/movements",
    response_model=StockMovementRead,
    status_code=status.HTTP_201_CREATED,
)
def create_stock_movement_endpoint(
    payload: StockMovementCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:movements:create")
    ),
):
    return create_manual_stock_movement(
        db=db,
        current_user=current_user,
        data=payload.model_dump(),
    )


@router.get("/movements/list", response_model=list[StockMovementRead])
def list_stock_movements_endpoint(
    item_id: Optional[int] = Query(None, gt=0),
    warehouse_id: Optional[int] = Query(None, gt=0),
    reference_type: Optional[str] = Query(None),
    reference_id: Optional[int] = Query(None, gt=0),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:movements:read")
    ),
):
    return list_stock_movements(
        db=db,
        current_user=current_user,
        item_id=item_id,
        warehouse_id=warehouse_id,
        reference_type=reference_type,
        reference_id=reference_id,
        page=page,
        size=size,
    )


@router.post(
    "/stock-counts",
    response_model=StockCountRead,
    status_code=status.HTTP_201_CREATED,
)
def create_stock_count_endpoint(
    payload: StockCountCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:stock:manage")
    ),
):
    return create_stock_count(
        db=db,
        current_user=current_user,
        warehouse_id=payload.warehouse_id,
        notes=payload.notes,
    )


@router.get("/stock-counts", response_model=list[StockCountRead])
def list_stock_counts_endpoint(
    warehouse_id: Optional[int] = Query(None, gt=0),
    stock_count_status: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:stock:read")
    ),
):
    return list_stock_counts(
        db=db,
        current_user=current_user,
        warehouse_id=warehouse_id,
        stock_count_status=stock_count_status,
    )


@router.get("/stock-counts/{stock_count_id}", response_model=StockCountRead)
def get_stock_count_endpoint(
    stock_count_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:stock:read")
    ),
):
    return get_stock_count_or_404(
        db=db,
        current_user=current_user,
        stock_count_id=stock_count_id,
    )


@router.post("/stock-counts/{stock_count_id}/start", response_model=StockCountRead)
def start_stock_count_endpoint(
    stock_count_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:stock:manage")
    ),
):
    return start_stock_count(
        db=db,
        current_user=current_user,
        stock_count_id=stock_count_id,
    )


@router.get(
    "/stock-counts/{stock_count_id}/lines",
    response_model=list[StockCountLineRead],
)
def list_stock_count_lines_endpoint(
    stock_count_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:stock:read")
    ),
):
    return list_stock_count_lines(
        db=db,
        current_user=current_user,
        stock_count_id=stock_count_id,
    )


@router.post(
    "/stock-counts/{stock_count_id}/lines",
    response_model=StockCountLineRead,
    status_code=status.HTTP_201_CREATED,
)
def add_stock_count_line_endpoint(
    stock_count_id: int,
    payload: StockCountLineCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:stock:manage")
    ),
):
    return add_stock_count_line(
        db=db,
        current_user=current_user,
        stock_count_id=stock_count_id,
        data=payload.model_dump(),
    )


@router.patch(
    "/stock-counts/{stock_count_id}/lines/{stock_count_line_id}",
    response_model=StockCountLineRead,
)
def update_stock_count_line_endpoint(
    stock_count_id: int,
    stock_count_line_id: int,
    payload: StockCountLineUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:stock:manage")
    ),
):
    return update_stock_count_line(
        db=db,
        current_user=current_user,
        stock_count_id=stock_count_id,
        stock_count_line_id=stock_count_line_id,
        counted_quantity=payload.counted_quantity,
    )


@router.post("/stock-counts/{stock_count_id}/post", response_model=StockCountRead)
def post_stock_count_endpoint(
    stock_count_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:stock:manage")
    ),
):
    return post_stock_count(
        db=db,
        current_user=current_user,
        stock_count_id=stock_count_id,
    )


@router.post("/items/search", response_model=list[StockItemSearchRead])
@router.post("/search", response_model=list[StockItemSearchRead])
def search_stock_items_endpoint(
    payload: WarehouseSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:search")
    ),
):
    return search_stock_items(
        db=db,
        current_user=current_user,
        query_text=payload.query,
        item_ids=payload.item_ids,
        warehouse_id=payload.warehouse_id,
        storage_location_id=payload.storage_location_id,
        limit=payload.limit,
        offset=payload.offset,
    )


@router.get("/summary", response_model=WarehouseSummaryRead)
def warehouse_summary_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:summary")
    ),
):
    return warehouse_summary(
        db=db,
        current_user=current_user,
    )
