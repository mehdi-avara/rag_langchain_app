from __future__ import annotations

import re

from assistant.module_interface import (
    Candidate,
    FunctionSearchProvider,
    ResourceSpec,
    register_resource,
)
from assistant.rbac import has_permission
from assistant.registry import register_toolset
from shared.commerce_assistant import (
    ConfiguredCommerceToolSet,
    PayloadField,
    ReferenceFieldSpec,
    SearchSpec,
    WriteSpec,
)

from .models import ItemType
from .search.service import search_item_hits
from .services import (
    find_model_candidates_for_item_reference,
    find_model_summary_for_item_reference,
    list_items,
    search_categories_for_assistant,
    search_units_for_assistant,
)

MODULE = "material_management"
API_PREFIX = "/materials"

P_READ = "material_management:read"
P_SEARCH = "material_management:search"
P_ASK = "material_management:ask"
P_CREATE = "material_management:create"
P_UPDATE = "material_management:update"
P_MODEL_READ = "models:read"
P_MODEL_CREATE = "models:create"


def _context_text(context: dict, *keys: str) -> str | None:
    for key in keys:
        value = context.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _context_int(context: dict, *keys: str) -> int | None:
    for key in keys:
        value = context.get(key)
        if isinstance(value, bool):
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def _model_reference_requested(raw: str, context: dict) -> bool:
    if any(
        _context_text(context, key)
        for key in (
            "model",
            "model_name",
            "equipment_model",
            "manufacturer",
            "make",
            "brand",
            "selected_model_id",
            "managed_model_id",
            "model_id",
        )
    ):
        return True
    return bool(
        re.search(r"(?=[\w.-]*[A-Za-z])(?=[\w.-]*\d)[\w.-]{3,}", raw or "")
        or re.search(r"(?:\bmodel\b|مدل)", raw or "", flags=re.IGNORECASE)
    )


def _requested_item_type(
    raw: str, context: dict, matched_model: dict | None
) -> str | None:
    explicit = _context_text(context, "item_type", "material_type")
    if explicit:
        return explicit

    normalized = (raw or "").lower()
    part_markers = ("spare", "part", "seal", "bearing", "قطعه", "یدکی")
    if any(marker in normalized for marker in part_markers):
        return ItemType.SPARE_PART.value

    equipment_markers = (
        "full equipment",
        "complete equipment",
        "whole equipment",
        "دستگاه کامل",
        "تجهیز کامل",
    )
    model_type = (
        str(
            (matched_model or {}).get("type")
            or _context_text(context, "model_type", "equipment_type")
            or ""
        )
        .strip()
        .lower()
    )
    if any(marker in normalized for marker in equipment_markers) or (
        model_type
        and (model_type in normalized or _model_reference_requested(raw, context))
    ):
        return ItemType.EQUIPMENT.value
    return None


def _model_candidates(db, current_user, raw: str, context: dict) -> list[dict]:
    if not has_permission(current_user, P_MODEL_READ):
        return []

    selected_model_id = _context_int(
        context,
        "selected_model_id",
        "managed_model_id",
        "model_id",
    )
    if selected_model_id is not None:
        selected = find_model_summary_for_item_reference(
            db,
            current_user,
            selected_model_id,
        )
        return [selected] if selected is not None else []

    return find_model_candidates_for_item_reference(
        db,
        current_user,
        query_text=raw,
        model_name=_context_text(
            context,
            "model_name",
            "model",
            "equipment_model",
        ),
        manufacturer=_context_text(
            context,
            "manufacturer",
            "make",
            "brand",
        ),
        model_type=_context_text(
            context,
            "model_type",
            "equipment_type",
        ),
        limit=5,
    )


def _search_items_for_resolution(
    db,
    current_user,
    query_text,
    ids=None,
    limit=10,
    context=None,
):
    context = dict(context or {})
    selected_model_id = _context_int(
        context,
        "selected_model_id",
        "managed_model_id",
        "model_id",
    )
    model_name = _context_text(context, "model_name", "model", "equipment_model")
    manufacturer = _context_text(context, "manufacturer", "make", "brand")
    model_type = _context_text(context, "model_type", "equipment_type")
    item_type = _requested_item_type(query_text, context, None)

    if selected_model_id is not None:
        hits = list_items(
            db,
            current_user,
            item_type=item_type,
            is_active=True,
            model_id=selected_model_id,
            limit=limit,
        )
    else:
        hits = search_item_hits(
            db=db,
            current_user=current_user,
            query_text=query_text,
            mode="hybrid",
            item_ids=ids,
            item_type=item_type,
            model_name=model_name,
            manufacturer=manufacturer,
            model_type=model_type,
            limit=limit,
        )
    return hits


