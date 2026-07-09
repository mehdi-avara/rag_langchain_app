from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Optional, Sequence

from fastapi import HTTPException, status
from sqlalchemy import String, cast, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from Models import User
from Models.file_asset import FileAssetStatus
from components import generate_embeddings_for_chunks
from core.exceptions.error_codes import (
    ASSET_NOT_READY,
    ITEM_ALTERNATIVE_ALREADY_EXISTS,
    ITEM_ALTERNATIVE_NOT_FOUND,
    ITEM_ALREADY_EXISTS,
    ITEM_CATEGORY_ALREADY_EXISTS,
    ITEM_CATEGORY_NOT_FOUND,
    ITEM_DOCUMENT_NOT_FOUND,
    ITEM_NOT_FOUND,
    UNIT_ALREADY_EXISTS,
    UNIT_NOT_FOUND,
    USER_HAS_NO_COMPANY,
)
from storage.manager import StorageManager

from .models import Item, ItemAlternative, ItemCategory, ItemDocument, ItemType, Unit
from .schemas import (
    ItemAlternativeOut,
    ItemCategoryOut,
    ItemCategoryTreeOut,
    ItemDocumentOut,
    ItemOut,
    UnitOut,
)


def _raise(status_code: int, code: str, message: str):
    raise HTTPException(status_code=status_code, detail={"code": code, "message": message})


def tenant_id(current_user: User) -> int:
    if current_user.company_id is None:
        _raise(
            status.HTTP_403_FORBIDDEN,
            USER_HAS_NO_COMPANY,
            "Current user does not belong to a company",
        )
    return current_user.company_id


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _clean_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _clean_code(value: Any, field_name: str) -> str:
    value = _clean_text(value)
    if not value:
        raise ValueError(f"{field_name} is required")
    return value


def _item_query(db: Session):
    return db.query(Item).options(
        joinedload(Item.category),
        joinedload(Item.unit),
        joinedload(Item.alternatives),
        joinedload(Item.documents),
    )


def get_category_or_404(db: Session, current_user: User, category_id: int) -> ItemCategory:
    category = (
        db.query(ItemCategory)
        .filter(
            ItemCategory.id == category_id,
            ItemCategory.company_id == tenant_id(current_user),
        )
        .first()
    )
    if category is None:
        _raise(status.HTTP_404_NOT_FOUND, ITEM_CATEGORY_NOT_FOUND, "Item category not found")
    return category


def get_unit_or_404(db: Session, current_user: User, unit_id: int) -> Unit:
    unit = (
        db.query(Unit)
        .filter(
            Unit.id == unit_id,
            Unit.company_id == tenant_id(current_user),
        )
        .first()
    )
    if unit is None:
        _raise(status.HTTP_404_NOT_FOUND, UNIT_NOT_FOUND, "Unit not found")
    return unit


def get_item_or_404(
    db: Session,
    current_user: User,
    item_id: int,
    include_relations: bool = False,
) -> Item:
    query = _item_query(db) if include_relations else db.query(Item)
    item = (
        query.filter(
            Item.id == item_id,
            Item.company_id == tenant_id(current_user),
        )
        .first()
    )
    if item is None:
        _raise(status.HTTP_404_NOT_FOUND, ITEM_NOT_FOUND, "Item not found")
    return item


def get_item_reference(db: Session, current_user: User, item_id: int) -> dict[str, Any]:
    item = get_item_or_404(db, current_user, item_id, include_relations=True)
    return {
        "id": item.id,
        "item_code": item.item_code,
        "name": item.name,
        "unit_code": item.unit.code,
        "unit_id": item.unit_id,
    }


def _validate_model_id(db: Session, current_user: User, model_id: Optional[int]) -> None:
    if model_id is None:
        return
    from model_management.services import get_model_or_404

    get_model_or_404(db, model_id, current_user)


def _validate_supplier_id(db: Session, current_user: User, supplier_id: Optional[int]) -> None:
    if supplier_id is None:
        return
    from supplier_management.services import get_supplier_or_404

    get_supplier_or_404(db, supplier_id, current_user)


def _require_ready_asset(db: Session, current_user: User, asset_id: int):
    asset = StorageManager(db).get_asset(asset_id=asset_id, user=current_user)
    if asset.status != FileAssetStatus.READY.value:
        _raise(status.HTTP_409_CONFLICT, ASSET_NOT_READY, "Asset is not ready")
    return asset


