from __future__ import annotations

from assistant.module_interface import Candidate, FunctionSearchProvider, ResourceSpec, register_resource
from assistant.registry import register_toolset
from shared.assistant_resources import register_shared_assistant_resources
from shared.commerce_assistant import ConfiguredCommerceToolSet, PayloadField, ReferenceFieldSpec, SearchSpec, WriteSpec

from .models import StockMovementType
from .search.service import search_warehouse_hits
from .services import list_storage_locations, list_warehouses

MODULE = "warehouse_management"
API_PREFIX = "/warehouse"

P_STOCK_READ = "warehouse_management:stock:read"
P_MOVEMENT_READ = "warehouse_management:movements:read"
P_SEARCH = "warehouse_management:search"
P_ASK = "warehouse_management:ask"
P_STOCK_ADJUST = "warehouse_management:movements:create"


def _search_warehouses_for_resolution(db, current_user, query_text, ids=None, limit=10):
    query = (query_text or "").strip().lower()
    rows = list_warehouses(db=db, current_user=current_user, active_only=True)
    if ids is not None:
        wanted = set(ids)
        rows = [row for row in rows if row.id in wanted]
    if query:
        rows = [
            row for row in rows
            if query in (row.code or "").lower() or query in (row.name or "").lower()
        ]
    return rows[:limit]


def _warehouse_to_candidate(warehouse) -> Candidate:
    return Candidate(
        id=warehouse.id,
        match_text=warehouse.name or warehouse.code or "",
        label=" - ".join(part for part in (warehouse.code, warehouse.name) if part) or f"Warehouse #{warehouse.id}",
        data={"id": warehouse.id, "code": warehouse.code, "name": warehouse.name},
    )


def _search_locations_for_resolution(db, current_user, query_text, ids=None, limit=10):
    query = (query_text or "").strip().lower()
    rows = list_storage_locations(db=db, current_user=current_user, active_only=True)
    if ids is not None:
        wanted = set(ids)
        rows = [row for row in rows if row.id in wanted]
    if query:
        rows = [
            row for row in rows
            if query in (row.code or "").lower() or query in (row.name or "").lower()
        ]
    return rows[:limit]


def _location_to_candidate(location) -> Candidate:
    return Candidate(
        id=location.id,
        match_text=location.name or location.code or "",
        label=" - ".join(part for part in (location.code, location.name) if part) or f"Location #{location.id}",
        data={"id": location.id, "code": location.code, "name": location.name, "zone_id": location.zone_id},
    )


def register_warehouse_resources() -> None:
    register_resource(ResourceSpec(
        key="warehouse",
        read_permission=P_STOCK_READ,
        provider=FunctionSearchProvider(_search_warehouses_for_resolution, _warehouse_to_candidate),
    ))
    register_resource(ResourceSpec(
        key="storage_location",
        read_permission=P_STOCK_READ,
        provider=FunctionSearchProvider(_search_locations_for_resolution, _location_to_candidate),
    ))


class WarehouseAssistantToolSet(ConfiguredCommerceToolSet):
    module = MODULE
    search_specs = (
        SearchSpec(
            intent="search_stock",
            description="Find warehouse stock by item, warehouse, location, code, or availability.",
            permission=P_SEARCH,
            search_fn=search_warehouse_hits,
            resource_type="stock",
            id_attr="stock_item_id",
            id_param="stock_item_ids",
            title_fields=("item_code", "item_name", "warehouse_code", "storage_location_code"),
            module=MODULE,
            ask_intent="ask_warehouse_stock",
            ask_description="Answer a grounded question using warehouse stock records as references.",
            ask_permission=P_ASK,
            citation_prefix="stock",
            extra_params={
                "warehouse_id": ("int", "warehouse"),
                "storage_location_id": ("int", "location_id", "storage_location"),
            },
        ),
    )
    write_specs = (
        WriteSpec(
            intent="add_stock_adjustment",
            description="Create a manual stock adjustment draft.",
            permission=P_STOCK_ADJUST,
            target_action="create_stock_adjustment",
            method="POST",
            endpoint=f"{API_PREFIX}/movements",
            required=(
                "item_id",
                "quantity",
                "unit_cost",
                "currency_id",
                "unit_cost_base",
                "base_currency_id",
                "exchange_rate_used",
            ),
            reference_fields=(
                ReferenceFieldSpec(
                    field="item_id",
                    resource_key="material_item",
                    raw_aliases=("item_query", "item_name", "item", "material_item", "part", "part_name"),
                    explicit_aliases=("item_id", "material_item_id"),
                    missing_label="item",
                ),
                ReferenceFieldSpec(
                    field="from_location_id",
                    resource_key="storage_location",
                    raw_aliases=("from_location_query", "from_location",),
                    explicit_aliases=("from_location_id",),
                    missing_label="source storage location",
                ),
                ReferenceFieldSpec(
                    field="to_location_id",
                    resource_key="storage_location",
                    raw_aliases=("to_location_query", "to_location", "location_query", "storage_location_query", "location", "storage_location"),
                    explicit_aliases=("to_location_id", "storage_location_id", "location_id"),
                    missing_label="storage location",
                ),
                ReferenceFieldSpec(
                    field="currency_id",
                    resource_key="currency",
                    raw_aliases=("currency_query", "currency_code", "currency"),
                    explicit_aliases=("currency_id",),
                    missing_label="currency",
                ),
                ReferenceFieldSpec(
                    field="base_currency_id",
                    resource_key="currency",
                    raw_aliases=("base_currency_query", "base_currency_code", "base_currency"),
                    explicit_aliases=("base_currency_id",),
                    missing_label="base currency",
                ),
            ),
            fields=(
                PayloadField("movement_type", kind="enum", enum_values=tuple(item.value for item in StockMovementType), default=StockMovementType.ADJUSTMENT.value),
                PayloadField("item_id", aliases=("material_item_id",), kind="int"),
                PayloadField("item_query", aliases=("item_name", "item", "material_item", "part", "part_name")),
                PayloadField("from_location_id", aliases=("from_location",), kind="int"),
                PayloadField("to_location_id", aliases=("to_location", "storage_location_id", "location_id"), kind="int"),
                PayloadField("quantity", aliases=("qty",), kind="decimal"),
                PayloadField("unit_cost", kind="decimal"),
                PayloadField("currency_id", aliases=("currency",), kind="int"),
                PayloadField("unit_cost_base", kind="decimal"),
                PayloadField("base_currency_id", aliases=("base_currency",), kind="int"),
                PayloadField("exchange_rate_used", aliases=("exchange_rate",), kind="decimal"),
                PayloadField("notes", aliases=("description",)),
            ),
        ),
    )


def register() -> WarehouseAssistantToolSet:
    toolset = WarehouseAssistantToolSet()
    register_toolset(toolset)
    register_shared_assistant_resources()
    register_warehouse_resources()
    return toolset


register()
