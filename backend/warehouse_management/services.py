from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import func, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from Models.company import Company
from Models.user import User
from core.exceptions.error_codes import (
    STOCK_COUNT_INCOMPLETE,
    STOCK_COUNT_LINE_NOT_FOUND,
    STOCK_COUNT_NOT_EDITABLE,
    STOCK_COUNT_NOT_FOUND,
    STOCK_COUNT_NOT_POSTABLE,
    STOCK_INSUFFICIENT,
    STOCK_ITEM_NOT_FOUND,
    STOCK_MOVEMENT_INVALID,
    STORAGE_LOCATION_INACTIVE,
    STORAGE_LOCATION_NOT_FOUND,
    STORAGE_LOCATION_WAREHOUSE_MISMATCH,
    USER_HAS_NO_COMPANY,
    WAREHOUSE_BASE_CURRENCY_NOT_FOUND,
    WAREHOUSE_DEFAULT_CANNOT_DEACTIVATE,
    WAREHOUSE_INACTIVE,
    WAREHOUSE_MANAGER_INVALID,
    WAREHOUSE_NOT_FOUND,
    WAREHOUSE_ZONE_NOT_FOUND,
)
from shared.currency.models import Currency

from .models import (
    StockCount,
    StockCountLine,
    StockCountStatus,
    StockItem,
    StockMovement,
    StockMovementType,
    StockReferenceType,
    StorageLocation,
    Warehouse,
    WarehouseType,
    Zone,
)


ZERO = Decimal("0")


def raise_error(status_code: int, code: str, message: str) -> None:
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def decimal_value(value: Any) -> Decimal:
    return Decimal(str(value)) if value is not None else ZERO


def tenant_id(current_user: User) -> int:
    if current_user.company_id is None:
        raise_error(
            status.HTTP_403_FORBIDDEN,
            USER_HAS_NO_COMPANY,
            "Current user does not belong to a company",
        )

    return current_user.company_id


def get_company_base_currency_id(db: Session, company_id: int) -> int:
    company = db.query(Company).filter(Company.id == company_id).first()

    if company is None:
        raise_error(
            status.HTTP_404_NOT_FOUND,
            WAREHOUSE_NOT_FOUND,
            "Company not found",
        )

    if company.base_currency_id is not None:
        return company.base_currency_id

    currency = (
        db.query(Currency)
        .filter(Currency.code == company.base_currency)
        .first()
    )

    if currency is None:
        raise_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            WAREHOUSE_BASE_CURRENCY_NOT_FOUND,
            "Company base currency is not configured",
        )

    return currency.id


def get_warehouse_or_404(
    db: Session,
    current_user: User,
    warehouse_id: int,
    active_only: bool = False,
) -> Warehouse:
    query = db.query(Warehouse).filter(
        Warehouse.id == warehouse_id,
        Warehouse.company_id == tenant_id(current_user),
    )

    if active_only:
        query = query.filter(Warehouse.is_active.is_(True))

    warehouse = query.first()

    if warehouse is None:
        raise_error(
            status.HTTP_404_NOT_FOUND,
            WAREHOUSE_NOT_FOUND,
            "Warehouse not found",
        )

    return warehouse


def get_warehouse_by_company_or_404(
    db: Session,
    company_id: int,
    warehouse_id: int,
    active_only: bool = False,
) -> Warehouse:
    query = db.query(Warehouse).filter(
        Warehouse.id == warehouse_id,
        Warehouse.company_id == company_id,
    )

    if active_only:
        query = query.filter(Warehouse.is_active.is_(True))

    warehouse = query.first()

    if warehouse is None:
        raise_error(
            status.HTTP_404_NOT_FOUND,
            WAREHOUSE_NOT_FOUND,
            "Warehouse not found",
        )

    return warehouse


def get_zone_or_404(
    db: Session,
    current_user: User,
    zone_id: int,
) -> Zone:
    zone = (
        db.query(Zone)
        .join(Warehouse, Zone.warehouse_id == Warehouse.id)
        .filter(
            Zone.id == zone_id,
            Warehouse.company_id == tenant_id(current_user),
        )
        .first()
    )

    if zone is None:
        raise_error(
            status.HTTP_404_NOT_FOUND,
            WAREHOUSE_ZONE_NOT_FOUND,
            "Warehouse zone not found",
        )

    return zone


def get_storage_location_or_404(
    db: Session,
    current_user: User,
    storage_location_id: int,
    active_only: bool = False,
) -> StorageLocation:
    query = (
        db.query(StorageLocation)
        .join(Zone, StorageLocation.zone_id == Zone.id)
        .join(Warehouse, Zone.warehouse_id == Warehouse.id)
        .filter(
            StorageLocation.id == storage_location_id,
            Warehouse.company_id == tenant_id(current_user),
        )
    )

    if active_only:
        query = query.filter(StorageLocation.is_active.is_(True))

    location = query.first()

    if location is None:
        raise_error(
            status.HTTP_404_NOT_FOUND,
            STORAGE_LOCATION_NOT_FOUND,
            "Storage location not found",
        )

    return location


def get_storage_location_by_company_or_404(
    db: Session,
    company_id: int,
    storage_location_id: int,
    active_only: bool = False,
) -> tuple[StorageLocation, int]:
    query = (
        db.query(StorageLocation, Warehouse.id)
        .join(Zone, StorageLocation.zone_id == Zone.id)
        .join(Warehouse, Zone.warehouse_id == Warehouse.id)
        .filter(
            StorageLocation.id == storage_location_id,
            Warehouse.company_id == company_id,
        )
    )

    if active_only:
        query = query.filter(StorageLocation.is_active.is_(True))

    row = query.first()

    if row is None:
        raise_error(
            status.HTTP_404_NOT_FOUND,
            STORAGE_LOCATION_NOT_FOUND,
            "Storage location not found",
        )

    return row[0], row[1]


def validate_manager(
    db: Session,
    company_id: int,
    manager_id: Optional[int],
) -> None:
    if manager_id is None:
        return

    manager = (
        db.query(User)
        .filter(
            User.id == manager_id,
            User.company_id == company_id,
            User.is_active.is_(True),
        )
        .first()
    )

    if manager is None:
        raise_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            WAREHOUSE_MANAGER_INVALID,
            "Warehouse manager must be an active user in the same company",
        )


