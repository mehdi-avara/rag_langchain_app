from __future__ import annotations

from assistant.registry import register_toolset
from shared.commerce_assistant import (
    ConfiguredCommerceToolSet,
    PayloadField,
    ReferenceFieldSpec,
    SearchSpec,
    WriteSpec,
    goods_receipt_required,
    goods_receipt_items_from_slots,
)

from .search.service import search_goods_receipt_hits

MODULE = "goods_receipt_management"
API_PREFIX = "/goods-receipts"

P_READ = "goods_receipt_management:read"
P_SEARCH = "goods_receipt_management:search"
P_ASK = "goods_receipt_management:ask"
P_CREATE = "goods_receipt_management:create"
P_UPDATE = "goods_receipt_management:update"


class GoodsReceiptAssistantToolSet(ConfiguredCommerceToolSet):
    module = MODULE
    search_specs = (
        SearchSpec(
            intent="search_goods_receipts",
            description="Find goods receipt notes by GRN number, date, delivery note, warehouse, status, or item.",
            permission=P_SEARCH,
            search_fn=search_goods_receipt_hits,
            resource_type="goods_receipt",
            id_attr="goods_receipt_id",
            id_param="goods_receipt_ids",
            title_fields=("grn_number", "status", "receipt_date", "delivery_note_number"),
            module=MODULE,
            ask_intent="ask_goods_receipts",
            ask_description="Answer a grounded question using goods receipt note records as references.",
            ask_permission=P_ASK,
            citation_prefix="grn",
        ),
    )
    write_specs = (
        WriteSpec(
            intent="add_goods_receipt",
            description="Create a goods receipt note draft.",
            permission=P_CREATE,
            target_action="create_goods_receipt",
            method="POST",
            endpoint=API_PREFIX,
            required=("purchase_phase_id", "receipt_date"),
            item_builder=goods_receipt_items_from_slots,
            validate=goods_receipt_required,
            reference_fields=(
                ReferenceFieldSpec(
                    field="purchase_phase_id",
                    resource_key="purchase_phase",
                    raw_aliases=("purchase_phase_query", "phase_query", "phase", "purchase_order", "po"),
                    explicit_aliases=("purchase_phase_id", "phase_id"),
                    missing_label="purchase phase",
                ),
                ReferenceFieldSpec(
                    field="warehouse_id",
                    resource_key="warehouse",
                    raw_aliases=("warehouse_query", "warehouse_name", "warehouse"),
                    explicit_aliases=("warehouse_id",),
                    missing_label="warehouse",
                ),
                ReferenceFieldSpec(
                    field="purchase_phase_item_id",
                    resource_key="purchase_phase_item",
                    raw_aliases=("purchase_phase_item_query", "phase_item_query", "po_item", "purchase_item", "item_query", "item_name", "item"),
                    explicit_aliases=("purchase_phase_item_id", "phase_item_id"),
                    missing_label="purchase phase item",
                    collection="items",
                ),
                ReferenceFieldSpec(
                    field="item_id",
                    resource_key="material_item",
                    raw_aliases=("item_query", "item_name", "item", "material_item", "part", "part_name"),
                    explicit_aliases=("item_id", "material_item_id"),
                    missing_label="item",
                    collection="items",
                ),
                ReferenceFieldSpec(
                    field="storage_location_id",
                    resource_key="storage_location",
                    raw_aliases=("location_query", "storage_location_query", "location", "storage_location"),
                    explicit_aliases=("storage_location_id", "location_id"),
                    missing_label="storage location",
                    collection="items",
                ),
            ),
            fields=(
                PayloadField("purchase_phase_id", aliases=("phase_id",), kind="int"),
                PayloadField("receipt_date", aliases=("date",)),
                PayloadField("delivery_note_number", aliases=("delivery_note",)),
                PayloadField("warehouse_id", aliases=("warehouse",), kind="int"),
                PayloadField("notes", aliases=("description",)),
            ),
        ),
        WriteSpec(
            intent="update_goods_receipt",
            description="Update an existing draft goods receipt note.",
            permission=P_UPDATE,
            target_action="update_goods_receipt",
            method="PATCH",
            endpoint=f"{API_PREFIX}/{{entity_id}}",
            id_aliases=("goods_receipt_id", "grn_id", "id"),
            reference_fields=(
                ReferenceFieldSpec(
                    field="warehouse_id",
                    resource_key="warehouse",
                    raw_aliases=("warehouse_query", "warehouse_name", "warehouse"),
                    explicit_aliases=("warehouse_id",),
                    missing_label="warehouse",
                ),
            ),
            fields=(
                PayloadField("receipt_date", aliases=("date",)),
                PayloadField("delivery_note_number", aliases=("delivery_note",)),
                PayloadField("warehouse_id", aliases=("warehouse",), kind="int"),
                PayloadField("notes", aliases=("description",)),
            ),
        ),
    )


def register() -> GoodsReceiptAssistantToolSet:
    toolset = GoodsReceiptAssistantToolSet()
    register_toolset(toolset)
    return toolset


register()
