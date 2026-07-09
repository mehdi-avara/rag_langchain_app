from __future__ import annotations

from assistant.module_interface import Candidate, FunctionSearchProvider, ResourceSpec, register_resource
from assistant.registry import register_toolset
from model_management.services import search_models_for_assistant
from shared.commerce_assistant import (
    ConfiguredCommerceToolSet,
    PayloadField,
    ReferenceFieldSpec,
    SearchSpec,
    WriteSpec,
)

from .models import ItemType
from .search.service import search_item_hits
from .services import search_categories_for_assistant, search_units_for_assistant

MODULE = "material_management"
API_PREFIX = "/materials"

P_READ = "material_management:read"
P_SEARCH = "material_management:search"
P_ASK = "material_management:ask"
P_CREATE = "material_management:create"
P_UPDATE = "material_management:update"
P_MODELS_READ = "models:read"
P_MODELS_CREATE = "models:create"


def _search_items_for_resolution(db, current_user, query_text, ids=None, limit=10):
    return search_item_hits(
        db=db,
        current_user=current_user,
        query_text=query_text,
        mode="hybrid",
        item_ids=ids,
        limit=limit,
    )


def _item_to_candidate(item) -> Candidate:
    code = getattr(item, "item_code", None)
    name = getattr(item, "name", None)
    item_type = getattr(item, "item_type", None)
    label = " - ".join(part for part in (code, name, item_type) if part)
    return Candidate(
        id=item.item_id,
        match_text=name or code or "",
        label=label or f"Item #{item.item_id}",
        data=item.model_dump(mode="json") if hasattr(item, "model_dump") else {
            "item_id": item.item_id,
            "item_code": code,
            "name": name,
            "item_type": item_type,
        },
    )


def _category_to_candidate(category) -> Candidate:
    code = getattr(category, "code", None)
    name = getattr(category, "name", None)
    description = getattr(category, "description", None)
    label = " - ".join(part for part in (code, name) if part)
    return Candidate(
        id=category.id,
        match_text=name or code or "",
        label=label or f"Category #{category.id}",
        data={
            "id": category.id,
            "code": code,
            "name": name,
            "description": description,
        },
    )


def _unit_to_candidate(unit) -> Candidate:
    code = getattr(unit, "code", None)
    name = getattr(unit, "name", None)
    unit_type = getattr(unit, "unit_type", None)
    label = " - ".join(part for part in (code, name, unit_type) if part)
    return Candidate(
        id=unit.id,
        match_text=name or code or "",
        label=label or f"Unit #{unit.id}",
        data={
            "id": unit.id,
            "code": code,
            "name": name,
            "unit_type": unit_type,
        },
    )


def _model_to_candidate(model) -> Candidate:
    label = " - ".join(
        part for part in (
            getattr(model, "manufacturer", None),
            getattr(model, "model", None),
            getattr(model, "type", None),
        )
        if part
    )
    return Candidate(
        id=model.id,
        match_text=getattr(model, "model", None) or getattr(model, "manufacturer", None) or "",
        label=label or f"Model #{model.id}",
        data={
            "id": model.id,
            "manufacturer": getattr(model, "manufacturer", None),
            "model": getattr(model, "model", None),
            "type": getattr(model, "type", None),
            "description": getattr(model, "description", None),
        },
    )


def register_material_resources() -> None:
    register_resource(ResourceSpec(
        key="material_item",
        read_permission=P_SEARCH,
        provider=FunctionSearchProvider(_search_items_for_resolution, _item_to_candidate),
        create_permission=P_CREATE,
        create_endpoint=API_PREFIX,
        suggestion_from=lambda raw, slots: {
            "name": raw,
            "item_code": slots.get("item_code") or raw,
        },
    ))
    register_resource(ResourceSpec(
        key="item_category",
        read_permission=P_READ,
        provider=FunctionSearchProvider(search_categories_for_assistant, _category_to_candidate),
        create_permission=P_CREATE,
        create_endpoint=f"{API_PREFIX}/categories",
        suggestion_from=lambda raw, slots: {
            "code": slots.get("category_code") or raw,
            "name": raw,
        },
    ))
    register_resource(ResourceSpec(
        key="material_unit",
        read_permission=P_READ,
        provider=FunctionSearchProvider(search_units_for_assistant, _unit_to_candidate),
        create_permission=P_CREATE,
        create_endpoint=f"{API_PREFIX}/units",
        suggestion_from=lambda raw, slots: {
            "code": slots.get("unit_code") or raw,
            "name": raw,
        },
    ))
    register_resource(ResourceSpec(
        key="managed_model",
        read_permission=P_MODELS_READ,
        provider=FunctionSearchProvider(search_models_for_assistant, _model_to_candidate),
        create_permission=P_MODELS_CREATE,
        create_endpoint="/models",
        suggestion_from=lambda raw, slots: {
            "manufacturer": slots.get("manufacturer") or "",
            "model": raw,
            "type": slots.get("model_type") or slots.get("type"),
        },
    ))


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
            reference_fields=(
                ReferenceFieldSpec(
                    field="category_id",
                    resource_key="item_category",
                    raw_aliases=("category_query", "category_name", "category_code", "category"),
                    explicit_aliases=("category_id",),
                    missing_label="category",
                ),
                ReferenceFieldSpec(
                    field="unit_id",
                    resource_key="material_unit",
                    raw_aliases=("unit_query", "unit_name", "unit_code", "unit"),
                    explicit_aliases=("unit_id",),
                    missing_label="unit",
                ),
                ReferenceFieldSpec(
                    field="model_id",
                    resource_key="managed_model",
                    raw_aliases=("model_query", "model_name", "model"),
                    explicit_aliases=("model_id",),
                    missing_label="model",
                ),
            ),
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
            reference_fields=(
                ReferenceFieldSpec(
                    field="category_id",
                    resource_key="item_category",
                    raw_aliases=("category_query", "category_name", "category_code", "category"),
                    explicit_aliases=("category_id",),
                    missing_label="category",
                ),
                ReferenceFieldSpec(
                    field="unit_id",
                    resource_key="material_unit",
                    raw_aliases=("unit_query", "unit_name", "unit_code", "unit"),
                    explicit_aliases=("unit_id",),
                    missing_label="unit",
                ),
                ReferenceFieldSpec(
                    field="model_id",
                    resource_key="managed_model",
                    raw_aliases=("model_query", "model_name", "model"),
                    explicit_aliases=("model_id",),
                    missing_label="model",
                ),
            ),
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
    register_material_resources()
    return toolset


register()