def create_warehouse(
    db: Session,
    current_user: User,
    data: dict[str, Any],
) -> Warehouse:
    company_id = tenant_id(current_user)
    validate_manager(db, company_id, data.get("manager_id"))

    has_existing = (
        db.query(Warehouse.id)
        .filter(Warehouse.company_id == company_id)
        .first()
        is not None
    )

    is_default = bool(data.get("is_default")) or not has_existing

    if is_default:
        (
            db.query(Warehouse)
            .filter(
                Warehouse.company_id == company_id,
                Warehouse.is_default.is_(True),
            )
            .update(
                {Warehouse.is_default: False},
                synchronize_session=False,
            )
        )

    warehouse = Warehouse(
        company_id=company_id,
        code=data["code"].strip().upper(),
        name=data["name"].strip(),
        warehouse_type=data.get(
            "warehouse_type",
            WarehouseType.MAIN.value,
        ),
        location=data.get("location"),
        address=data.get("address"),
        manager_id=data.get("manager_id"),
        is_active=data.get("is_active", True),
        is_default=is_default,
    )

    db.add(warehouse)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise_error(
            status.HTTP_409_CONFLICT,
            WAREHOUSE_NOT_FOUND,
            "Warehouse code already exists in this company",
        )

    db.refresh(warehouse)
    return warehouse


def list_warehouses(
    db: Session,
    current_user: User,
    active_only: bool = False,
) -> list[Warehouse]:
    query = db.query(Warehouse).filter(
        Warehouse.company_id == tenant_id(current_user)
    )

    if active_only:
        query = query.filter(Warehouse.is_active.is_(True))

    return query.order_by(
        Warehouse.is_default.desc(),
        Warehouse.code.asc(),
    ).all()


