from __future__ import annotations

from assistant.registry import register_toolset
from shared.commerce_assistant import ConfiguredCommerceToolSet, PayloadField, SearchSpec, WriteSpec

from .models import StockMovementType
from .search.service import search_warehouse_hits

MODULE = "warehouse_management"
API_PREFIX = "/warehouse"

P_STOCK_READ = "warehouse_management:stock:read"
P_MOVEMENT_READ = "warehouse_management:movements:read"
P_SEARCH = "warehouse_management:search"
P_ASK = "warehouse_management:ask"
P_STOCK_ADJUST = "warehouse_management:movements:create"


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
            fields=(
                PayloadField("movement_type", kind="enum", enum_values=tuple(item.value for item in StockMovementType), default=StockMovementType.ADJUSTMENT.value),
                PayloadField("item_id", aliases=("material_item_id",), kind="int"),
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
    return toolset


register()
