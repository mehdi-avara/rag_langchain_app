from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Callable, Iterable, Optional

from sqlalchemy.orm import Session

from Models import User
from assistant.registry import (
    DraftData,
    IntentSpec,
    ModuleAssistantDescriptor,
    ModuleToolSet,
    TaskAssistantDescriptor,
)
from assistant.rbac import ensure_permission
from assistant.resolve import resolve_field
from shared.phase1_ask import answer_from_references, parse_citations


_UNSET = object()
_PERSIAN_RE = re.compile(r"[\u0600-\u06ff]")


@dataclass(frozen=True)
class PayloadField:
    name: str
    aliases: tuple[str, ...] = ()
    kind: str = "str"
    default: Any = _UNSET
    enum_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchSpec:
    intent: str
    permission: str
    search_fn: Callable
    resource_type: str
    id_attr: str
    id_param: str
    title_fields: tuple[str, ...]
    module: str
    description: str
    ask_intent: Optional[str] = None
    ask_permission: Optional[str] = None
    ask_description: Optional[str] = None
    citation_prefix: Optional[str] = None
    extra_params: dict[str, tuple[str, str]] = field(default_factory=dict)
    slot_rules: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    specialist_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class WriteSpec:
    intent: str
    permission: str
    target_action: str
    description: str
    method: str
    endpoint: str
    fields: tuple[PayloadField, ...]
    required: tuple[str, ...] = ()
    id_aliases: tuple[str, ...] = ("id",)
    item_builder: Optional[Callable[[dict], Optional[list[dict]]]] = None
    validate: Optional[Callable[[dict, dict], list[str]]] = None
    reference_fields: tuple["ReferenceFieldSpec", ...] = ()
    slot_rules: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    specialist_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReferenceFieldSpec:
    field: str
    resource_key: str
    raw_aliases: tuple[str, ...]
    explicit_aliases: tuple[str, ...]
    missing_label: str
    collection: Optional[str] = None
    as_list: bool = False
    cleanup_fields: tuple[str, ...] = ()


def _slot(slots: dict, *keys: str) -> Any:
    for key in keys:
        if key in slots and slots[key] is not None:
            if isinstance(slots[key], str):
                stripped = slots[key].strip()
                if stripped:
                    return stripped
            else:
                return slots[key]
    return None


def _str(slots: dict, *keys: str) -> Optional[str]:
    value = _slot(slots, *keys)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _language_from_text(text: str) -> str:
    return "fa" if _PERSIAN_RE.search(text or "") else "en"