def update_warehouse(
    db: Session,
    current_user: User,
    warehouse_id: int,
    data: dict[str, Any],
) -> Warehouse:
    warehouse = get_warehouse_or_404(
        db=db,
        current_user=current_user,
        warehouse_id=warehouse_id,
    )

    company_id = tenant_id(current_user)
    validate_manager(
        db,
        company_id,
        data.get("manager_id", warehouse.manager_id),
    )

    if data.get("is_active") is False and warehouse.is_default:
        raise_error(
            status.HTTP_409_CONFLICT,
            WAREHOUSE_DEFAULT_CANNOT_DEACTIVATE,
            "The default warehouse cannot be deactivated",
        )

    if data.get("is_default") is True and not warehouse.is_default:
        (
            db.query(Warehouse)
            .filter(
                Warehouse.company_id == company_id,
                Warehouse.is_default.is_(True),
            )
            .update(
                {Warehouse.is_default: False},
                synchronize_session=False,
            )
        )

    for key, value in data.items():
        if key == "code" and value is not None:
            value = value.strip().upper()

        if key == "name" and value is not None:
            value = value.strip()

        setattr(warehouse, key, value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise_error(
            status.HTTP_409_CONFLICT,
            WAREHOUSE_NOT_FOUND,
            "Warehouse code already exists in this company",
        )

    db.refresh(warehouse)
    return warehouse


def create_zone(
    db: Session,
    current_user: User,
    warehouse_id: int,
    data: dict[str, Any],
) -> Zone:
    warehouse = get_warehouse_or_404(
        db=db,
        current_user=current_user,
        warehouse_id=warehouse_id,
        active_only=True,
    )

    zone = Zone(
        warehouse_id=warehouse.id,
        code=data["code"].strip().upper(),
        name=data["name"].strip(),
        description=data.get("description"),
    )

    db.add(zone)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise_error(
            status.HTTP_409_CONFLICT,
            WAREHOUSE_ZONE_NOT_FOUND,
            "Zone code already exists in this warehouse",
        )

    db.refresh(zone)
    return zone


def list_zones(
    db: Session,
    current_user: User,
    warehouse_id: int,
) -> list[Zone]:
    get_warehouse_or_404(
        db=db,
        current_user=current_user,
        warehouse_id=warehouse_id,
    )

    return (
        db.query(Zone)
        .filter(Zone.warehouse_id == warehouse_id)
        .order_by(Zone.code.asc())
        .all()
    )


def update_zone(
    db: Session,
    current_user: User,
    zone_id: int,
    data: dict[str, Any],
) -> Zone:
    zone = get_zone_or_404(
        db=db,
        current_user=current_user,
        zone_id=zone_id,
    )

    for key, value in data.items():
        if key == "code" and value is not None:
            value = value.strip().upper()

        if key == "name" and value is not None:
            value = value.strip()

        setattr(zone, key, value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise_error(
            status.HTTP_409_CONFLICT,
            WAREHOUSE_ZONE_NOT_FOUND,
            "Zone code already exists in this warehouse",
        )

    db.refresh(zone)
    return zone


def create_storage_location(
    db: Session,
    current_user: User,
    data: dict[str, Any],
) -> StorageLocation:
    zone = get_zone_or_404(
        db=db,
        current_user=current_user,
        zone_id=data["zone_id"],
    )

    location = StorageLocation(
        zone_id=zone.id,
        code=data["code"].strip().upper(),
        name=data["name"].strip(),
        capacity_unit=data.get("capacity_unit"),
        capacity_value=data.get("capacity_value"),
        is_active=data.get("is_active", True),
        is_receiving=data.get("is_receiving", False),
    )

    db.add(location)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise_error(
            status.HTTP_409_CONFLICT,
            STORAGE_LOCATION_NOT_FOUND,
            "Storage location code already exists in this zone",
        )

    db.refresh(location)
    return location


def list_storage_locations(
    db: Session,
    current_user: User,
    warehouse_id: Optional[int] = None,
    zone_id: Optional[int] = None,
    active_only: bool = False,
) -> list[StorageLocation]:
    company_id = tenant_id(current_user)

    query = (
        db.query(StorageLocation)
        .join(Zone, StorageLocation.zone_id == Zone.id)
        .join(Warehouse, Zone.warehouse_id == Warehouse.id)
        .filter(Warehouse.company_id == company_id)
    )

    if warehouse_id is not None:
        query = query.filter(Warehouse.id == warehouse_id)

    if zone_id is not None:
        query = query.filter(Zone.id == zone_id)

    if active_only:
        query = query.filter(StorageLocation.is_active.is_(True))

    return query.order_by(
        Warehouse.code.asc(),
        Zone.code.asc(),
        StorageLocation.code.asc(),
    ).all()


def update_storage_location(
    db: Session,
    current_user: User,
    storage_location_id: int,
    data: dict[str, Any],
) -> StorageLocation:
    location = get_storage_location_or_404(
        db=db,
        current_user=current_user,
        storage_location_id=storage_location_id,
    )

    for key, value in data.items():
        if key == "code" and value is not None:
            value = value.strip().upper()

        if key == "name" and value is not None:
            value = value.strip()

        setattr(location, key, value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise_error(
            status.HTTP_409_CONFLICT,
            STORAGE_LOCATION_NOT_FOUND,
            "Storage location code already exists in this zone",
        )

    db.refresh(location)
    return location


def get_warehouse_reference(
    db: Session,
    current_user: User,
    warehouse_id: int,
) -> dict[str, Any]:
    warehouse = get_warehouse_or_404(
        db=db,
        current_user=current_user,
        warehouse_id=warehouse_id,
        active_only=True,
    )

    return {
        "id": warehouse.id,
        "company_id": warehouse.company_id,
        "code": warehouse.code,
        "name": warehouse.name,
    }


def get_storage_location_reference(
    db: Session,
    current_user: User,
    storage_location_id: int,
) -> dict[str, Any]:
    location, warehouse_id = get_storage_location_by_company_or_404(
        db=db,
        company_id=tenant_id(current_user),
        storage_location_id=storage_location_id,
        active_only=True,
    )

    return {
        "id": location.id,
        "warehouse_id": warehouse_id,
        "zone_id": location.zone_id,
        "code": location.code,
        "name": location.name,
        "is_receiving": location.is_receiving,
    }


def get_or_create_receiving_location(
    db: Session,
    company_id: int,
    warehouse_id: int,
) -> StorageLocation:
    warehouse = get_warehouse_by_company_or_404(
        db=db,
        company_id=company_id,
        warehouse_id=warehouse_id,
        active_only=True,
    )

    existing = (
        db.query(StorageLocation)
        .join(Zone, StorageLocation.zone_id == Zone.id)
        .filter(
            Zone.warehouse_id == warehouse.id,
            StorageLocation.is_active.is_(True),
            StorageLocation.is_receiving.is_(True),
        )
        .order_by(StorageLocation.id.asc())
        .first()
    )

    if existing is not None:
        return existing

    zone = (
        db.query(Zone)
        .filter(
            Zone.warehouse_id == warehouse.id,
            Zone.code == "RECEIVING",
        )
        .first()
    )

    if zone is None:
        zone = Zone(
            warehouse_id=warehouse.id,
            code="RECEIVING",
            name="Receiving",
            description="System receiving zone",
        )
        db.add(zone)
        db.flush()

    location = (
        db.query(StorageLocation)
        .filter(
            StorageLocation.zone_id == zone.id,
            StorageLocation.code == "RECEIVING",
        )
        .first()
    )

    if location is None:
        location = StorageLocation(
            zone_id=zone.id,
            code="RECEIVING",
            name="Receiving",
            is_active=True,
            is_receiving=True,
        )
        db.add(location)
        db.flush()
    else:
        location.is_active = True
        location.is_receiving = True
        db.flush()

    return location


def get_or_create_system_default_receiving_location(
    db: Session,
    company_id: int,
) -> StorageLocation:
    warehouse = (
        db.query(Warehouse)
        .filter(
            Warehouse.company_id == company_id,
            Warehouse.is_default.is_(True),
        )
        .first()
    )

    if warehouse is None:
        warehouse = (
            db.query(Warehouse)
            .filter(
                Warehouse.company_id == company_id,
                Warehouse.code == "SYSTEM",
            )
            .first()
        )

    if warehouse is None:
        warehouse = Warehouse(
            company_id=company_id,
            code="SYSTEM",
            name="System Receiving Warehouse",
            warehouse_type=WarehouseType.MAIN.value,
            is_active=True,
            is_default=True,
        )
        db.add(warehouse)
        db.flush()
    else:
        (
            db.query(Warehouse)
            .filter(
                Warehouse.company_id == company_id,
                Warehouse.is_default.is_(True),
                Warehouse.id != warehouse.id,
            )
            .update(
                {Warehouse.is_default: False},
                synchronize_session=False,
            )
        )
        warehouse.is_active = True
        warehouse.is_default = True
        db.flush()

    return get_or_create_receiving_location(
        db=db,
        company_id=company_id,
        warehouse_id=warehouse.id,
    )


def resolve_receipt_destination(
    db: Session,
    company_id: int,
    warehouse_id: Optional[int],
    storage_location_id: Optional[int],
) -> StorageLocation:
    if storage_location_id is not None:
        location, location_warehouse_id = get_storage_location_by_company_or_404(
            db=db,
            company_id=company_id,
            storage_location_id=storage_location_id,
            active_only=True,
        )

        if warehouse_id is not None and location_warehouse_id != warehouse_id:
            raise_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                STORAGE_LOCATION_WAREHOUSE_MISMATCH,
                "Storage location does not belong to the goods receipt warehouse",
            )

        return location

    if warehouse_id is not None:
        return get_or_create_receiving_location(
            db=db,
            company_id=company_id,
            warehouse_id=warehouse_id,
        )

    return get_or_create_system_default_receiving_location(
        db=db,
        company_id=company_id,
    )


def get_stock_item_or_404(
    db: Session,
    current_user: User,
    stock_item_id: int,
) -> StockItem:
    stock_item = (
        db.query(StockItem)
        .filter(
            StockItem.id == stock_item_id,
            StockItem.company_id == tenant_id(current_user),
        )
        .first()
    )

    if stock_item is None:
        raise_error(
            status.HTTP_404_NOT_FOUND,
            STOCK_ITEM_NOT_FOUND,
            "Stock item not found",
        )

    return stock_item


def list_stock_items(
    db: Session,
    current_user: User,
    item_id: Optional[int] = None,
    warehouse_id: Optional[int] = None,
    storage_location_id: Optional[int] = None,
    low_stock_only: bool = False,
) -> list[StockItem]:
    company_id = tenant_id(current_user)

    query = (
        db.query(StockItem)
        .join(
            StorageLocation,
            StockItem.storage_location_id == StorageLocation.id,
        )
        .join(Zone, StorageLocation.zone_id == Zone.id)
        .join(Warehouse, Zone.warehouse_id == Warehouse.id)
        .filter(StockItem.company_id == company_id)
    )

    if item_id is not None:
        query = query.filter(StockItem.item_id == item_id)

    if warehouse_id is not None:
        query = query.filter(Warehouse.id == warehouse_id)

    if storage_location_id is not None:
        query = query.filter(
            StockItem.storage_location_id == storage_location_id
        )

    if low_stock_only:
        query = query.filter(
            StockItem.reorder_point.isnot(None),
            StockItem.quantity_available <= StockItem.reorder_point,
        )

    return query.order_by(
        Warehouse.code.asc(),
        Zone.code.asc(),
        StorageLocation.code.asc(),
        StockItem.item_id.asc(),
    ).all()


def update_stock_thresholds(
    db: Session,
    current_user: User,
    stock_item_id: int,
    data: dict[str, Any],
) -> StockItem:
    stock_item = get_stock_item_or_404(
        db=db,
        current_user=current_user,
        stock_item_id=stock_item_id,
    )

    for field in ("min_level", "max_level", "reorder_point"):
        if field in data:
            setattr(stock_item, field, data[field])

    min_level = stock_item.min_level
    max_level = stock_item.max_level

    if (
        min_level is not None
        and max_level is not None
        and decimal_value(min_level) > decimal_value(max_level)
    ):
        raise_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            STOCK_MOVEMENT_INVALID,
            "min_level cannot exceed max_level",
        )

    db.commit()
    db.refresh(stock_item)
    return stock_item


def get_stock_item_for_update(
    db: Session,
    company_id: int,
    item_id: int,
    storage_location_id: int,
) -> Optional[StockItem]:
    return (
        db.query(StockItem)
        .filter(
            StockItem.company_id == company_id,
            StockItem.item_id == item_id,
            StockItem.storage_location_id == storage_location_id,
        )
        .with_for_update()
        .first()
    )


def get_or_create_stock_item_for_receipt(
    db: Session,
    company_id: int,
    item_id: int,
    storage_location_id: int,
    base_currency_id: int,
) -> StockItem:
    stock_item = get_stock_item_for_update(
        db=db,
        company_id=company_id,
        item_id=item_id,
        storage_location_id=storage_location_id,
    )

    if stock_item is not None:
        return stock_item

    stock_item = StockItem(
        company_id=company_id,
        item_id=item_id,
        storage_location_id=storage_location_id,
        quantity_on_hand=ZERO,
        quantity_reserved=ZERO,
        quantity_available=ZERO,
        unit_cost=ZERO,
        unit_cost_currency_id=base_currency_id,
        unit_cost_base=ZERO,
    )

    db.add(stock_item)
    db.flush()
    return stock_item


def next_movement_number(db: Session, company_id: int) -> str:
    year = datetime.utcnow().year
    sequence_value = db.execute(
        text("SELECT nextval('stock_movement_number_seq')")
    ).scalar_one()

    return f"MOV-{year}-{sequence_value:05d}"


def find_reference_movement(
    db: Session,
    company_id: int,
    reference_type: str,
    reference_id: int,
    reference_line_id: Optional[int],
) -> Optional[StockMovement]:
    return (
        db.query(StockMovement)
        .filter(
            StockMovement.company_id == company_id,
            StockMovement.reference_type == reference_type,
            StockMovement.reference_id == reference_id,
            StockMovement.reference_line_id == reference_line_id,
        )
        .first()
    )


def apply_incoming_balance(
    stock_item: StockItem,
    quantity: Decimal,
    unit_cost_base: Decimal,
    base_currency_id: int,
) -> None:
    current_quantity = decimal_value(stock_item.quantity_on_hand)
    current_cost_base = decimal_value(stock_item.unit_cost_base)
    received_quantity = decimal_value(quantity)
    received_cost_base = decimal_value(unit_cost_base)

    new_quantity = current_quantity + received_quantity

    if new_quantity <= ZERO:
        raise_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            STOCK_MOVEMENT_INVALID,
            "Incoming quantity must make stock positive",
        )

    weighted_cost_base = (
        (current_quantity * current_cost_base)
        + (received_quantity * received_cost_base)
    ) / new_quantity

    stock_item.quantity_on_hand = new_quantity
    stock_item.quantity_available = (
        new_quantity - decimal_value(stock_item.quantity_reserved)
    )
    stock_item.unit_cost = weighted_cost_base
    stock_item.unit_cost_currency_id = base_currency_id
    stock_item.unit_cost_base = weighted_cost_base