def validate_item_import_asset(db: Session, current_user: User, asset_id: int):
    asset = _require_ready_asset(db, current_user, asset_id)
    filename = (asset.original_filename or "").lower()
    if not filename.endswith(".xlsx"):
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "ITEM_IMPORT_INVALID_FILE",
            "Material import requires an .xlsx file",
        )
    return asset


def item_searchable_text(item: Item) -> str:
    values: list[Any] = [
        item.item_code,
        item.name,
        item.description,
        item.barcode,
        item.qr_code,
        item.item_type,
        item.lead_time_days,
        item.specs,
    ]

    if getattr(item, "category", None) is not None:
        values.extend([item.category.code, item.category.name, item.category.description])

    if getattr(item, "unit", None) is not None:
        values.extend([item.unit.code, item.unit.name, item.unit.unit_type])

    values.extend(
        value
        for alternative in list(getattr(item, "alternatives", []) or [])
        for value in [alternative.alt_code, alternative.alt_name, alternative.notes]
    )

    return "\n".join(_clean_text(value) for value in values if _clean_text(value))


def safe_embed_item_text(text: str) -> Optional[list[float]]:
    if not _clean_text(text):
        return None
    try:
        embeddings = generate_embeddings_for_chunks([text])
    except Exception:
        return None
    return embeddings[0] if embeddings else None


def category_to_out(category: ItemCategory) -> ItemCategoryOut:
    return ItemCategoryOut(
        id=category.id,
        company_id=category.company_id,
        parent_id=category.parent_id,
        code=category.code,
        name=category.name,
        description=category.description,
        created_by_user_id=category.created_by_user_id,
        created_at=category.created_at,
        updated_at=category.updated_at,
    )


def unit_to_out(unit: Unit) -> UnitOut:
    return UnitOut(
        id=unit.id,
        company_id=unit.company_id,
        code=unit.code,
        name=unit.name,
        unit_type=unit.unit_type,
        created_by_user_id=unit.created_by_user_id,
        created_at=unit.created_at,
        updated_at=unit.updated_at,
    )


def alternative_to_out(alternative: ItemAlternative) -> ItemAlternativeOut:
    return ItemAlternativeOut(
        id=alternative.id,
        item_id=alternative.item_id,
        supplier_id=alternative.supplier_id,
        alt_code=alternative.alt_code,
        alt_name=alternative.alt_name,
        notes=alternative.notes,
        created_by_user_id=alternative.created_by_user_id,
        created_at=alternative.created_at,
        updated_at=alternative.updated_at,
    )


def document_to_out(document: ItemDocument) -> ItemDocumentOut:
    return ItemDocumentOut(
        id=document.id,
        item_id=document.item_id,
        asset_id=document.asset_id,
        document_type=document.document_type,
        title=document.title,
        notes=document.notes,
        created_by_user_id=document.created_by_user_id,
        created_at=document.created_at,
    )


def item_to_out(item: Item, include_relations: bool = True) -> ItemOut:
    return ItemOut(
        id=item.id,
        company_id=item.company_id,
        item_code=item.item_code,
        name=item.name,
        description=item.description,
        category_id=item.category_id,
        unit_id=item.unit_id,
        model_id=item.model_id,
        specs=item.specs or {},
        barcode=item.barcode,
        qr_code=item.qr_code,
        item_type=item.item_type,
        is_active=item.is_active,
        is_critical=item.is_critical,
        lead_time_days=item.lead_time_days,
        created_by_user_id=item.created_by_user_id,
        embedding_status="available" if item.description_embedding is not None else "pending",
        created_at=item.created_at,
        updated_at=item.updated_at,
        category=category_to_out(item.category),
        unit=unit_to_out(item.unit),
        alternatives=[
            alternative_to_out(value)
            for value in list(item.alternatives or [])
        ] if include_relations else [],
        documents=[
            document_to_out(value)
            for value in list(item.documents or [])
        ] if include_relations else [],
    )


def list_categories(db: Session, current_user: User) -> list[ItemCategory]:
    return (
        db.query(ItemCategory)
        .filter(ItemCategory.company_id == tenant_id(current_user))
        .order_by(ItemCategory.code.asc(), ItemCategory.id.asc())
        .all()
    )