def _int_value(value: Any) -> Optional[int]:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _decimal_value(value: Any) -> Optional[str]:
    if value is None or str(value).strip() == "":
        return None
    try:
        return str(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return None


def _bool_value(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1", "active", "enabled", "فعال"}:
        return True
    if text in {"false", "no", "n", "0", "inactive", "disabled", "غیرفعال"}:
        return False
    return None


def _enum_value(value: Any, allowed: Iterable[str]) -> Optional[str]:
    if value is None:
        return None
    raw = str(value).strip()
    lowered = raw.lower()
    aliases = {
        "local supplier": "local",
        "domestic": "local",
        "داخلی": "local",
        "international supplier": "international",
        "foreign": "international",
        "خارجی": "international",
        "urgent": "urgent",
        "فوری": "urgent",
        "critical": "critical",
        "بحرانی": "critical",
        "normal": "normal",
        "عادی": "normal",
        "spare part": "spare_part",
        "spare": "spare_part",
        "قطعه یدکی": "spare_part",
        "consumable": "consumable",
        "مصرفی": "consumable",
        "tool": "tool",
        "ابزار": "tool",
        "chemical": "chemical",
        "شیمیایی": "chemical",
        "material": "material",
        "کالا": "material",
        "adjustment": "adjustment",
        "stock adjustment": "adjustment",
        "اصلاح موجودی": "adjustment",
    }
    mapped = aliases.get(lowered) or aliases.get(raw)
    allowed_set = {item.lower(): item for item in allowed}
    if mapped and mapped.lower() in allowed_set:
        return allowed_set[mapped.lower()]
    return allowed_set.get(lowered)


def _coerce_field(field: PayloadField, slots: dict) -> Any:
    value = _slot(slots, field.name, *field.aliases)
    if value is None and field.default is not _UNSET:
        value = field.default
    if value is None:
        return None
    if field.kind == "int":
        return _int_value(value)
    if field.kind == "decimal":
        return _decimal_value(value)
    if field.kind == "bool":
        return _bool_value(value)
    if field.kind == "enum":
        return _enum_value(value, field.enum_values)
    if field.kind == "raw":
        return value
    return str(value).strip() if str(value).strip() else None


def _model_dump(obj: Any) -> dict:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return dict(obj)
    return {
        key: value
        for key, value in vars(obj).items()
        if not key.startswith("_")
    }


def _hit_id(hit: Any, id_attr: str) -> Any:
    return getattr(hit, id_attr, None) if not isinstance(hit, dict) else hit.get(id_attr)


def _build_items(slots: dict, fields: tuple[tuple[str, str, tuple[str, ...]], ...]) -> Optional[list[dict]]:
    raw_items = slots.get("items")
    if isinstance(raw_items, list):
        return [item for item in raw_items if isinstance(item, dict)]

    item: dict[str, Any] = {}
    for output_name, kind, aliases in fields:
        value = _slot(slots, output_name, *aliases)
        if kind == "int":
            value = _int_value(value)
        elif kind == "decimal":
            value = _decimal_value(value)
        elif kind == "str" and value is not None:
            value = str(value).strip() or None
        if value is not None:
            item[output_name] = value
    return [item] if item else None


def requisition_items_from_slots(slots: dict) -> Optional[list[dict]]:
    return _build_items(slots, (
        ("item_id", "int", ("material_item_id",)),
        ("item_query", "str", ("item_name", "item", "material_item", "part", "part_name")),
        ("manufacturer", "str", ("make", "brand")),
        ("model_id", "int", ("managed_model_id", "selected_model_id")),
        ("model_name", "str", ("model", "equipment_model")),
        ("model_type", "str", ("equipment_type",)),
        ("item_type", "str", ()),
        ("quantity", "decimal", ("qty",)),
        ("estimated_unit_cost", "decimal", ()),
        ("currency_id", "int", ()),
        ("currency_query", "str", ("currency", "currency_code")),
        ("estimated_unit_cost_base", "decimal", ()),
        ("base_currency_id", "int", ()),
        ("base_currency_query", "str", ("base_currency", "base_currency_code")),
        ("exchange_rate_used", "decimal", ()),
        ("notes", "str", ("item_notes",)),
    ))


def rfq_items_from_slots(slots: dict) -> Optional[list[dict]]:
    return _build_items(slots, (
        ("item_id", "int", ("material_item_id",)),
        ("item_query", "str", ("item_name", "item", "material_item", "part", "part_name")),
        ("quantity", "decimal", ("qty",)),
        ("specifications", "str", ("specs",)),
    ))


def goods_receipt_items_from_slots(slots: dict) -> Optional[list[dict]]:
    return _build_items(slots, (
        (
            "purchase_phase_allocation_id",
            "int",
            ("allocation_id",),
        ),
        (
            "purchase_phase_allocation_query",
            "str",
            (
                "allocation_query",
                "purchase_phase_item_query",
                "phase_item_query",
                "po_item",
                "purchase_item",
            ),
        ),
        ("item_id", "int", ("material_item_id",)),
        ("item_query", "str", ("item_name", "item", "material_item", "part", "part_name")),
        ("received_quantity", "decimal", ("received_qty", "quantity", "qty")),
        ("accepted_quantity", "decimal", ("accepted_qty",)),
        ("rejected_quantity", "decimal", ("rejected_qty",)),
        ("rejection_reason", "str", ()),
        ("storage_location_id", "int", ("location_id",)),
        ("notes", "str", ("item_notes",)),
    ))


def rfq_required(payload: dict, slots: dict) -> list[str]:
    if payload.get("mr_id") is None and not payload.get("items"):
        return ["mr_id or items"]
    return []


def goods_receipt_required(payload: dict, slots: dict) -> list[str]:
    missing: list[str] = []

    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue

        if (
            not item.get(
                "purchase_phase_allocation_id"
            )
            and not item.get(
                "purchase_phase_allocation_query"
            )
        ):
            missing.append(
                "purchase phase allocation"
            )

        for field in (
            "received_quantity",
            "accepted_quantity",
            "rejected_quantity",
        ):
            if item.get(field) in (None, ""):
                missing.append(field)

    return missing


class ConfiguredCommerceToolSet(ModuleToolSet):
    module: str
    module_display_title: Optional[str] = None
    module_description: Optional[str] = None
    module_specialist_notes: tuple[str, ...] = ()
    search_specs: tuple[SearchSpec, ...] = ()
    write_specs: tuple[WriteSpec, ...] = ()

    def module_descriptor(self) -> ModuleAssistantDescriptor:
        return ModuleAssistantDescriptor(
            module=self.module,
            display_title=self.module_display_title or self.module.replace("_", " ").title(),
            description=self.module_description or f"Search and manage records in {self.module}.",
        )

    def task_descriptors(self) -> list[TaskAssistantDescriptor]:
        output: list[TaskAssistantDescriptor] = []
        for spec in self.search_specs:
            output.append(TaskAssistantDescriptor(
                module=spec.module,
                intent=spec.intent,
                kind="read",
                required_permission=spec.permission,
                description=spec.description,
                slot_rules=spec.slot_rules,
                examples=spec.examples,
                specialist_notes=spec.specialist_notes,
            ))
            if spec.ask_intent and spec.ask_permission:
                output.append(TaskAssistantDescriptor(
                    module=spec.module,
                    intent=spec.ask_intent,
                    kind="read",
                    required_permission=spec.ask_permission,
                    description=spec.ask_description or spec.description,
                    slot_rules=spec.slot_rules,
                    examples=spec.examples,
                    specialist_notes=spec.specialist_notes,
                ))
        for spec in self.write_specs:
            output.append(TaskAssistantDescriptor(
                module=self.module,
                intent=spec.intent,
                kind="write",
                required_permission=spec.permission,
                description=spec.description,
                slot_rules=spec.slot_rules,
                examples=spec.examples,
                specialist_notes=spec.specialist_notes,
                target_action=spec.target_action,
            ))
        return output

    def specialist_instructions(self, intent: str) -> tuple[str, ...]:
        for descriptor in self.task_descriptors():
            if descriptor.intent == intent:
                return (*self.module_specialist_notes, *descriptor.specialist_notes)
        return self.module_specialist_notes

    def intents(self) -> list[IntentSpec]:
        output: list[IntentSpec] = []
        for spec in self.search_specs:
            output.append(IntentSpec(
                name=spec.intent,
                description=spec.description,
                kind="read",
                permission=spec.permission,
                module=spec.module,
            ))
            if spec.ask_intent and spec.ask_permission:
                output.append(IntentSpec(
                    name=spec.ask_intent,
                    description=spec.ask_description or spec.description,
                    kind="read",
                    permission=spec.ask_permission,
                    module=spec.module,
                ))
        for spec in self.write_specs:
            output.append(IntentSpec(
                name=spec.intent,
                description=spec.description,
                kind="write",
                permission=spec.permission,
                module=self.module,
                target_action=spec.target_action,
            ))
        return output

    async def handle_read(self, *, intent: str, db: Session, user: User, slots: dict) -> dict:
        for spec in self.search_specs:
            if intent == spec.intent:
                return self._search(spec, db, user, slots)
            if intent == spec.ask_intent:
                return await self._ask(spec, db, user, slots)
        raise ValueError(f"Unsupported read intent: {intent}")

    def build_draft(self, *, intent: str, db: Session, user: User, slots: dict, attachments: list) -> DraftData:
        for spec in self.write_specs:
            if spec.intent == intent:
                return self._build_write(spec, db, user, slots, attachments or [])
        raise ValueError(f"Unsupported write intent: {intent}")

    def _search(self, spec: SearchSpec, db: Session, user: User, slots: dict) -> dict:
        ensure_permission(user, spec.permission)
        hits = self._run_search(spec, db, user, slots)
        items = [self._item(spec, hit) for hit in hits]
        return {
            "retrieved_items": items,
            "citations": [item["citation_key"] for item in items],
            "answer": "",
            "summary": None,
        }

    async def _ask(self, spec: SearchSpec, db: Session, user: User, slots: dict) -> dict:
        ensure_permission(user, spec.ask_permission)
        hits = self._run_search(spec, db, user, slots)
        if not hits:
            return {"retrieved_items": [], "citations": [], "answer": "No matching references were found.", "summary": None}
        items = [self._item(spec, hit) for hit in hits]
        context = "\n".join(f"[{item['citation_key']}] {item['title']} data={item['data']}" for item in items[:20])
        prefix = spec.citation_prefix or spec.resource_type
        question = _str(slots, "question", "query", "text") or ""
        answer = await answer_from_references(
            question=question,
            references=hits,
            context=context,
            citation_prefix=prefix,
            component_name=f"{spec.module}.assistant.ask",
            language=_language_from_text(question),
        )
        return {
            "retrieved_items": items,
            "citations": [f"{prefix}:{value}" for value in parse_citations(answer, prefix)],
            "answer": answer,
            "summary": None,
        }

    def _run_search(self, spec: SearchSpec, db: Session, user: User, slots: dict) -> list:
        query = _str(slots, "query", "question", "text", "name", "code") or ""
        mode = _str(slots, "mode") or "hybrid"
        if mode == "semantic":
            mode = "vector"
        if mode not in {"keyword", "vector", "hybrid"}:
            mode = "hybrid"
        limit = _int_value(slots.get("limit")) or 10
        ids = slots.get("ids") or slots.get(spec.id_param) or slots.get(f"{spec.resource_type}_ids") or []
        params = {
            "db": db,
            "current_user": user,
            "query_text": query,
            "mode": mode,
            spec.id_param: list(ids) if ids else None,
            "limit": max(1, min(limit, 50)),
        }
        for param_name, (kind, *aliases) in spec.extra_params.items():
            value = _slot(slots, param_name, *aliases)
            if kind == "int":
                value = _int_value(value)
            elif kind == "bool":
                value = _bool_value(value)
            elif kind == "str" and value is not None:
                value = str(value).strip() or None
            if value is not None:
                params[param_name] = value
        return list(spec.search_fn(**params))

    def _item(self, spec: SearchSpec, hit: Any) -> dict:
        data = _model_dump(hit)
        hit_id = data.get(spec.id_attr) or _hit_id(hit, spec.id_attr) or data.get("id")
        title_parts = [str(data.get(field)) for field in spec.title_fields if data.get(field) is not None]
        title = " - ".join(title_parts) or f"{spec.resource_type} #{hit_id}"
        prefix = spec.citation_prefix or spec.resource_type
        return {
            "resource_type": spec.resource_type,
            "source_type": spec.module,
            "citation_key": f"{prefix}:{hit_id}",
            "title": title,
            "data": data,
        }

    def _resolve_references(
        self,
        spec: WriteSpec,
        db: Session,
        user: User,
        slots: dict,
        payload: dict,
    ) -> list[dict]:
        references: list[dict] = []
        for ref_spec in spec.reference_fields:
            if ref_spec.collection:
                rows = payload.get(ref_spec.collection)
                if not isinstance(rows, list):
                    continue
                for index, row in enumerate(rows):
                    if not isinstance(row, dict):
                        continue
                    explicit = _slot(row, *ref_spec.explicit_aliases) or _slot(slots, *ref_spec.explicit_aliases)
                    raw = _str(row, *ref_spec.raw_aliases) or _str(slots, *ref_spec.raw_aliases)
                    if explicit is None and raw is None:
                        continue
                    field_name = f"{ref_spec.collection}.{index}.{ref_spec.field}"
                    resolution_context = dict(slots)
                    resolution_context.update(row)
                    resolution = resolve_field(
                        db,
                        user,
                        field=field_name,
                        resource_key=ref_spec.resource_key,
                        raw_text=raw or "",
                        slots=resolution_context,
                        explicit_id=explicit,
                    )
                    references.append(resolution.as_dict())
                    if resolution.status == "resolved":
                        row[ref_spec.field] = resolution.chosen["id"]
                        for key in ref_spec.raw_aliases:
                            row.pop(key, None)
                        for key in ref_spec.cleanup_fields:
                            row.pop(key, None)
                continue

            explicit = _slot(payload, *ref_spec.explicit_aliases) or _slot(slots, *ref_spec.explicit_aliases)
            raw = _str(payload, *ref_spec.raw_aliases) or _str(slots, *ref_spec.raw_aliases)
            if explicit is None and raw is None:
                continue
            resolution = resolve_field(
                db,
                user,
                field=ref_spec.field,
                resource_key=ref_spec.resource_key,
                raw_text=raw or "",
                slots=slots,
                explicit_id=explicit,
            )
            references.append(resolution.as_dict())
            if resolution.status == "resolved":
                resolved_id = resolution.chosen["id"]
                payload[ref_spec.field] = [resolved_id] if ref_spec.as_list else resolved_id
                for key in ref_spec.raw_aliases:
                    payload.pop(key, None)
        return references

    def _build_write(self, spec: WriteSpec, db: Session, user: User, slots: dict, attachments: list) -> DraftData:
        ensure_permission(user, spec.permission)
        payload: dict[str, Any] = {}
        for field_spec in spec.fields:
            value = _coerce_field(field_spec, slots)
            if value is not None:
                payload[field_spec.name] = value
        if spec.item_builder:
            items = spec.item_builder(slots)
            if items is not None:
                payload["items"] = items

        references = self._resolve_references(spec, db, user, slots, payload)
        pending_references = [
            ref for ref in references
            if ref.get("status") in {"ambiguous", "missing"}
        ]

        pending_reference_fields = {
            str(ref.get("field", "")).split(".")[-1]
            for ref in pending_references
        }
        missing = [
            name for name in spec.required
            if payload.get(name) in (None, "", []) and name not in pending_reference_fields
        ]
        if spec.validate:
            missing.extend(spec.validate(payload, slots))
        for ref in pending_references:
            for ref_spec in spec.reference_fields:
                if ref.get("field") == ref_spec.field or str(ref.get("field", "")).endswith(f".{ref_spec.field}"):
                    missing.append(ref_spec.missing_label)
                    break

        entity_id = None
        if "{" in spec.endpoint:
            entity_id = _slot(slots, *spec.id_aliases)
            if entity_id is None:
                missing.insert(0, spec.id_aliases[0])

        if missing:
            validation = {"valid": False, "missing": missing, "errors": {}}
            if references:
                validation["references"] = references
                validation["references_pending"] = [ref["field"] for ref in pending_references]
            return DraftData(
                target_module=self.module,
                target_action=spec.target_action,
                payload=payload,
                commit_target={},
                validation=validation,
                valid=False,
                clarify_question=self._clarify_question(missing, pending_references),
                references=references,
            )

        if "{" in spec.endpoint and not payload:
            return DraftData(
                target_module=self.module,
                target_action=spec.target_action,
                payload={},
                commit_target={},
                validation={"valid": False, "missing": [], "errors": {"fields": "no updatable fields provided"}},
                valid=False,
                clarify_question="What should I change?",
            )

        endpoint = spec.endpoint.format(entity_id=entity_id)
        commit_target = {
            "method": spec.method,
            "endpoint": endpoint,
            "permission": spec.permission,
        }
        if entity_id is not None:
            commit_target["entity_id"] = entity_id

        return DraftData(
            target_module=self.module,
            target_action=spec.target_action,
            payload=payload,
            commit_target=commit_target,
            attachments=list(attachments),
            validation={"valid": True, "references": references, "references_pending": []},
            references=references,
        )

    @staticmethod
    def _clarify_question(missing: list[str], pending_references: list[dict]) -> str:
        if pending_references:
            first = pending_references[0]
            if first.get("clarify_question"):
                return str(first["clarify_question"])
            label = _reference_label(str(first.get("field", "")))
            if first.get("status") == "ambiguous":
                return f"I found multiple possible matches. Please choose the correct {label} from the references."
            if first.get("create_suggestion"):
                return f"I could not find that {label}. Do you want to create it, or should I search again with different text?"
            return f"I could not resolve the referenced {label}. Please provide an id or a clearer name."
        return "I still need: " + ", ".join(missing) + "."


def _reference_label(field: str) -> str:
    name = field.split(".")[-1]
    labels = {
        "item_id": "item",
        "category_id": "category",
        "unit_id": "unit",
        "model_id": "model",
        "currency_id": "currency",
        "base_currency_id": "base currency",
        "supplier_id": "supplier",
        "supplier_ids": "supplier",
        "mr_id": "material requisition",
        "rfq_id": "RFQ",
        "warehouse_id": "warehouse",
        "storage_location_id": "storage location",
        "from_location_id": "source storage location",
        "to_location_id": "storage location",
        "purchase_phase_id": "purchase phase",
        "purchase_phase_allocation_id": "purchase phase allocation",
    }
    if name in labels:
        return labels[name]
    if name.endswith("_ids"):
        name = name[:-4]
    elif name.endswith("_id"):
        name = name[:-3]
    return name.replace("_", " ") or "reference"