def apply_outgoing_balance(
    stock_item: StockItem,
    quantity: Decimal,
) -> tuple[Decimal, int, Decimal]:
    requested_quantity = decimal_value(quantity)
    available_quantity = decimal_value(stock_item.quantity_available)

    if available_quantity < requested_quantity:
        raise_error(
            status.HTTP_409_CONFLICT,
            STOCK_INSUFFICIENT,
            "Insufficient available quantity for this movement",
        )

    source_cost = decimal_value(stock_item.unit_cost)
    source_currency_id = stock_item.unit_cost_currency_id
    source_cost_base = decimal_value(stock_item.unit_cost_base)

    stock_item.quantity_on_hand = (
        decimal_value(stock_item.quantity_on_hand)
        - requested_quantity
    )
    stock_item.quantity_available = (
        decimal_value(stock_item.quantity_on_hand)
        - decimal_value(stock_item.quantity_reserved)
    )

    return source_cost, source_currency_id, source_cost_base


def validate_movement_locations(
    movement_type: str,
    from_location_id: Optional[int],
    to_location_id: Optional[int],
) -> None:
    incoming_types = {
        StockMovementType.RECEIPT.value,
        StockMovementType.RETURN.value,
        StockMovementType.TRANSFER_IN.value,
    }
    outgoing_types = {
        StockMovementType.ISSUE.value,
        StockMovementType.TRANSFER_OUT.value,
    }

    if movement_type in incoming_types and to_location_id is None:
        raise_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            STOCK_MOVEMENT_INVALID,
            "Destination location is required for this movement",
        )

    if movement_type in outgoing_types and from_location_id is None:
        raise_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            STOCK_MOVEMENT_INVALID,
            "Source location is required for this movement",
        )

    if movement_type == StockMovementType.TRANSFER_OUT.value:
        if to_location_id is None:
            raise_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                STOCK_MOVEMENT_INVALID,
                "Destination location is required for transfer",
            )

    if movement_type in {
        StockMovementType.ADJUSTMENT.value,
        StockMovementType.COUNT_ADJUSTMENT.value,
    } and from_location_id is None and to_location_id is None:
        raise_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            STOCK_MOVEMENT_INVALID,
            "Adjustment requires a source or destination location",
        )

    if (
        from_location_id is not None
        and to_location_id is not None
        and from_location_id == to_location_id
    ):
        raise_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            STOCK_MOVEMENT_INVALID,
            "Source and destination locations must differ",
        )