def _lookup_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[\w\u0600-\u06ff]+", (text or "").lower())
        if len(token) >= 2
    }


def _lookup_rank(query_text: str, values: Sequence[Optional[str]]) -> Optional[tuple[int, str]]:
    query = (query_text or "").strip().lower()
    haystack = " ".join(value for value in values if value).lower()
    if not query:
        return (50, haystack)
    if any((value or "").strip().lower() == query for value in values):
        return (0, haystack)
    if any((value or "").strip().lower().startswith(query) for value in values):
        return (10, haystack)
    if query in haystack:
        return (20, haystack)
    query_tokens = _lookup_tokens(query)
    if query_tokens and query_tokens & _lookup_tokens(haystack):
        return (30, haystack)
    return None


def search_categories_for_assistant(
    db: Session,
    current_user: User,
    query_text: str,
    *,
    limit: int = 10,
) -> list[ItemCategory]:
    ranked: list[tuple[tuple[int, str], ItemCategory]] = []
    for category in list_categories(db, current_user):
        rank = _lookup_rank(query_text, (category.code, category.name, category.description))
        if rank is not None:
            ranked.append((rank, category))
    ranked.sort(key=lambda item: (item[0][0], item[1].code, item[1].id))
    return [category for _, category in ranked[: max(1, limit)]]


def build_category_tree(categories: Sequence[ItemCategory]) -> list[ItemCategoryTreeOut]:
    nodes = {
        category.id: ItemCategoryTreeOut(
            id=category.id,
            company_id=category.company_id,
            parent_id=category.parent_id,
            code=category.code,
            name=category.name,
            description=category.description,
            created_by_user_id=category.created_by_user_id,
            created_at=category.created_at,
            updated_at=category.updated_at,
            children=[],
        )
        for category in categories
    }

    roots: list[ItemCategoryTreeOut] = []

    for category in categories:
        node = nodes[category.id]
        if category.parent_id and category.parent_id in nodes:
            nodes[category.parent_id].children.append(node)
        else:
            roots.append(node)

    return roots


def _validate_category_parent(
    db: Session,
    current_user: User,
    category_id: Optional[int],
    parent_id: Optional[int],
) -> None:
    if parent_id is None:
        return

    parent = get_category_or_404(db, current_user, parent_id)

    if category_id is None:
        return

    if parent.id == category_id:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "ITEM_CATEGORY_INVALID_PARENT",
            "An item category cannot be its own parent",
        )

    current = parent
    visited: set[int] = set()

    while current.parent_id is not None:
        if current.id in visited:
            break
        visited.add(current.id)

        if current.parent_id == category_id:
            _raise(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "ITEM_CATEGORY_INVALID_PARENT",
                "A category cannot be assigned to one of its descendants",
            )

        current = (
            db.query(ItemCategory)
            .filter(ItemCategory.id == current.parent_id)
            .first()
        )
        if current is None:
            break