class _MaterialItemSearchProvider(FunctionSearchProvider):
    accepts_context = True

    def search(self, *, db, user, query, ids=None, limit=10, context=None):
        rows = self._search_fn(
            db,
            user,
            query,
            ids=ids,
            limit=limit,
            context=context,
        )
        candidates = [self._to_candidate(row) for row in rows]
        if (
            _context_int(
                context or {},
                "selected_model_id",
                "managed_model_id",
                "model_id",
            )
            is not None
        ):
            # The user explicitly selected the managed model. Every returned
            # item is already tenant-, model-, activity-, and item-type-scoped;
            # make the resolver choose a sole item or expose multiple choices
            # without requiring a cross-language name token overlap.
            for candidate in candidates:
                candidate.match_text = query
        return candidates


def _missing_material_suggestion(db, current_user, raw: str, context: dict):
    if not _model_reference_requested(raw, context):
        return None

    candidates = _model_candidates(db, current_user, raw, context)
    selected_model_id = _context_int(
        context,
        "selected_model_id",
        "managed_model_id",
        "model_id",
    )
    matched_model = candidates[0] if selected_model_id and candidates else None

    requested_manufacturer = _context_text(
        context,
        "manufacturer",
        "make",
        "brand",
    )
    requested_model_name = _context_text(
        context,
        "model_name",
        "model",
        "equipment_model",
    )
    requested_model_type = _context_text(
        context,
        "model_type",
        "equipment_type",
    )
    requested_name = _context_text(
        context,
        "item_name",
        "item",
        "material_item",
        "part",
    )

    if matched_model is None:
        payload = {
            "name": requested_name or raw,
        }
        item_type = _requested_item_type(raw, context, None)
        if item_type:
            payload["item_type"] = item_type

        model_payload = {
            "manufacturer": requested_manufacturer or "",
            "model": requested_model_name or "",
            "type": requested_model_type or "",
        }
        create_model_suggestion = None
        if has_permission(current_user, P_MODEL_CREATE):
            create_model_suggestion = {
                "resource": "managed_model",
                "method": "POST",
                "endpoint": "/models/",
                "permission": P_MODEL_CREATE,
                "payload": model_payload,
            }

        if candidates:
            labels = ", ".join(
                " ".join(
                    part
                    for part in (
                        str(candidate.get("manufacturer") or "").strip(),
                        str(candidate.get("model") or "").strip(),
                        str(candidate.get("type") or "").strip(),
                    )
                    if part
                )
                for candidate in candidates[:3]
            )
            message = (
                f"I found these exact or similar equipment models: {labels}. "
                "Choose the correct model, or create a new one if none match."
            )
        else:
            message = (
                "I could not find an exact or similar equipment model. "
                "Create a new model to continue."
            )

        return {
            "payload": payload,
            "requires_model_selection": True,
            "model_candidates": candidates,
            "requested_model": model_payload,
            "create_model_suggestion": create_model_suggestion,
            "message": message,
        }

    manufacturer = str(matched_model.get("manufacturer") or "").strip()
    model_name = str(matched_model.get("model") or "").strip()
    model_type = str(matched_model.get("type") or "").strip()
    name = requested_name or " ".join(
        part for part in (manufacturer, model_name, model_type) if part
    )
    item_type = _requested_item_type(raw, context, matched_model)
    payload = {
        "name": name or raw,
        "model_id": matched_model["id"],
        "model_name": " ".join(part for part in (manufacturer, model_name) if part),
    }
    if item_type:
        payload["item_type"] = item_type

    model_label = " ".join(
        part for part in (manufacturer, model_name, model_type) if part
    )
    return {
        "payload": payload,
        "matched_model": matched_model,
        "message": (
            f"I found the equipment model {model_label}, but no matching material "
            "item. Do you want to create a material item linked to this model?"
        ),
    }