def record_stock_movement(
    db: Session,
    company_id: int,
    movement_type: str,
    item_id: int,
    quantity: Decimal,
    unit_cost: Decimal,
    currency_id: int,
    unit_cost_base: Decimal,
    base_currency_id: int,
    exchange_rate_used: Decimal,
    from_location_id: Optional[int],
    to_location_id: Optional[int],
    reference_type: str,
    reference_id: int,
    reference_line_id: Optional[int],
    performed_by_user_id: Optional[int],
    movement_date: Optional[datetime] = None,
    notes: Optional[str] = None,
    idempotent: bool = False,
) -> tuple[StockMovement, bool]:
    validate_movement_locations(
        movement_type=movement_type,
        from_location_id=from_location_id,
        to_location_id=to_location_id,
    )

    if idempotent:
        lock_key = (
            f"{company_id}:{reference_type}:{reference_id}:{reference_line_id}"
        )
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": lock_key},
        )

        existing = find_reference_movement(
            db=db,
            company_id=company_id,
            reference_type=reference_type,
            reference_id=reference_id,
            reference_line_id=reference_line_id,
        )

        if existing is not None:
            return existing, False

    if from_location_id is not None:
        _, from_warehouse_id = get_storage_location_by_company_or_404(
            db=db,
            company_id=company_id,
            storage_location_id=from_location_id,
            active_only=True,
        )
        get_warehouse_by_company_or_404(
            db=db,
            company_id=company_id,
            warehouse_id=from_warehouse_id,
            active_only=True,
        )

    if to_location_id is not None:
        _, to_warehouse_id = get_storage_location_by_company_or_404(
            db=db,
            company_id=company_id,
            storage_location_id=to_location_id,
            active_only=True,
        )
        get_warehouse_by_company_or_404(
            db=db,
            company_id=company_id,
            warehouse_id=to_warehouse_id,
            active_only=True,
        )

    movement_quantity = decimal_value(quantity)
    effective_unit_cost = decimal_value(unit_cost)
    effective_currency_id = currency_id
    effective_unit_cost_base = decimal_value(unit_cost_base)
    effective_base_currency_id = base_currency_id
    effective_exchange_rate = decimal_value(exchange_rate_used)

    source_stock_item = None

    if from_location_id is not None:
        source_stock_item = get_stock_item_for_update(
            db=db,
            company_id=company_id,
            item_id=item_id,
            storage_location_id=from_location_id,
        )

        if source_stock_item is None:
            raise_error(
                status.HTTP_409_CONFLICT,
                STOCK_INSUFFICIENT,
                "No stock exists at the source location",
            )

        if movement_type in {
            StockMovementType.ISSUE.value,
            StockMovementType.TRANSFER_OUT.value,
        } or (
            movement_type
            in {
                StockMovementType.ADJUSTMENT.value,
                StockMovementType.COUNT_ADJUSTMENT.value,
            }
            and to_location_id is None
        ):
            (
                effective_unit_cost,
                effective_currency_id,
                effective_unit_cost_base,
            ) = apply_outgoing_balance(
                stock_item=source_stock_item,
                quantity=movement_quantity,
            )
            effective_base_currency_id = get_company_base_currency_id(
                db=db,
                company_id=company_id,
            )
            effective_exchange_rate = Decimal("1")

    should_add_to_destination = (
        to_location_id is not None
        and (
            movement_type
            in {
                StockMovementType.RECEIPT.value,
                StockMovementType.RETURN.value,
                StockMovementType.TRANSFER_IN.value,
                StockMovementType.TRANSFER_OUT.value,
            }
            or (
                movement_type
                in {
                    StockMovementType.ADJUSTMENT.value,
                    StockMovementType.COUNT_ADJUSTMENT.value,
                }
                and from_location_id is None
            )
        )
    )

    if should_add_to_destination:
        destination_stock_item = get_or_create_stock_item_for_receipt(
            db=db,
            company_id=company_id,
            item_id=item_id,
            storage_location_id=to_location_id,
            base_currency_id=effective_base_currency_id,
        )

        apply_incoming_balance(
            stock_item=destination_stock_item,
            quantity=movement_quantity,
            unit_cost_base=effective_unit_cost_base,
            base_currency_id=effective_base_currency_id,
        )

    movement = StockMovement(
        company_id=company_id,
        movement_number=next_movement_number(db, company_id),
        movement_type=movement_type,
        item_id=item_id,
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        quantity=movement_quantity,
        unit_cost=effective_unit_cost,
        currency_id=effective_currency_id,
        unit_cost_base=effective_unit_cost_base,
        base_currency_id=effective_base_currency_id,
        exchange_rate_used=effective_exchange_rate,
        reference_type=reference_type,
        reference_id=reference_id,
        reference_line_id=reference_line_id,
        performed_by_user_id=performed_by_user_id,
        movement_date=movement_date or datetime.utcnow(),
        notes=notes,
    )

    db.add(movement)
    db.flush()
    return movement, True


def create_manual_stock_movement(
    db: Session,
    current_user: User,
    data: dict[str, Any],
) -> StockMovement:
    company_id = tenant_id(current_user)

    from material_management.services import get_item_reference

    get_item_reference(
        db=db,
        current_user=current_user,
        item_id=data["item_id"],
    )

    movement, _ = record_stock_movement(
        db=db,
        company_id=company_id,
        movement_type=data["movement_type"],
        item_id=data["item_id"],
        quantity=data["quantity"],
        unit_cost=data["unit_cost"],
        currency_id=data["currency_id"],
        unit_cost_base=data["unit_cost_base"],
        base_currency_id=data["base_currency_id"],
        exchange_rate_used=data["exchange_rate_used"],
        from_location_id=data.get("from_location_id"),
        to_location_id=data.get("to_location_id"),
        reference_type=StockReferenceType.MANUAL.value,
        reference_id=0,
        reference_line_id=None,
        performed_by_user_id=current_user.id,
        notes=data.get("notes"),
        idempotent=False,
    )

    db.commit()
    db.refresh(movement)
    return movement