def create_category(db: Session, current_user: User, data: dict) -> ItemCategory:
    company_id = tenant_id(current_user)
    code = _clean_code(data["code"], "code")

    existing = (
        db.query(ItemCategory)
        .filter(
            ItemCategory.company_id == company_id,
            ItemCategory.code == code,
        )
        .first()
    )
    if existing:
        _raise(status.HTTP_409_CONFLICT, ITEM_CATEGORY_ALREADY_EXISTS, "Item category code already exists")

    _validate_category_parent(db, current_user, None, data.get("parent_id"))

    category = ItemCategory(
        company_id=company_id,
        code=code,
        name=_clean_code(data["name"], "name"),
        parent_id=data.get("parent_id"),
        description=data.get("description"),
        created_by_user_id=current_user.id,
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


def update_category(db: Session, current_user: User, category_id: int, data: dict) -> ItemCategory:
    category = get_category_or_404(db, current_user, category_id)

    if "parent_id" in data:
        _validate_category_parent(db, current_user, category.id, data["parent_id"])

    if "code" in data:
        code = _clean_code(data["code"], "code")
        existing = (
            db.query(ItemCategory)
            .filter(
                ItemCategory.company_id == category.company_id,
                ItemCategory.code == code,
                ItemCategory.id != category.id,
            )
            .first()
        )
        if existing:
            _raise(status.HTTP_409_CONFLICT, ITEM_CATEGORY_ALREADY_EXISTS, "Item category code already exists")
        category.code = code

    for key in ("name", "parent_id", "description"):
        if key in data:
            setattr(category, key, data[key])

    db.commit()
    db.refresh(category)
    return category


def delete_category(db: Session, current_user: User, category_id: int) -> None:
    category = get_category_or_404(db, current_user, category_id)

    if db.query(ItemCategory.id).filter(ItemCategory.parent_id == category.id).first():
        _raise(
            status.HTTP_409_CONFLICT,
            "ITEM_CATEGORY_IN_USE",
            "Cannot delete a category that has child categories",
        )

    if db.query(Item.id).filter(Item.category_id == category.id).first():
        _raise(
            status.HTTP_409_CONFLICT,
            "ITEM_CATEGORY_IN_USE",
            "Cannot delete a category that is used by items",
        )

    db.delete(category)
    db.commit()


def list_units(db: Session, current_user: User) -> list[Unit]:
    return (
        db.query(Unit)
        .filter(Unit.company_id == tenant_id(current_user))
        .order_by(Unit.code.asc(), Unit.id.asc())
        .all()
    )


def search_units_for_assistant(
    db: Session,
    current_user: User,
    query_text: str,
    *,
    limit: int = 10,
) -> list[Unit]:
    ranked: list[tuple[tuple[int, str], Unit]] = []
    for unit in list_units(db, current_user):
        rank = _lookup_rank(query_text, (unit.code, unit.name, unit.unit_type))
        if rank is not None:
            ranked.append((rank, unit))
    ranked.sort(key=lambda item: (item[0][0], item[1].code, item[1].id))
    return [unit for _, unit in ranked[: max(1, limit)]]


def create_unit(db: Session, current_user: User, data: dict) -> Unit:
    company_id = tenant_id(current_user)
    code = _clean_code(data["code"], "code")

    existing = (
        db.query(Unit)
        .filter(Unit.company_id == company_id, Unit.code == code)
        .first()
    )
    if existing:
        _raise(status.HTTP_409_CONFLICT, UNIT_ALREADY_EXISTS, "Unit code already exists")

    unit = Unit(
        company_id=company_id,
        code=code,
        name=_clean_code(data["name"], "name"),
        unit_type=_enum_value(data.get("unit_type", "count")),
        created_by_user_id=current_user.id,
    )
    db.add(unit)
    db.commit()
    db.refresh(unit)
    return unit


def update_unit(db: Session, current_user: User, unit_id: int, data: dict) -> Unit:
    unit = get_unit_or_404(db, current_user, unit_id)

    if "code" in data:
        code = _clean_code(data["code"], "code")
        existing = (
            db.query(Unit)
            .filter(
                Unit.company_id == unit.company_id,
                Unit.code == code,
                Unit.id != unit.id,
            )
            .first()
        )
        if existing:
            _raise(status.HTTP_409_CONFLICT, UNIT_ALREADY_EXISTS, "Unit code already exists")
        unit.code = code

    if "name" in data:
        unit.name = _clean_code(data["name"], "name")

    if "unit_type" in data:
        unit.unit_type = _enum_value(data["unit_type"])

    db.commit()
    db.refresh(unit)
    return unit


def delete_unit(db: Session, current_user: User, unit_id: int) -> None:
    unit = get_unit_or_404(db, current_user, unit_id)

    if db.query(Item.id).filter(Item.unit_id == unit.id).first():
        _raise(status.HTTP_409_CONFLICT, "UNIT_IN_USE", "Cannot delete a unit used by items")

    db.delete(unit)
    db.commit()


def list_items(
    db: Session,
    current_user: User,
    query_text: Optional[str] = None,
    category_id: Optional[int] = None,
    item_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Item]:
    query = _item_query(db).filter(Item.company_id == tenant_id(current_user))

    if category_id is not None:
        query = query.filter(Item.category_id == category_id)

    if item_type:
        query = query.filter(Item.item_type == _enum_value(item_type))

    if is_active is not None:
        query = query.filter(Item.is_active == is_active)

    if query_text:
        pattern = f"%{query_text.strip()}%"
        query = query.join(ItemCategory, Item.category_id == ItemCategory.id).filter(
            or_(
                Item.item_code.ilike(pattern),
                Item.name.ilike(pattern),
                Item.description.ilike(pattern),
                Item.barcode.ilike(pattern),
                Item.qr_code.ilike(pattern),
                cast(Item.specs, String).ilike(pattern),
                ItemCategory.code.ilike(pattern),
                ItemCategory.name.ilike(pattern),
            )
        )

    return (
        query.order_by(Item.created_at.desc(), Item.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def _validate_item_references(
    db: Session,
    current_user: User,
    category_id: int,
    unit_id: int,
    model_id: Optional[int],
) -> None:
    get_category_or_404(db, current_user, category_id)
    get_unit_or_404(db, current_user, unit_id)
    _validate_model_id(db, current_user, model_id)


def create_item(db: Session, current_user: User, data: dict) -> Item:
    company_id = tenant_id(current_user)
    item_code = _clean_code(data["item_code"], "item_code")

    existing = (
        db.query(Item)
        .filter(Item.company_id == company_id, Item.item_code == item_code)
        .first()
    )
    if existing:
        _raise(status.HTTP_409_CONFLICT, ITEM_ALREADY_EXISTS, "Item code already exists")

    _validate_item_references(
        db,
        current_user,
        data["category_id"],
        data["unit_id"],
        data.get("model_id"),
    )

    item = Item(
        company_id=company_id,
        item_code=item_code,
        name=_clean_code(data["name"], "name"),
        description=data.get("description"),
        category_id=data["category_id"],
        unit_id=data["unit_id"],
        model_id=data.get("model_id"),
        specs=data.get("specs") or {},
        barcode=data.get("barcode"),
        qr_code=data.get("qr_code"),
        item_type=_enum_value(data.get("item_type", ItemType.MATERIAL.value)),
        is_active=data.get("is_active", True),
        is_critical=data.get("is_critical", False),
        lead_time_days=data.get("lead_time_days"),
        created_by_user_id=current_user.id,
    )
    item.description_embedding = safe_embed_item_text(item_searchable_text(item))

    db.add(item)
    db.commit()
    return get_item_or_404(db, current_user, item.id, include_relations=True)


def update_item(db: Session, current_user: User, item_id: int, data: dict) -> Item:
    item = get_item_or_404(db, current_user, item_id, include_relations=True)

    category_id = data.get("category_id", item.category_id)
    unit_id = data.get("unit_id", item.unit_id)
    model_id = data["model_id"] if "model_id" in data else item.model_id

    _validate_item_references(db, current_user, category_id, unit_id, model_id)

    if "item_code" in data:
        item_code = _clean_code(data["item_code"], "item_code")
        existing = (
            db.query(Item)
            .filter(
                Item.company_id == item.company_id,
                Item.item_code == item_code,
                Item.id != item.id,
            )
            .first()
        )
        if existing:
            _raise(status.HTTP_409_CONFLICT, ITEM_ALREADY_EXISTS, "Item code already exists")
        item.item_code = item_code

    if "name" in data:
        item.name = _clean_code(data["name"], "name")

    for key in (
        "description",
        "category_id",
        "unit_id",
        "model_id",
        "barcode",
        "qr_code",
        "is_active",
        "is_critical",
        "lead_time_days",
    ):
        if key in data:
            setattr(item, key, data[key])

    if "specs" in data:
        item.specs = data["specs"] or {}

    if "item_type" in data:
        item.item_type = _enum_value(data["item_type"])

    searchable_fields = {
        "item_code",
        "name",
        "description",
        "category_id",
        "unit_id",
        "model_id",
        "specs",
        "barcode",
        "qr_code",
        "item_type",
        "lead_time_days",
    }

    if searchable_fields.intersection(data):
        item.description_embedding = safe_embed_item_text(item_searchable_text(item))

    db.commit()
    return get_item_or_404(db, current_user, item.id, include_relations=True)


def delete_item(db: Session, current_user: User, item_id: int) -> None:
    item = get_item_or_404(db, current_user, item_id)
    db.delete(item)
    db.commit()


def _get_alternative_or_404(
    db: Session,
    current_user: User,
    item_id: int,
    alternative_id: int,
) -> ItemAlternative:
    get_item_or_404(db, current_user, item_id)
    alternative = (
        db.query(ItemAlternative)
        .filter(
            ItemAlternative.id == alternative_id,
            ItemAlternative.item_id == item_id,
        )
        .first()
    )
    if alternative is None:
        _raise(status.HTTP_404_NOT_FOUND, ITEM_ALTERNATIVE_NOT_FOUND, "Item alternative not found")
    return alternative


def add_item_alternative(
    db: Session,
    current_user: User,
    item_id: int,
    data: dict,
) -> ItemAlternative:
    item = get_item_or_404(db, current_user, item_id)
    alt_code = _clean_code(data["alt_code"], "alt_code")

    existing = (
        db.query(ItemAlternative)
        .filter(
            ItemAlternative.item_id == item.id,
            ItemAlternative.alt_code == alt_code,
        )
        .first()
    )
    if existing:
        _raise(
            status.HTTP_409_CONFLICT,
            ITEM_ALTERNATIVE_ALREADY_EXISTS,
            "Alternative code already exists for this item",
        )

    _validate_supplier_id(db, current_user, data.get("supplier_id"))

    alternative = ItemAlternative(
        item_id=item.id,
        supplier_id=data.get("supplier_id"),
        alt_code=alt_code,
        alt_name=_clean_code(data["alt_name"], "alt_name"),
        notes=data.get("notes"),
        created_by_user_id=current_user.id,
    )
    db.add(alternative)
    db.commit()
    db.refresh(alternative)
    return alternative


def update_item_alternative(
    db: Session,
    current_user: User,
    item_id: int,
    alternative_id: int,
    data: dict,
) -> ItemAlternative:
    alternative = _get_alternative_or_404(db, current_user, item_id, alternative_id)

    if "supplier_id" in data:
        _validate_supplier_id(db, current_user, data["supplier_id"])
        alternative.supplier_id = data["supplier_id"]

    if "alt_code" in data:
        alt_code = _clean_code(data["alt_code"], "alt_code")
        existing = (
            db.query(ItemAlternative)
            .filter(
                ItemAlternative.item_id == item_id,
                ItemAlternative.alt_code == alt_code,
                ItemAlternative.id != alternative.id,
            )
            .first()
        )
        if existing:
            _raise(
                status.HTTP_409_CONFLICT,
                ITEM_ALTERNATIVE_ALREADY_EXISTS,
                "Alternative code already exists for this item",
            )
        alternative.alt_code = alt_code

    if "alt_name" in data:
        alternative.alt_name = _clean_code(data["alt_name"], "alt_name")

    if "notes" in data:
        alternative.notes = data["notes"]

    db.commit()
    db.refresh(alternative)
    return alternative


def delete_item_alternative(
    db: Session,
    current_user: User,
    item_id: int,
    alternative_id: int,
) -> None:
    alternative = _get_alternative_or_404(db, current_user, item_id, alternative_id)
    db.delete(alternative)
    db.commit()


def _get_document_or_404(
    db: Session,
    current_user: User,
    item_id: int,
    document_id: int,
) -> ItemDocument:
    get_item_or_404(db, current_user, item_id)
    document = (
        db.query(ItemDocument)
        .filter(
            ItemDocument.id == document_id,
            ItemDocument.item_id == item_id,
        )
        .first()
    )
    if document is None:
        _raise(status.HTTP_404_NOT_FOUND, ITEM_DOCUMENT_NOT_FOUND, "Item document not found")
    return document


def add_item_document(
    db: Session,
    current_user: User,
    item_id: int,
    data: dict,
) -> ItemDocument:
    item = get_item_or_404(db, current_user, item_id)

    asset_id = data.get("asset_id")
    if asset_id is not None:
        _require_ready_asset(db, current_user, asset_id)

    document = ItemDocument(
        item_id=item.id,
        asset_id=asset_id,
        document_type=_clean_code(data["document_type"], "document_type"),
        title=_clean_code(data["title"], "title"),
        notes=data.get("notes"),
        created_by_user_id=current_user.id,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def delete_item_document(
    db: Session,
    current_user: User,
    item_id: int,
    document_id: int,
) -> None:
    document = _get_document_or_404(db, current_user, item_id, document_id)
    db.delete(document)
    db.commit()


def ensure_item_embeddings(
    db: Session,
    current_user: User,
    item_ids: Optional[Sequence[int]] = None,
) -> None:
    query = _item_query(db).filter(
        Item.company_id == tenant_id(current_user),
        Item.description_embedding.is_(None),
    )

    if item_ids is not None:
        if not item_ids:
            return
        query = query.filter(Item.id.in_(list(dict.fromkeys(item_ids))))

    items = query.all()

    changed = False
    for item in items:
        embedding = safe_embed_item_text(item_searchable_text(item))
        if embedding is not None:
            item.description_embedding = embedding
            changed = True

    if changed:
        db.commit()


def _import_bool(value: Any, default: bool) -> bool:
    if value is None or _clean_text(value) == "":
        return default
    if isinstance(value, bool):
        return value
    normalized = _clean_text(value).lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value}")


def _import_integer(value: Any, field_name: str) -> Optional[int]:
    if value is None or _clean_text(value) == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _import_specs(value: Any) -> dict:
    if value is None or _clean_text(value) == "":
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError as exc:
        raise ValueError("specs_json must contain a valid JSON object") from exc
    if not isinstance(parsed, dict):
        raise ValueError("specs_json must contain a JSON object")
    return parsed


def upsert_item_from_import_row(
    db: Session,
    current_user: User,
    row: dict[str, Any],
) -> str:
    company_id = tenant_id(current_user)

    item_code = _clean_code(row.get("item_code"), "item_code")
    name = _clean_code(row.get("name"), "name")
    category_code = _clean_code(row.get("category_code"), "category_code")
    unit_code = _clean_code(row.get("unit_code"), "unit_code")

    category = (
        db.query(ItemCategory)
        .filter(
            ItemCategory.company_id == company_id,
            ItemCategory.code == category_code,
        )
        .first()
    )
    if category is None:
        raise ValueError(f"Unknown category_code: {category_code}")

    unit = (
        db.query(Unit)
        .filter(
            Unit.company_id == company_id,
            Unit.code == unit_code,
        )
        .first()
    )
    if unit is None:
        raise ValueError(f"Unknown unit_code: {unit_code}")

    model_id = _import_integer(row.get("model_id"), "model_id")
    _validate_model_id(db, current_user, model_id)

    item_type = _clean_text(row.get("item_type") or ItemType.MATERIAL.value).lower()
    if item_type not in {value.value for value in ItemType}:
        raise ValueError(f"Invalid item_type: {item_type}")

    lead_time_days = _import_integer(row.get("lead_time_days"), "lead_time_days")
    if lead_time_days is not None and lead_time_days < 0:
        raise ValueError("lead_time_days cannot be negative")

    values = {
        "name": name,
        "description": _clean_text(row.get("description")) or None,
        "category_id": category.id,
        "unit_id": unit.id,
        "model_id": model_id,
        "specs": _import_specs(row.get("specs_json")),
        "barcode": _clean_text(row.get("barcode")) or None,
        "qr_code": _clean_text(row.get("qr_code")) or None,
        "item_type": item_type,
        "is_active": _import_bool(row.get("is_active"), True),
        "is_critical": _import_bool(row.get("is_critical"), False),
        "lead_time_days": lead_time_days,
    }

    item = (
        db.query(Item)
        .filter(Item.company_id == company_id, Item.item_code == item_code)
        .first()
    )

    if item is None:
        item = Item(
            company_id=company_id,
            item_code=item_code,
            created_by_user_id=current_user.id,
            **values,
        )
        db.add(item)
        outcome = "created"
    else:
        for key, value in values.items():
            setattr(item, key, value)
        outcome = "updated"

    item.description_embedding = safe_embed_item_text(item_searchable_text(item))
    db.flush()
    return outcome


def get_item_references(
    db: Session,
    current_user: User,
    item_ids: list[int],
) -> dict[int, dict[str, Any]]:
    normalized_ids = sorted(
        {
            int(item_id)
            for item_id in item_ids
            if item_id is not None and int(item_id) > 0
        }
    )

    if not normalized_ids:
        return {}

    items = (
        _item_query(db)
        .filter(
            Item.company_id == tenant_id(current_user),
            Item.id.in_(normalized_ids),
        )
        .all()
    )

    return {
        item.id: {
            "id": item.id,
            "item_code": item.item_code,
            "name": item.name,
            "unit_code": item.unit.code if item.unit is not None else None,
        }
        for item in items
    }