def _item_to_candidate(item) -> Candidate:
    item_id = getattr(item, "item_id", None) or getattr(item, "id", None)
    code = getattr(item, "item_code", None)
    name = getattr(item, "name", None)
    item_type = getattr(item, "item_type", None)
    model = getattr(item, "model", None)
    manufacturer = getattr(model, "manufacturer", None)
    model_name = getattr(model, "model", None)
    model_type = getattr(model, "type", None)
    label = " - ".join(
        part
        for part in (
            code,
            name,
            manufacturer,
            model_name,
            model_type,
            item_type,
        )
        if part
    )
    return Candidate(
        id=item_id,
        match_text=" ".join(
            part for part in (name, code, manufacturer, model_name, model_type) if part
        ),
        label=label or f"Item #{item.item_id}",
        data=(
            item.model_dump(mode="json")
            if hasattr(item, "model_dump")
            else {
                "item_id": item_id,
                "item_code": code,
                "name": name,
                "item_type": item_type,
            }
        ),
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


def register_material_resources() -> None:
    register_resource(
        ResourceSpec(
            key="material_item",
            read_permission=P_SEARCH,
            provider=_MaterialItemSearchProvider(
                _search_items_for_resolution, _item_to_candidate
            ),
            create_permission=P_CREATE,
            create_endpoint=API_PREFIX,
            suggestion_from=lambda raw, slots: {
                "name": raw,
                "item_code": slots.get("item_code") or raw,
            },
            missing_suggestion_from=_missing_material_suggestion,
        )
    )
    register_resource(
        ResourceSpec(
            key="item_category",
            read_permission=P_READ,
            provider=FunctionSearchProvider(
                search_categories_for_assistant, _category_to_candidate
            ),
            create_permission=P_CREATE,
            create_endpoint=f"{API_PREFIX}/categories",
            suggestion_from=lambda raw, slots: {
                "code": slots.get("category_code") or raw,
                "name": raw,
            },
        )
    )
    register_resource(
        ResourceSpec(
            key="material_unit",
            read_permission=P_READ,
            provider=FunctionSearchProvider(
                search_units_for_assistant, _unit_to_candidate
            ),
            create_permission=P_CREATE,
            create_endpoint=f"{API_PREFIX}/units",
            suggestion_from=lambda raw, slots: {
                "code": slots.get("unit_code") or raw,
                "name": raw,
            },
        )
    )


def _normalize_material_write_slots(
    slots: dict,
) -> dict:
    normalized = dict(slots or {})

    alias_pairs = (
        ("item_name", "name"),
        ("item_description", "description"),
        ("item_category", "category"),
        ("item_unit", "unit"),
        ("item_critical", "is_critical"),
    )

    for source, target in alias_pairs:
        if target not in normalized and normalized.get(source) is not None:
            normalized[target] = normalized[source]

    item_code = normalized.get("item_code")

    if item_code is not None:
        normalized["item_code"] = str(item_code).translate(
            str.maketrans(
                "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
                "01234567890123456789",
            )
        )

    unit_value = normalized.get("unit")

    if unit_value is not None:
        unit_text = (
            str(unit_value)
            .strip()
            .lower()
            .replace("‌", " ")
            .replace("ي", "ی")
            .replace("ك", "ک")
        )

        compact_unit = "".join(unit_text.split())

        if compact_unit in {
            "kg",
            "kgs",
            "kilogram",
            "کیلو",
            "کیلوگرم",
        }:
            normalized["unit"] = "kilogram"

    explicit_criticality = any(
        key in normalized
        for key in (
            "is_critical",
            "critical",
            "item_critical",
            "criticality",
        )
    )

    if not explicit_criticality:
        description = str(normalized.get("description") or "")

        normalized_description = (
            description.strip()
            .lower()
            .replace("‌", " ")
            .replace("ي", "ی")
            .replace("ك", "ک")
        )

        negative_phrases = (
            "حیاتی نیست",
            "حیاتی نمی باشد",
            "حیاتی نمی‌باشد",
            "غیر حیاتی",
            "غیرحیاتی",
            "not critical",
            "non critical",
            "non-critical",
        )

        positive_phrases = (
            "کالای حیاتی",
            "کالا حیاتی",
            "حیاتی می باشد",
            "حیاتی می‌باشد",
            "حیاتی میباشد",
            "critical item",
            "is critical",
        )

        if any(phrase in normalized_description for phrase in negative_phrases):
            normalized["is_critical"] = False
        elif any(phrase in normalized_description for phrase in positive_phrases):
            normalized["is_critical"] = True

    return normalized


class MaterialAssistantToolSet(ConfiguredCommerceToolSet):
    module = MODULE

    def _item(self, spec, hit):
        result = super()._item(spec, hit)
        if spec.resource_type != "item":
            return result

        model = getattr(hit, "model", None)
        model_parts = [
            getattr(model, "manufacturer", None),
            getattr(model, "model", None),
            getattr(model, "type", None),
        ]
        visible_model_parts = [part for part in model_parts if part]
        if visible_model_parts:
            result["title"] = " - ".join([result["title"], *visible_model_parts])
        return result

    def build_draft(
        self,
        *,
        intent,
        db,
        user,
        slots,
        attachments,
    ):
        if intent in {
            "add_item",
            "update_item",
        }:
            slots = _normalize_material_write_slots(slots)

        return super().build_draft(
            intent=intent,
            db=db,
            user=user,
            slots=slots,
            attachments=attachments,
        )

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
                "model_id": ("int", "model id"),
                "model_name": ("str", "model"),
                "manufacturer": ("str", "make", "brand"),
                "model_type": ("str", "equipment_type"),
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
                    raw_aliases=(
                        "category_query",
                        "category_name",
                        "category_code",
                        "category",
                        "item_category",
                        "item_category_name",
                        "item_category_code",
                    ),
                    explicit_aliases=("category_id",),
                    missing_label="category",
                ),
                ReferenceFieldSpec(
                    field="unit_id",
                    resource_key="material_unit",
                    raw_aliases=(
                        "unit_query",
                        "unit_name",
                        "unit_code",
                        "unit",
                        "item_unit",
                        "item_unit_name",
                        "item_unit_code",
                    ),
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
                PayloadField("description", aliases=("item_description",)),
                PayloadField("category_id", aliases=("category",), kind="int"),
                PayloadField("unit_id", aliases=("unit",), kind="int"),
                PayloadField("model_id", aliases=("model",), kind="int"),
                PayloadField("specs", kind="raw"),
                PayloadField("barcode"),
                PayloadField("qr_code"),
                PayloadField(
                    "item_type",
                    kind="enum",
                    enum_values=tuple(item.value for item in ItemType),
                    default=ItemType.MATERIAL.value,
                ),
                PayloadField(
                    "is_active", aliases=("active",), kind="bool", default=True
                ),
                PayloadField(
                    "is_critical",
                    aliases=("critical", "item_critical", "criticality"),
                    kind="bool",
                    default=False,
                ),
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
                    raw_aliases=(
                        "category_query",
                        "category_name",
                        "category_code",
                        "category",
                        "item_category",
                        "item_category_name",
                        "item_category_code",
                    ),
                    explicit_aliases=("category_id",),
                    missing_label="category",
                ),
                ReferenceFieldSpec(
                    field="unit_id",
                    resource_key="material_unit",
                    raw_aliases=(
                        "unit_query",
                        "unit_name",
                        "unit_code",
                        "unit",
                        "item_unit",
                        "item_unit_name",
                        "item_unit_code",
                    ),
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
                PayloadField("description", aliases=("item_description",)),
                PayloadField("category_id", aliases=("category",), kind="int"),
                PayloadField("unit_id", aliases=("unit",), kind="int"),
                PayloadField("model_id", aliases=("model",), kind="int"),
                PayloadField("specs", kind="raw"),
                PayloadField("barcode"),
                PayloadField("qr_code"),
                PayloadField(
                    "item_type",
                    kind="enum",
                    enum_values=tuple(item.value for item in ItemType),
                ),
                PayloadField("is_active", aliases=("active",), kind="bool"),
                PayloadField(
                    "is_critical",
                    aliases=("critical", "item_critical", "criticality"),
                    kind="bool",
                ),
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