def list_stock_movements(
    db: Session,
    current_user: User,
    item_id: Optional[int] = None,
    warehouse_id: Optional[int] = None,
    reference_type: Optional[str] = None,
    reference_id: Optional[int] = None,
    page: int = 1,
    size: int = 50,
) -> list[StockMovement]:
    company_id = tenant_id(current_user)

    query = db.query(StockMovement).filter(
        StockMovement.company_id == company_id
    )

    if item_id is not None:
        query = query.filter(StockMovement.item_id == item_id)

    if reference_type is not None:
        query = query.filter(
            StockMovement.reference_type == reference_type
        )

    if reference_id is not None:
        query = query.filter(StockMovement.reference_id == reference_id)

    if warehouse_id is not None:
        location_ids = (
            db.query(StorageLocation.id)
            .join(Zone, StorageLocation.zone_id == Zone.id)
            .filter(Zone.warehouse_id == warehouse_id)
        )

        query = query.filter(
            or_(
                StockMovement.from_location_id.in_(location_ids),
                StockMovement.to_location_id.in_(location_ids),
            )
        )

    return (
        query.order_by(
            StockMovement.movement_date.desc(),
            StockMovement.id.desc(),
        )
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )


def process_grn_receipt(
    db: Session,
    goods_receipt_id: int,
) -> dict[str, Any]:
    from goods_receipt_management.services import (
        get_posted_goods_receipt_for_warehouse,
    )

    goods_receipt = get_posted_goods_receipt_for_warehouse(
        db=db,
        goods_receipt_id=goods_receipt_id,
    )

    created_movements = 0
    skipped_movements = 0

    for item in goods_receipt["items"]:
        if item["item_id"] is None:
            raise_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                STOCK_MOVEMENT_INVALID,
                "Accepted GRN items must have a material item reference",
            )

        destination = resolve_receipt_destination(
            db=db,
            company_id=goods_receipt["company_id"],
            warehouse_id=goods_receipt["warehouse_id"],
            storage_location_id=item["storage_location_id"],
        )

        movement_date = datetime.combine(
            goods_receipt["receipt_date"],
            time.min,
        )

        _, created = record_stock_movement(
            db=db,
            company_id=goods_receipt["company_id"],
            movement_type=StockMovementType.RECEIPT.value,
            item_id=item["item_id"],
            quantity=item["accepted_quantity"],
            unit_cost=item["unit_cost"],
            currency_id=item["currency_id"],
            unit_cost_base=item["unit_cost_base"],
            base_currency_id=item["base_currency_id"],
            exchange_rate_used=item["exchange_rate_used"],
            from_location_id=None,
            to_location_id=destination.id,
            reference_type=StockReferenceType.GRN.value,
            reference_id=goods_receipt["id"],
            reference_line_id=item["id"],
            performed_by_user_id=None,
            movement_date=movement_date,
            notes=f"GRN {goods_receipt['grn_number']}",
            idempotent=True,
        )

        if created:
            created_movements += 1
        else:
            skipped_movements += 1

    return {
        "goods_receipt_id": goods_receipt["id"],
        "created_movements": created_movements,
        "skipped_movements": skipped_movements,
    }


def inventory_value_summary_for_company(
    db: Session,
    company_id: int,
) -> dict[str, Decimal]:
    stock_items = (
        db.query(StockItem)
        .filter(StockItem.company_id == company_id)
        .all()
    )

    quantity_total = sum(
        (
            decimal_value(stock_item.quantity_on_hand)
            for stock_item in stock_items
        ),
        ZERO,
    )

    value_total = sum(
        (
            decimal_value(stock_item.quantity_on_hand)
            * decimal_value(stock_item.unit_cost_base)
            for stock_item in stock_items
        ),
        ZERO,
    )

    return {
        "quantity_total": quantity_total,
        "value_total": value_total,
    }


def warehouse_summary(
    db: Session,
    current_user: User,
) -> dict[str, Any]:
    company_id = tenant_id(current_user)

    stock_items = (
        db.query(StockItem)
        .filter(StockItem.company_id == company_id)
        .all()
    )

    low_stock_count = sum(
        1
        for stock_item in stock_items
        if stock_item.reorder_point is not None
        and decimal_value(stock_item.quantity_available)
        <= decimal_value(stock_item.reorder_point)
    )

    inventory = inventory_value_summary_for_company(
        db=db,
        company_id=company_id,
    )

    return {
        "warehouse_count": (
            db.query(Warehouse)
            .filter(
                Warehouse.company_id == company_id,
                Warehouse.is_active.is_(True),
            )
            .count()
        ),
        "stock_item_count": len(stock_items),
        "low_stock_count": low_stock_count,
        "quantity_on_hand_total": inventory["quantity_total"],
        "inventory_value_base": inventory["value_total"],
    }


