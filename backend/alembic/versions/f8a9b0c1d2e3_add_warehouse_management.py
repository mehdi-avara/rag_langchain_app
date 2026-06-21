"""add_warehouse_management

Revision ID: f8a9b0c1d2e3
Revises: e7f8091a2b3c
Create Date: 2026-06-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, None] = "e7f8091a2b3c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE stock_movement_number_seq START WITH 1")

    op.create_table(
        "warehouses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("warehouse_type", sa.String(length=30), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("manager_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_warehouses_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["manager_id"],
            ["users.id"],
            name="fk_warehouses_manager",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_warehouses"),
        sa.UniqueConstraint(
            "company_id",
            "code",
            name="uq_warehouses_company_code",
        ),
    )

    op.create_index("ix_warehouses_company_id", "warehouses", ["company_id"])
    op.create_index("ix_warehouses_manager_id", "warehouses", ["manager_id"])
    op.create_index("ix_warehouses_type", "warehouses", ["warehouse_type"])
    op.create_index("ix_warehouses_active", "warehouses", ["is_active"])
    op.create_index("ix_warehouses_default", "warehouses", ["is_default"])
    op.create_index(
        "uq_warehouses_one_default",
        "warehouses",
        ["company_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    op.create_table(
        "warehouse_zones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouses.id"],
            name="fk_warehouse_zones_warehouse",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_warehouse_zones"),
        sa.UniqueConstraint(
            "warehouse_id",
            "code",
            name="uq_warehouse_zones_code",
        ),
    )

    op.create_index(
        "ix_warehouse_zones_warehouse_id",
        "warehouse_zones",
        ["warehouse_id"],
    )

    op.create_table(
        "storage_locations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("zone_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("capacity_unit", sa.String(length=30), nullable=True),
        sa.Column(
            "capacity_value",
            sa.Numeric(precision=18, scale=4),
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_receiving", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["zone_id"],
            ["warehouse_zones.id"],
            name="fk_storage_locations_zone",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_storage_locations"),
        sa.UniqueConstraint(
            "zone_id",
            "code",
            name="uq_storage_locations_zone_code",
        ),
    )

    op.create_index(
        "ix_storage_locations_zone_id",
        "storage_locations",
        ["zone_id"],
    )
    op.create_index(
        "ix_storage_locations_active",
        "storage_locations",
        ["is_active"],
    )
    op.create_index(
        "ix_storage_locations_receiving",
        "storage_locations",
        ["is_receiving"],
    )

    op.create_table(
        "stock_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("storage_location_id", sa.Integer(), nullable=False),
        sa.Column(
            "quantity_on_hand",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
        ),
        sa.Column(
            "quantity_reserved",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
        ),
        sa.Column(
            "quantity_available",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
        ),
        sa.Column(
            "min_level",
            sa.Numeric(precision=18, scale=4),
            nullable=True,
        ),
        sa.Column(
            "max_level",
            sa.Numeric(precision=18, scale=4),
            nullable=True,
        ),
        sa.Column(
            "reorder_point",
            sa.Numeric(precision=18, scale=4),
            nullable=True,
        ),
        sa.Column(
            "unit_cost",
            sa.Numeric(precision=28, scale=10),
            nullable=False,
        ),
        sa.Column("unit_cost_currency_id", sa.Integer(), nullable=False),
        sa.Column(
            "unit_cost_base",
            sa.Numeric(precision=28, scale=10),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "quantity_on_hand >= 0",
            name="ck_stock_items_on_hand_nonnegative",
        ),
        sa.CheckConstraint(
            "quantity_reserved >= 0",
            name="ck_stock_items_reserved_nonnegative",
        ),
        sa.CheckConstraint(
            "quantity_available = quantity_on_hand - quantity_reserved",
            name="ck_stock_items_available_balance",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_stock_items_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["items.id"],
            name="fk_stock_items_item",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["storage_location_id"],
            ["storage_locations.id"],
            name="fk_stock_items_location",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["unit_cost_currency_id"],
            ["currencies.id"],
            name="fk_stock_items_currency",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stock_items"),
        sa.UniqueConstraint(
            "item_id",
            "storage_location_id",
            name="uq_stock_items_item_location",
        ),
    )

    op.create_index("ix_stock_items_company_id", "stock_items", ["company_id"])
    op.create_index("ix_stock_items_item_id", "stock_items", ["item_id"])
    op.create_index(
        "ix_stock_items_location_id",
        "stock_items",
        ["storage_location_id"],
    )
    op.create_index(
        "ix_stock_items_reorder_point",
        "stock_items",
        ["reorder_point"],
    )

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("movement_number", sa.String(length=50), nullable=False),
        sa.Column("movement_type", sa.String(length=30), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("from_location_id", sa.Integer(), nullable=True),
        sa.Column("to_location_id", sa.Integer(), nullable=True),
        sa.Column(
            "quantity",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
        ),
        sa.Column(
            "unit_cost",
            sa.Numeric(precision=28, scale=10),
            nullable=False,
        ),
        sa.Column("currency_id", sa.Integer(), nullable=False),
        sa.Column(
            "unit_cost_base",
            sa.Numeric(precision=28, scale=10),
            nullable=False,
        ),
        sa.Column("base_currency_id", sa.Integer(), nullable=False),
        sa.Column(
            "exchange_rate_used",
            sa.Numeric(precision=28, scale=10),
            nullable=False,
        ),
        sa.Column("reference_type", sa.String(length=30), nullable=False),
        sa.Column("reference_id", sa.Integer(), nullable=False),
        sa.Column("reference_line_id", sa.Integer(), nullable=True),
        sa.Column("performed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("movement_date", sa.DateTime(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_stock_movements_quantity_positive",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_stock_movements_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["items.id"],
            name="fk_stock_movements_item",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["from_location_id"],
            ["storage_locations.id"],
            name="fk_stock_movements_from_location",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_location_id"],
            ["storage_locations.id"],
            name="fk_stock_movements_to_location",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["currency_id"],
            ["currencies.id"],
            name="fk_stock_movements_currency",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_currency_id"],
            ["currencies.id"],
            name="fk_stock_movements_base_currency",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["performed_by_user_id"],
            ["users.id"],
            name="fk_stock_movements_performed_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stock_movements"),
        sa.UniqueConstraint(
            "company_id",
            "movement_number",
            name="uq_stock_movements_company_number",
        ),
    )

    op.create_index(
        "uq_stock_movements_grn_reference_line",
        "stock_movements",
        ["company_id", "reference_type", "reference_id", "reference_line_id"],
        unique=True,
        postgresql_where=sa.text("reference_type = 'grn'"),
    )
    op.create_index(
        "ix_stock_movements_company_id",
        "stock_movements",
        ["company_id"],
    )
    op.create_index(
        "ix_stock_movements_item_id",
        "stock_movements",
        ["item_id"],
    )
    op.create_index(
        "ix_stock_movements_from_location",
        "stock_movements",
        ["from_location_id"],
    )
    op.create_index(
        "ix_stock_movements_to_location",
        "stock_movements",
        ["to_location_id"],
    )
    op.create_index(
        "ix_stock_movements_type",
        "stock_movements",
        ["movement_type"],
    )
    op.create_index(
        "ix_stock_movements_reference",
        "stock_movements",
        ["reference_type", "reference_id"],
    )
    op.create_index(
        "ix_stock_movements_date",
        "stock_movements",
        ["movement_date"],
    )

    op.create_table(
        "stock_counts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("count_number", sa.String(length=50), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("performed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("posted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_stock_counts_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouses.id"],
            name="fk_stock_counts_warehouse",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["performed_by_user_id"],
            ["users.id"],
            name="fk_stock_counts_performed_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stock_counts"),
        sa.UniqueConstraint(
            "company_id",
            "count_number",
            name="uq_stock_counts_company_number",
        ),
    )

    op.create_index(
        "ix_stock_counts_company_id",
        "stock_counts",
        ["company_id"],
    )
    op.create_index(
        "ix_stock_counts_warehouse_id",
        "stock_counts",
        ["warehouse_id"],
    )
    op.create_index(
        "ix_stock_counts_status",
        "stock_counts",
        ["status"],
    )

    op.create_table(
        "stock_count_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stock_count_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("storage_location_id", sa.Integer(), nullable=False),
        sa.Column(
            "system_quantity",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
        ),
        sa.Column(
            "counted_quantity",
            sa.Numeric(precision=18, scale=4),
            nullable=True,
        ),
        sa.Column(
            "variance",
            sa.Numeric(precision=18, scale=4),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["stock_count_id"],
            ["stock_counts.id"],
            name="fk_stock_count_lines_count",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["items.id"],
            name="fk_stock_count_lines_item",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["storage_location_id"],
            ["storage_locations.id"],
            name="fk_stock_count_lines_location",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stock_count_lines"),
        sa.UniqueConstraint(
            "stock_count_id",
            "item_id",
            "storage_location_id",
            name="uq_stock_count_lines_item_location",
        ),
    )

    op.create_index(
        "ix_stock_count_lines_count_id",
        "stock_count_lines",
        ["stock_count_id"],
    )
    op.create_index(
        "ix_stock_count_lines_item_id",
        "stock_count_lines",
        ["item_id"],
    )
    op.create_index(
        "ix_stock_count_lines_location_id",
        "stock_count_lines",
        ["storage_location_id"],
    )

    op.execute(
        """
        INSERT INTO warehouses (
            company_id,
            code,
            name,
            warehouse_type,
            location,
            address,
            manager_id,
            is_active,
            is_default,
            created_at,
            updated_at
        )
        SELECT DISTINCT ON (warehouse_items.company_id)
            warehouse_items.company_id,
            'LEGACY',
            'Legacy Warehouse',
            'main',
            'Migrated from legacy warehouse_items',
            NULL,
            NULL,
            TRUE,
            TRUE,
            NOW(),
            NOW()
        FROM warehouse_items
        ORDER BY warehouse_items.company_id, warehouse_items.id
        ON CONFLICT (company_id, code)
        DO UPDATE SET
            name = EXCLUDED.name,
            location = EXCLUDED.location,
            is_active = TRUE,
            updated_at = NOW()
        """
    )

    op.execute(
        """
        INSERT INTO warehouse_zones (
            warehouse_id,
            code,
            name,
            description,
            created_at,
            updated_at
        )
        SELECT
            warehouses.id,
            'LEGACY',
            'Legacy Zone',
            'Migrated from legacy warehouse_items',
            NOW(),
            NOW()
        FROM warehouses
        WHERE warehouses.code = 'LEGACY'
        ON CONFLICT (warehouse_id, code)
        DO UPDATE SET
            name = EXCLUDED.name,
            description = EXCLUDED.description,
            updated_at = NOW()
        """
    )

    op.execute(
        """
        INSERT INTO storage_locations (
            zone_id,
            code,
            name,
            capacity_unit,
            capacity_value,
            is_active,
            is_receiving,
            created_at,
            updated_at
        )
        SELECT
            warehouse_zones.id,
            'LEGACY',
            'Legacy Storage',
            NULL,
            NULL,
            TRUE,
            TRUE,
            NOW(),
            NOW()
        FROM warehouse_zones
        JOIN warehouses
            ON warehouses.id = warehouse_zones.warehouse_id
        WHERE warehouses.code = 'LEGACY'
          AND warehouse_zones.code = 'LEGACY'
        ON CONFLICT (zone_id, code)
        DO UPDATE SET
            name = EXCLUDED.name,
            is_active = TRUE,
            is_receiving = TRUE,
            updated_at = NOW()
        """
    )

    op.execute(
        """
        INSERT INTO item_categories (
            company_id,
            parent_id,
            code,
            name,
            description,
            created_by_user_id,
            created_at,
            updated_at
        )
        SELECT
            warehouse_items.company_id,
            NULL,
            'LEGACY',
            'Legacy Warehouse Items',
            'Migrated from legacy warehouse_items',
            MIN(warehouse_items.owner_id),
            NOW(),
            NOW()
        FROM warehouse_items
        GROUP BY warehouse_items.company_id
        ON CONFLICT (company_id, code)
        DO UPDATE SET
            name = EXCLUDED.name,
            description = EXCLUDED.description,
            updated_at = NOW()
        """
    )

    op.execute(
        """
        INSERT INTO units (
            company_id,
            code,
            name,
            unit_type,
            created_by_user_id,
            created_at,
            updated_at
        )
        SELECT
            warehouse_items.company_id,
            'PCS',
            'Piece',
            'count',
            MIN(warehouse_items.owner_id),
            NOW(),
            NOW()
        FROM warehouse_items
        GROUP BY warehouse_items.company_id
        ON CONFLICT (company_id, code)
        DO UPDATE SET
            name = EXCLUDED.name,
            unit_type = EXCLUDED.unit_type,
            updated_at = NOW()
        """
    )

    op.execute(
        """
        INSERT INTO items (
            company_id,
            item_code,
            name,
            description,
            category_id,
            unit_id,
            model_id,
            specs,
            barcode,
            qr_code,
            item_type,
            is_active,
            is_critical,
            lead_time_days,
            description_embedding,
            created_by_user_id,
            created_at,
            updated_at
        )
        SELECT
            warehouse_items.company_id,
            'LEGACY-WI-' || warehouse_items.id,
            CONCAT_WS(
                ' ',
                'Legacy',
                COALESCE(managed_models.manufacturer, ''),
                COALESCE(managed_models.model, ''),
                warehouse_items.color
            ),
            COALESCE(
                warehouse_items.description,
                'Migrated from legacy warehouse_items'
            ),
            item_categories.id,
            units.id,
            warehouse_items.model_id,
            JSONB_BUILD_OBJECT(
                'legacy_warehouse_item_id',
                warehouse_items.id,
                'legacy_color',
                warehouse_items.color,
                'legacy_unit_current_value',
                warehouse_items.unit_current_value
            ),
            NULL,
            NULL,
            'material',
            TRUE,
            FALSE,
            NULL,
            NULL,
            warehouse_items.owner_id,
            warehouse_items.created_at,
            warehouse_items.updated_at
        FROM warehouse_items
        JOIN item_categories
            ON item_categories.company_id = warehouse_items.company_id
           AND item_categories.code = 'LEGACY'
        JOIN units
            ON units.company_id = warehouse_items.company_id
           AND units.code = 'PCS'
        JOIN managed_models
            ON managed_models.id = warehouse_items.model_id
        ON CONFLICT (company_id, item_code)
        DO UPDATE SET
            name = EXCLUDED.name,
            description = EXCLUDED.description,
            specs = EXCLUDED.specs,
            updated_at = EXCLUDED.updated_at
        """
    )

    op.execute(
        """
        INSERT INTO stock_items (
            company_id,
            item_id,
            storage_location_id,
            quantity_on_hand,
            quantity_reserved,
            quantity_available,
            min_level,
            max_level,
            reorder_point,
            unit_cost,
            unit_cost_currency_id,
            unit_cost_base,
            created_at,
            updated_at
        )
        SELECT
            warehouse_items.company_id,
            items.id,
            storage_locations.id,
            warehouse_items.count,
            0,
            warehouse_items.count,
            NULL,
            NULL,
            NULL,
            COALESCE(warehouse_items.unit_cost, 0),
            COALESCE(
                companies.base_currency_id,
                company_currency.id,
                fallback_currency.id
            ),
            COALESCE(warehouse_items.unit_cost, 0),
            warehouse_items.created_at,
            warehouse_items.updated_at
        FROM warehouse_items
        JOIN items
            ON items.company_id = warehouse_items.company_id
           AND items.item_code = 'LEGACY-WI-' || warehouse_items.id
        JOIN companies
            ON companies.id = warehouse_items.company_id
        LEFT JOIN currencies AS company_currency
            ON company_currency.code = companies.base_currency
        LEFT JOIN currencies AS fallback_currency
            ON fallback_currency.code = 'IRT'
        JOIN warehouses
            ON warehouses.company_id = warehouse_items.company_id
           AND warehouses.code = 'LEGACY'
        JOIN warehouse_zones
            ON warehouse_zones.warehouse_id = warehouses.id
           AND warehouse_zones.code = 'LEGACY'
        JOIN storage_locations
            ON storage_locations.zone_id = warehouse_zones.id
           AND storage_locations.code = 'LEGACY'
        ON CONFLICT (item_id, storage_location_id)
        DO UPDATE SET
            quantity_on_hand = EXCLUDED.quantity_on_hand,
            quantity_available = EXCLUDED.quantity_available,
            unit_cost = EXCLUDED.unit_cost,
            unit_cost_currency_id = EXCLUDED.unit_cost_currency_id,
            unit_cost_base = EXCLUDED.unit_cost_base,
            updated_at = EXCLUDED.updated_at
        """
    )

    op.execute(
        """
        INSERT INTO stock_movements (
            company_id,
            movement_number,
            movement_type,
            item_id,
            from_location_id,
            to_location_id,
            quantity,
            unit_cost,
            currency_id,
            unit_cost_base,
            base_currency_id,
            exchange_rate_used,
            reference_type,
            reference_id,
            reference_line_id,
            performed_by_user_id,
            movement_date,
            notes,
            created_at
        )
        SELECT
            warehouse_items.company_id,
            'MOV-'
            || TO_CHAR(
                COALESCE(warehouse_items.created_at, NOW()),
                'YYYY'
            )
            || '-'
            || LPAD(
                NEXTVAL('stock_movement_number_seq')::TEXT,
                5,
                '0'
            ),
            'receipt',
            items.id,
            NULL,
            storage_locations.id,
            warehouse_items.count,
            COALESCE(warehouse_items.unit_cost, 0),
            COALESCE(
                companies.base_currency_id,
                company_currency.id,
                fallback_currency.id
            ),
            COALESCE(warehouse_items.unit_cost, 0),
            COALESCE(
                companies.base_currency_id,
                company_currency.id,
                fallback_currency.id
            ),
            1,
            'legacy_migration',
            warehouse_items.id,
            NULL,
            warehouse_items.owner_id,
            COALESCE(warehouse_items.created_at, NOW()),
            'Migrated from legacy warehouse_items',
            NOW()
        FROM warehouse_items
        JOIN items
            ON items.company_id = warehouse_items.company_id
           AND items.item_code = 'LEGACY-WI-' || warehouse_items.id
        JOIN companies
            ON companies.id = warehouse_items.company_id
        LEFT JOIN currencies AS company_currency
            ON company_currency.code = companies.base_currency
        LEFT JOIN currencies AS fallback_currency
            ON fallback_currency.code = 'IRT'
        JOIN warehouses
            ON warehouses.company_id = warehouse_items.company_id
           AND warehouses.code = 'LEGACY'
        JOIN warehouse_zones
            ON warehouse_zones.warehouse_id = warehouses.id
           AND warehouse_zones.code = 'LEGACY'
        JOIN storage_locations
            ON storage_locations.zone_id = warehouse_zones.id
           AND storage_locations.code = 'LEGACY'
        WHERE warehouse_items.count > 0
        """
    )

    op.rename_table("warehouse_items", "warehouse_items_legacy_archive")


def downgrade() -> None:
    raise RuntimeError(
        "Warehouse migration downgrade is unsupported because legacy "
        "warehouse_items data is transformed into material and stock records."
    )
