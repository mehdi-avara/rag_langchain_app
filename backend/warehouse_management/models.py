from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)

from db.base import Base


class WarehouseType(str, enum.Enum):
    MAIN = "main"
    SECONDARY = "secondary"
    FIELD = "field"
    TRANSIT = "transit"


class StockMovementType(str, enum.Enum):
    RECEIPT = "receipt"
    ISSUE = "issue"
    TRANSFER_OUT = "transfer_out"
    TRANSFER_IN = "transfer_in"
    ADJUSTMENT = "adjustment"
    RETURN = "return"
    COUNT_ADJUSTMENT = "count_adjustment"


class StockReferenceType(str, enum.Enum):
    GRN = "grn"
    WORK_ORDER = "work_order"
    MANUAL = "manual"
    STOCK_COUNT = "stock_count"
    LEGACY_MIGRATION = "legacy_migration"


class StockCountStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    POSTED = "posted"


class Warehouse(Base):
    __tablename__ = "warehouses"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "code",
            name="uq_warehouses_company_code",
        ),
        Index("ix_warehouses_company_id", "company_id"),
        Index("ix_warehouses_manager_id", "manager_id"),
        Index("ix_warehouses_type", "warehouse_type"),
        Index("ix_warehouses_active", "is_active"),
        Index("ix_warehouses_default", "is_default"),
        Index(
            "uq_warehouses_one_default",
            "company_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(
        Integer,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    code = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    warehouse_type = Column(
        String(30),
        nullable=False,
        default=WarehouseType.MAIN.value,
    )
    location = Column(String(255), nullable=True)
    address = Column(Text, nullable=True)
    manager_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active = Column(Boolean, nullable=False, default=True)
    is_default = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class Zone(Base):
    __tablename__ = "warehouse_zones"
    __table_args__ = (
        UniqueConstraint(
            "warehouse_id",
            "code",
            name="uq_warehouse_zones_code",
        ),
        Index("ix_warehouse_zones_warehouse_id", "warehouse_id"),
    )

    id = Column(Integer, primary_key=True)
    warehouse_id = Column(
        Integer,
        ForeignKey("warehouses.id", ondelete="CASCADE"),
        nullable=False,
    )
    code = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class StorageLocation(Base):
    __tablename__ = "storage_locations"
    __table_args__ = (
        UniqueConstraint(
            "zone_id",
            "code",
            name="uq_storage_locations_zone_code",
        ),
        Index("ix_storage_locations_zone_id", "zone_id"),
        Index("ix_storage_locations_active", "is_active"),
        Index("ix_storage_locations_receiving", "is_receiving"),
    )

    id = Column(Integer, primary_key=True)
    zone_id = Column(
        Integer,
        ForeignKey("warehouse_zones.id", ondelete="CASCADE"),
        nullable=False,
    )
    code = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    capacity_unit = Column(String(30), nullable=True)
    capacity_value = Column(Numeric(18, 4), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    is_receiving = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class StockItem(Base):
    __tablename__ = "stock_items"
    __table_args__ = (
        UniqueConstraint(
            "item_id",
            "storage_location_id",
            name="uq_stock_items_item_location",
        ),
        CheckConstraint(
            "quantity_on_hand >= 0",
            name="ck_stock_items_on_hand_nonnegative",
        ),
        CheckConstraint(
            "quantity_reserved >= 0",
            name="ck_stock_items_reserved_nonnegative",
        ),
        CheckConstraint(
            "quantity_available = quantity_on_hand - quantity_reserved",
            name="ck_stock_items_available_balance",
        ),
        Index("ix_stock_items_company_id", "company_id"),
        Index("ix_stock_items_item_id", "item_id"),
        Index("ix_stock_items_location_id", "storage_location_id"),
        Index("ix_stock_items_reorder_point", "reorder_point"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(
        Integer,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id = Column(
        Integer,
        ForeignKey("items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    storage_location_id = Column(
        Integer,
        ForeignKey("storage_locations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity_on_hand = Column(
        Numeric(18, 4),
        nullable=False,
        default=0,
    )
    quantity_reserved = Column(
        Numeric(18, 4),
        nullable=False,
        default=0,
    )
    quantity_available = Column(
        Numeric(18, 4),
        nullable=False,
        default=0,
    )
    min_level = Column(Numeric(18, 4), nullable=True)
    max_level = Column(Numeric(18, 4), nullable=True)
    reorder_point = Column(Numeric(18, 4), nullable=True)
    unit_cost = Column(Numeric(28, 10), nullable=False, default=0)
    unit_cost_currency_id = Column(
        Integer,
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    unit_cost_base = Column(Numeric(28, 10), nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "movement_number",
            name="uq_stock_movements_company_number",
        ),
        Index(
            "uq_stock_movements_grn_reference_line",
            "company_id",
            "reference_type",
            "reference_id",
            "reference_line_id",
            unique=True,
            postgresql_where=text("reference_type = 'grn'"),
        ),
        CheckConstraint(
            "quantity > 0",
            name="ck_stock_movements_quantity_positive",
        ),
        Index("ix_stock_movements_company_id", "company_id"),
        Index("ix_stock_movements_item_id", "item_id"),
        Index("ix_stock_movements_from_location", "from_location_id"),
        Index("ix_stock_movements_to_location", "to_location_id"),
        Index("ix_stock_movements_type", "movement_type"),
        Index("ix_stock_movements_reference", "reference_type", "reference_id"),
        Index("ix_stock_movements_date", "movement_date"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(
        Integer,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    movement_number = Column(String(50), nullable=False)
    movement_type = Column(String(30), nullable=False)
    item_id = Column(
        Integer,
        ForeignKey("items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    from_location_id = Column(
        Integer,
        ForeignKey("storage_locations.id", ondelete="RESTRICT"),
        nullable=True,
    )
    to_location_id = Column(
        Integer,
        ForeignKey("storage_locations.id", ondelete="RESTRICT"),
        nullable=True,
    )
    quantity = Column(Numeric(18, 4), nullable=False)
    unit_cost = Column(Numeric(28, 10), nullable=False)
    currency_id = Column(
        Integer,
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    unit_cost_base = Column(Numeric(28, 10), nullable=False)
    base_currency_id = Column(
        Integer,
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    exchange_rate_used = Column(Numeric(28, 10), nullable=False)
    reference_type = Column(String(30), nullable=False)
    reference_id = Column(Integer, nullable=False)
    reference_line_id = Column(Integer, nullable=True)
    performed_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    movement_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class StockCount(Base):
    __tablename__ = "stock_counts"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "count_number",
            name="uq_stock_counts_company_number",
        ),
        Index("ix_stock_counts_company_id", "company_id"),
        Index("ix_stock_counts_warehouse_id", "warehouse_id"),
        Index("ix_stock_counts_status", "status"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(
        Integer,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    count_number = Column(String(50), nullable=False)
    warehouse_id = Column(
        Integer,
        ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status = Column(
        String(30),
        nullable=False,
        default=StockCountStatus.OPEN.value,
    )
    performed_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    posted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class StockCountLine(Base):
    __tablename__ = "stock_count_lines"
    __table_args__ = (
        UniqueConstraint(
            "stock_count_id",
            "item_id",
            "storage_location_id",
            name="uq_stock_count_lines_item_location",
        ),
        Index("ix_stock_count_lines_count_id", "stock_count_id"),
        Index("ix_stock_count_lines_item_id", "item_id"),
        Index("ix_stock_count_lines_location_id", "storage_location_id"),
    )

    id = Column(Integer, primary_key=True)
    stock_count_id = Column(
        Integer,
        ForeignKey("stock_counts.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id = Column(
        Integer,
        ForeignKey("items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    storage_location_id = Column(
        Integer,
        ForeignKey("storage_locations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    system_quantity = Column(Numeric(18, 4), nullable=False)
    counted_quantity = Column(Numeric(18, 4), nullable=True)
    variance = Column(Numeric(18, 4), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