def search_stock_items(
    db: Session,
    current_user: User,
    query_text: str,
    item_ids: Optional[list[int]] = None,
    warehouse_id: Optional[int] = None,
    storage_location_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    company_id = tenant_id(current_user)
    normalized_query = query_text.strip().lower()

    query = (
        db.query(
            StockItem,
            StorageLocation,
            Zone,
            Warehouse,
        )
        .join(
            StorageLocation,
            StockItem.storage_location_id == StorageLocation.id,
        )
        .join(Zone, StorageLocation.zone_id == Zone.id)
        .join(Warehouse, Zone.warehouse_id == Warehouse.id)
        .filter(StockItem.company_id == company_id)
    )

    if item_ids:
        query = query.filter(StockItem.item_id.in_(item_ids))

    if warehouse_id is not None:
        query = query.filter(Warehouse.id == warehouse_id)

    if storage_location_id is not None:
        query = query.filter(
            StorageLocation.id == storage_location_id
        )

    rows = (
        query.order_by(
            Warehouse.code.asc(),
            Zone.code.asc(),
            StorageLocation.code.asc(),
            StockItem.item_id.asc(),
        )
        .all()
    )

    from material_management.services import get_item_reference

    results: list[dict[str, Any]] = []

    for stock_item, location, zone, warehouse in rows:
        item = get_item_reference(
            db=db,
            current_user=current_user,
            item_id=stock_item.item_id,
        )

        haystack = " ".join(
            str(value or "").lower()
            for value in (
                item["item_code"],
                item["name"],
                item["unit_code"],
                warehouse.code,
                warehouse.name,
                zone.code,
                zone.name,
                location.code,
                location.name,
            )
        )

        if normalized_query not in haystack:
            continue

        results.append(
            {
                "id": stock_item.id,
                "company_id": stock_item.company_id,
                "item_id": stock_item.item_id,
                "item_code": item["item_code"],
                "item_name": item["name"],
                "unit_code": item["unit_code"],
                "storage_location_id": stock_item.storage_location_id,
                "storage_location_code": location.code,
                "storage_location_name": location.name,
                "zone_id": zone.id,
                "zone_code": zone.code,
                "warehouse_id": warehouse.id,
                "warehouse_code": warehouse.code,
                "warehouse_name": warehouse.name,
                "quantity_on_hand": stock_item.quantity_on_hand,
                "quantity_reserved": stock_item.quantity_reserved,
                "quantity_available": stock_item.quantity_available,
                "min_level": stock_item.min_level,
                "max_level": stock_item.max_level,
                "reorder_point": stock_item.reorder_point,
                "unit_cost": stock_item.unit_cost,
                "unit_cost_currency_id": stock_item.unit_cost_currency_id,
                "unit_cost_base": stock_item.unit_cost_base,
                "inventory_value_base": (
                    decimal_value(stock_item.quantity_on_hand)
                    * decimal_value(stock_item.unit_cost_base)
                ),
                "created_at": stock_item.created_at,
                "updated_at": stock_item.updated_at,
            }
        )

    return results[offset:offset + limit]


def create_stock_count(
    db: Session,
    current_user: User,
    warehouse_id: int,
    notes: Optional[str],
) -> StockCount:
    warehouse = get_warehouse_or_404(
        db=db,
        current_user=current_user,
        warehouse_id=warehouse_id,
        active_only=True,
    )

    company_id = tenant_id(current_user)
    year = datetime.utcnow().year
    prefix = f"COUNT-{year}-"

    count_numbers = (
        db.query(StockCount.count_number)
        .filter(
            StockCount.company_id == company_id,
            StockCount.count_number.like(f"{prefix}%"),
        )
        .all()
    )

    highest = 0

    for (count_number,) in count_numbers:
        suffix = (count_number or "").replace(prefix, "", 1)

        if suffix.isdigit():
            highest = max(highest, int(suffix))

    stock_count = StockCount(
        company_id=company_id,
        count_number=f"{prefix}{highest + 1:04d}",
        warehouse_id=warehouse.id,
        status=StockCountStatus.OPEN.value,
        performed_by_user_id=current_user.id,
        notes=notes,
    )

    db.add(stock_count)
    db.flush()

    stock_items = (
        db.query(StockItem)
        .join(
            StorageLocation,
            StockItem.storage_location_id == StorageLocation.id,
        )
        .join(Zone, StorageLocation.zone_id == Zone.id)
        .filter(
            StockItem.company_id == company_id,
            Zone.warehouse_id == warehouse.id,
        )
        .all()
    )

    for stock_item in stock_items:
        db.add(
            StockCountLine(
                stock_count_id=stock_count.id,
                item_id=stock_item.item_id,
                storage_location_id=stock_item.storage_location_id,
                system_quantity=stock_item.quantity_on_hand,
                counted_quantity=None,
                variance=None,
            )
        )

    db.commit()
    db.refresh(stock_count)
    return stock_count


def get_stock_count_or_404(
    db: Session,
    current_user: User,
    stock_count_id: int,
    for_update: bool = False,
) -> StockCount:
    query = db.query(StockCount).filter(
        StockCount.id == stock_count_id,
        StockCount.company_id == tenant_id(current_user),
    )

    if for_update:
        query = query.with_for_update()

    stock_count = query.first()

    if stock_count is None:
        raise_error(
            status.HTTP_404_NOT_FOUND,
            STOCK_COUNT_NOT_FOUND,
            "Stock count not found",
        )

    return stock_count


def start_stock_count(
    db: Session,
    current_user: User,
    stock_count_id: int,
) -> StockCount:
    stock_count = get_stock_count_or_404(
        db=db,
        current_user=current_user,
        stock_count_id=stock_count_id,
        for_update=True,
    )

    if stock_count.status != StockCountStatus.OPEN.value:
        raise_error(
            status.HTTP_409_CONFLICT,
            STOCK_COUNT_NOT_EDITABLE,
            "Only open stock counts can be started",
        )

    stock_count.status = StockCountStatus.IN_PROGRESS.value
    db.commit()
    db.refresh(stock_count)
    return stock_count


def add_stock_count_line(
    db: Session,
    current_user: User,
    stock_count_id: int,
    data: dict[str, Any],
) -> StockCountLine:
    stock_count = get_stock_count_or_404(
        db=db,
        current_user=current_user,
        stock_count_id=stock_count_id,
        for_update=True,
    )

    if stock_count.status not in {
        StockCountStatus.OPEN.value,
        StockCountStatus.IN_PROGRESS.value,
    }:
        raise_error(
            status.HTTP_409_CONFLICT,
            STOCK_COUNT_NOT_EDITABLE,
            "Posted stock counts cannot be changed",
        )

    from material_management.services import get_item_reference

    get_item_reference(
        db=db,
        current_user=current_user,
        item_id=data["item_id"],
    )

    location, location_warehouse_id = get_storage_location_by_company_or_404(
        db=db,
        company_id=tenant_id(current_user),
        storage_location_id=data["storage_location_id"],
        active_only=True,
    )

    if location_warehouse_id != stock_count.warehouse_id:
        raise_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            STORAGE_LOCATION_WAREHOUSE_MISMATCH,
            "Stock count location does not belong to the selected warehouse",
        )

    stock_item = get_stock_item_for_update(
        db=db,
        company_id=tenant_id(current_user),
        item_id=data["item_id"],
        storage_location_id=location.id,
    )

    line = StockCountLine(
        stock_count_id=stock_count.id,
        item_id=data["item_id"],
        storage_location_id=location.id,
        system_quantity=(
            stock_item.quantity_on_hand
            if stock_item is not None
            else ZERO
        ),
        counted_quantity=data.get("counted_quantity"),
        variance=(
            decimal_value(data["counted_quantity"])
            - decimal_value(
                stock_item.quantity_on_hand
                if stock_item is not None
                else ZERO
            )
            if data.get("counted_quantity") is not None
            else None
        ),
    )

    db.add(line)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise_error(
            status.HTTP_409_CONFLICT,
            STOCK_COUNT_NOT_EDITABLE,
            "This item and storage location already exist in the stock count",
        )

    db.refresh(line)
    return line


