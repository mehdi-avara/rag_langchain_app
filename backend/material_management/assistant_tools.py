from __future__ import annotations

from assistant.registry import register_toolset
from shared.commerce_assistant import ConfiguredCommerceToolSet, PayloadField, SearchSpec, WriteSpec

from .models import ItemType
from .search.service import search_item_hits

MODULE = "material_management"
API_PREFIX = "/materials"

P_READ = "material_management:read"
P_SEARCH = "material_management:search"
P_ASK = "material_management:ask"
P_CREATE = "material_management:create"
P_UPDATE = "material_management:update"


class MaterialAssistantToolSet(ConfiguredCommerceToolSet):
    module = MODULE
    search_specs = (
        SearchSpec(
            intent="search_items",
            description="Find material items by code, name, description, category, type, model, or criticality.",
            permission=P_SEARCH,
            search_fn=search_item_hits,
            resource_type="item",
            id_attr="item_id",
            id_param="item_ids",
            title_fields=("item_code", "name", "item_type"),
            module=MODULE,
            ask_intent="ask_items",
            ask_description="Answer a grounded question using material item records as references.",
            ask_permission=P_ASK,
            citation_prefix="item",
            extra_params={
                "category_id": ("int", "category"),
                "item_type": ("str", "type"),
                "is_active": ("bool", "active"),
            },
        ),
    )
    write_specs = (
        WriteSpec(
            intent="add_item",
            description="Create a material item draft.",
            permission=P_CREATE,
            target_action="create_item",
            method="POST",
            endpoint=API_PREFIX,
            required=("item_code", "name", "category_id", "unit_id"),
            fields=(
                PayloadField("item_code", aliases=("code",)),
                PayloadField("name", aliases=("item_name",)),
                PayloadField("description"),
                PayloadField("category_id", aliases=("category",), kind="int"),
                PayloadField("unit_id", aliases=("unit",), kind="int"),
                PayloadField("model_id", aliases=("model",), kind="int"),
                PayloadField("specs", kind="raw"),
                PayloadField("barcode"),
                PayloadField("qr_code"),
                PayloadField("item_type", kind="enum", enum_values=tuple(item.value for item in ItemType), default=ItemType.MATERIAL.value),
                PayloadField("is_active", aliases=("active",), kind="bool", default=True),
                PayloadField("is_critical", aliases=("critical",), kind="bool", default=False),
                PayloadField("lead_time_days", aliases=("lead_time",), kind="int"),
            ),
        ),
        WriteSpec(
            intent="update_item",
            description="Update an existing material item draft.",
            permission=P_UPDATE,
            target_action="update_item",
            method="PATCH",
            endpoint=f"{API_PREFIX}/{{entity_id}}",
            id_aliases=("item_id", "id"),
            fields=(
                PayloadField("item_code", aliases=("code",)),
                PayloadField("name", aliases=("item_name",)),
                PayloadField("description"),
                PayloadField("category_id", aliases=("category",), kind="int"),
                PayloadField("unit_id", aliases=("unit",), kind="int"),
                PayloadField("model_id", aliases=("model",), kind="int"),
                PayloadField("specs", kind="raw"),
                PayloadField("barcode"),
                PayloadField("qr_code"),
                PayloadField("item_type", kind="enum", enum_values=tuple(item.value for item in ItemType)),
                PayloadField("is_active", aliases=("active",), kind="bool"),
                PayloadField("is_critical", aliases=("critical",), kind="bool"),
                PayloadField("lead_time_days", aliases=("lead_time",), kind="int"),
            ),
        ),
    )


def register() -> MaterialAssistantToolSet:
    toolset = MaterialAssistantToolSet()
    register_toolset(toolset)
    return toolset


register()
