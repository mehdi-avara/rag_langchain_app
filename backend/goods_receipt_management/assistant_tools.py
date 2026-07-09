from __future__ import annotations

from assistant.registry import register_toolset
from shared.commerce_assistant import (
    ConfiguredCommerceToolSet,
    PayloadField,
    SearchSpec,
    WriteSpec,
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