def update_stock_count_line(
    db: Session,
    current_user: User,
    stock_count_id: int,
    stock_count_line_id: int,
    counted_quantity: Decimal,
) -> StockCountLine:
    stock_count = get_stock_count_or_404(
        db=db,
        current_user=current_user,
        stock_count_id=stock_count_id,
        for_update=True,
    )

    if stock_count.status not in {
        StockCountStatus.OPEN.value,
        StockCountStatus.IN_PROGRESS.value,
    }:
        raise_error(
            status.HTTP_409_CONFLICT,
            STOCK_COUNT_NOT_EDITABLE,
            "Posted stock counts cannot be changed",
        )

    line = (
        db.query(StockCountLine)
        .filter(
            StockCountLine.id == stock_count_line_id,
            StockCountLine.stock_count_id == stock_count.id,
        )
        .first()
    )

    if line is None:
        raise_error(
            status.HTTP_404_NOT_FOUND,
            STOCK_COUNT_LINE_NOT_FOUND,
            "Stock count line not found",
        )

    line.counted_quantity = counted_quantity
    line.variance = (
        decimal_value(counted_quantity)
        - decimal_value(line.system_quantity)
    )

    db.commit()
    db.refresh(line)
    return line


def post_stock_count(
    db: Session,
    current_user: User,
    stock_count_id: int,
) -> StockCount:
    stock_count = get_stock_count_or_404(
        db=db,
        current_user=current_user,
        stock_count_id=stock_count_id,
        for_update=True,
    )

    if stock_count.status != StockCountStatus.IN_PROGRESS.value:
        raise_error(
            status.HTTP_409_CONFLICT,
            STOCK_COUNT_NOT_POSTABLE,
            "Only in-progress stock counts can be posted",
        )

    lines = (
        db.query(StockCountLine)
        .filter(StockCountLine.stock_count_id == stock_count.id)
        .order_by(StockCountLine.id.asc())
        .all()
    )

    if any(line.counted_quantity is None for line in lines):
        raise_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            STOCK_COUNT_INCOMPLETE,
            "All stock count lines require counted_quantity before posting",
        )

    company_id = tenant_id(current_user)
    base_currency_id = get_company_base_currency_id(
        db=db,
        company_id=company_id,
    )

    for line in lines:
        variance = (
            decimal_value(line.counted_quantity)
            - decimal_value(line.system_quantity)
        )
        line.variance = variance

        if variance == ZERO:
            continue

        stock_item = get_stock_item_for_update(
            db=db,
            company_id=company_id,
            item_id=line.item_id,
            storage_location_id=line.storage_location_id,
        )

        unit_cost = (
            decimal_value(stock_item.unit_cost)
            if stock_item is not None
            else ZERO
        )
        currency_id = (
            stock_item.unit_cost_currency_id
            if stock_item is not None
            else base_currency_id
        )
        unit_cost_base = (
            decimal_value(stock_item.unit_cost_base)
            if stock_item is not None
            else ZERO
        )

        record_stock_movement(
            db=db,
            company_id=company_id,
            movement_type=StockMovementType.COUNT_ADJUSTMENT.value,
            item_id=line.item_id,
            quantity=abs(variance),
            unit_cost=unit_cost,
            currency_id=currency_id,
            unit_cost_base=unit_cost_base,
            base_currency_id=base_currency_id,
            exchange_rate_used=Decimal("1"),
            from_location_id=(
                line.storage_location_id
                if variance < ZERO
                else None
            ),
            to_location_id=(
                line.storage_location_id
                if variance > ZERO
                else None
            ),
            reference_type=StockReferenceType.STOCK_COUNT.value,
            reference_id=stock_count.id,
            reference_line_id=line.id,
            performed_by_user_id=current_user.id,
            notes=f"Stock count {stock_count.count_number}",
            idempotent=True,
        )

    stock_count.status = StockCountStatus.POSTED.value
    stock_count.posted_at = datetime.utcnow()

    db.commit()
    db.refresh(stock_count)
    return stock_count


def list_stock_count_lines(
    db: Session,
    current_user: User,
    stock_count_id: int,
) -> list[StockCountLine]:
    stock_count = get_stock_count_or_404(
        db=db,
        current_user=current_user,
        stock_count_id=stock_count_id,
    )

    return (
        db.query(StockCountLine)
        .filter(StockCountLine.stock_count_id == stock_count.id)
        .order_by(StockCountLine.id.asc())
        .all()
    )


def list_stock_counts(
    db: Session,
    current_user: User,
    warehouse_id: Optional[int] = None,
    stock_count_status: Optional[str] = None,
) -> list[StockCount]:
    query = db.query(StockCount).filter(
        StockCount.company_id == tenant_id(current_user)
    )

    if warehouse_id is not None:
        query = query.filter(StockCount.warehouse_id == warehouse_id)

    if stock_count_status is not None:
        query = query.filter(StockCount.status == stock_count_status)

    return query.order_by(
        StockCount.created_at.desc(),
        StockCount.id.desc(),
    ).all()


def get_low_stock_items(
    db: Session,
    current_user: User,
) -> list[StockItem]:
    return list_stock_items(
        db=db,
        current_user=current_user,
        low_stock_only=True,
    )


def backfill_posted_goods_receipts(
    db: Session,
    company_id: Optional[int] = None,
) -> dict[str, int]:
    from goods_receipt_management.services import (
        list_posted_goods_receipt_ids_for_warehouse,
    )

    goods_receipt_ids = list_posted_goods_receipt_ids_for_warehouse(
        db=db,
        company_id=company_id,
    )

    created_movements = 0
    skipped_movements = 0

    for goods_receipt_id in goods_receipt_ids:
        result = process_grn_receipt(
            db=db,
            goods_receipt_id=goods_receipt_id,
        )
        created_movements += result["created_movements"]
        skipped_movements += result["skipped_movements"]

    return {
        "goods_receipts": len(goods_receipt_ids),
        "created_movements": created_movements,
        "skipped_movements": skipped_movements,
    }
