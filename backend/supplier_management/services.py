from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Sequence

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from Models import User
from Models.file_asset import FileAsset, FileAssetStatus
from components import generate_embeddings_for_chunks
from core.exceptions.error_codes import (
    ASSET_NOT_READY,
    SUPPLIER_CATEGORY_ALREADY_EXISTS,
    SUPPLIER_CATEGORY_NOT_FOUND,
    SUPPLIER_CONTACT_NOT_FOUND,
    SUPPLIER_DOCUMENT_NOT_FOUND,
    SUPPLIER_EVALUATION_NOT_FOUND,
    SUPPLIER_NOT_FOUND,
    USER_HAS_NO_COMPANY,
)

from .models import (
    Supplier,
    SupplierCategory,
    SupplierContact,
    SupplierDocument,
    SupplierEvaluation,
)
from .schemas import (
    SupplierCategoryOut,
    SupplierContactOut,
    SupplierDocumentOut,
    SupplierEvaluationOut,
    SupplierOut,
    SupplierPerformanceOut,
)


def tenant_id(user: User) -> int:
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": USER_HAS_NO_COMPANY,
                "message": "Current user does not belong to a company",
            },
        )
    return user.company_id


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _text(value) -> str:
    return str(value).strip() if value is not None else ""


def supplier_searchable_text(supplier: Supplier) -> str:
    values = [
        supplier.code,
        supplier.name,
        supplier.supplier_type,
        supplier.country,
        supplier.city,
        supplier.address,
        supplier.tax_id,
        supplier.website,
        supplier.status,
        supplier.notes,
    ]

    values.extend(
        value
        for contact in list(supplier.contacts or [])
        for value in [contact.full_name, contact.job_title, contact.phone, contact.email, contact.notes]
    )
    values.extend(category.category for category in list(supplier.categories or []))

    return "\n".join(value for value in (_text(item) for item in values) if value)


def safe_embed_supplier_text(text: str) -> Optional[list[float]]:
    if not _text(text):
        return None

    try:
        embeddings = generate_embeddings_for_chunks([text])
    except Exception:
        return None

    return embeddings[0] if embeddings else None


def _supplier_query(db: Session):
    return db.query(Supplier).options(
        joinedload(Supplier.contacts),
        joinedload(Supplier.categories),
        joinedload(Supplier.documents),
        joinedload(Supplier.evaluations),
    )


def get_supplier_or_404(
    db: Session,
    supplier_id: int,
    current_user: User,
    include_relations: bool = False,
) -> Supplier:
    query = _supplier_query(db) if include_relations else db.query(Supplier)

    supplier = (
        query.filter(
            Supplier.id == supplier_id,
            Supplier.company_id == tenant_id(current_user),
        )
        .first()
    )

    if supplier is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": SUPPLIER_NOT_FOUND,
                "message": "Supplier not found",
            },
        )

    return supplier


def _next_supplier_code(db: Session, company_id: int) -> str:
    highest = 0

    codes = (
        db.query(Supplier.code)
        .filter(
            Supplier.company_id == company_id,
            Supplier.code.like("SUP-%"),
        )
        .all()
    )

    for (code,) in codes:
        match = re.fullmatch(r"SUP-(\d+)", code or "")
        if match:
            highest = max(highest, int(match.group(1)))

    return f"SUP-{highest + 1:03d}"


def _decimal_average(values: Sequence[Optional[Decimal]]) -> Optional[Decimal]:
    valid_values = [Decimal(str(value)) for value in values if value is not None]

    if not valid_values:
        return None

    return (sum(valid_values) / Decimal(len(valid_values))).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def calculate_supplier_performance(
    supplier_id: int,
    evaluations: Sequence[SupplierEvaluation],
) -> SupplierPerformanceOut:
    quality_score = _decimal_average([item.quality_score for item in evaluations])
    delivery_score = _decimal_average([item.delivery_score for item in evaluations])
    price_score = _decimal_average([item.price_score for item in evaluations])
    service_score = _decimal_average([item.service_score for item in evaluations])

    overall_score = _decimal_average(
        [quality_score, delivery_score, price_score, service_score]
    )

    return SupplierPerformanceOut(
        supplier_id=supplier_id,
        evaluation_count=len(evaluations),
        quality_score=quality_score,
        delivery_score=delivery_score,
        price_score=price_score,
        service_score=service_score,
        overall_score=overall_score,
    )


def contact_to_out(contact: SupplierContact) -> SupplierContactOut:
    return SupplierContactOut(
        id=contact.id,
        supplier_id=contact.supplier_id,
        full_name=contact.full_name,
        job_title=contact.job_title,
        phone=contact.phone,
        email=contact.email,
        is_primary=contact.is_primary,
        notes=contact.notes,
        created_at=contact.created_at,
        updated_at=contact.updated_at,
    )


def category_to_out(category: SupplierCategory) -> SupplierCategoryOut:
    return SupplierCategoryOut(
        id=category.id,
        supplier_id=category.supplier_id,
        category=category.category,
        created_at=category.created_at,
    )


def document_to_out(document: SupplierDocument) -> SupplierDocumentOut:
    return SupplierDocumentOut(
        id=document.id,
        supplier_id=document.supplier_id,
        asset_id=document.asset_id,
        document_type=document.document_type,
        title=document.title,
        notes=document.notes,
        expires_at=document.expires_at,
        created_by_user_id=document.created_by_user_id,
        created_at=document.created_at,
    )


def evaluation_to_out(evaluation: SupplierEvaluation) -> SupplierEvaluationOut:
    return SupplierEvaluationOut(
        id=evaluation.id,
        supplier_id=evaluation.supplier_id,
        evaluator_user_id=evaluation.evaluator_user_id,
        quality_score=evaluation.quality_score,
        delivery_score=evaluation.delivery_score,
        price_score=evaluation.price_score,
        service_score=evaluation.service_score,
        notes=evaluation.notes,
        evaluation_date=evaluation.evaluation_date,
        created_at=evaluation.created_at,
        updated_at=evaluation.updated_at,
    )


def supplier_to_out(
    supplier: Supplier,
    include_relations: bool = True,
    include_performance: bool = False,
) -> SupplierOut:
    performance = (
        calculate_supplier_performance(supplier.id, list(supplier.evaluations or []))
        if include_performance
        else None
    )

    return SupplierOut(
        id=supplier.id,
        company_id=supplier.company_id,
        code=supplier.code,
        name=supplier.name,
        supplier_type=supplier.supplier_type,
        country=supplier.country,
        city=supplier.city,
        address=supplier.address,
        tax_id=supplier.tax_id,
        website=supplier.website,
        status=supplier.status,
        notes=supplier.notes,
        created_by_user_id=supplier.created_by_user_id,
        embedding_status="available" if supplier.description_embedding is not None else "pending",
        created_at=supplier.created_at,
        updated_at=supplier.updated_at,
        contacts=[contact_to_out(item) for item in list(supplier.contacts or [])] if include_relations else [],
        categories=[category_to_out(item) for item in list(supplier.categories or [])] if include_relations else [],
        documents=[document_to_out(item) for item in list(supplier.documents or [])] if include_relations else [],
        performance=performance,
    )


def list_suppliers(
    db: Session,
    current_user: User,
    query_text: Optional[str] = None,
    supplier_status: Optional[str] = None,
    supplier_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Supplier]:
    company_id = tenant_id(current_user)

    query = _supplier_query(db).filter(Supplier.company_id == company_id)

    if supplier_status:
        query = query.filter(Supplier.status == _enum_value(supplier_status))

    if supplier_type:
        query = query.filter(Supplier.supplier_type == _enum_value(supplier_type))

    if query_text:
        pattern = f"%{query_text.strip()}%"
        query = query.filter(
            or_(
                Supplier.code.ilike(pattern),
                Supplier.name.ilike(pattern),
                Supplier.country.ilike(pattern),
                Supplier.city.ilike(pattern),
                Supplier.tax_id.ilike(pattern),
                Supplier.notes.ilike(pattern),
            )
        )

    return (
        query.order_by(Supplier.created_at.desc(), Supplier.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def create_supplier(
    db: Session,
    current_user: User,
    data: dict,
) -> Supplier:
    company_id = tenant_id(current_user)

    normalized = {
        key: _enum_value(value)
        for key, value in data.items()
    }

    for _ in range(5):
        supplier = Supplier(
            company_id=company_id,
            code=_next_supplier_code(db, company_id),
            created_by_user_id=current_user.id,
            **normalized,
        )
        supplier.description_embedding = safe_embed_supplier_text(
            supplier_searchable_text(supplier)
        )

        db.add(supplier)

        try:
            db.commit()
            db.refresh(supplier)
            return supplier
        except IntegrityError as exc:
            db.rollback()
            if "uq_suppliers_company_code" not in str(exc.orig):
                raise

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "SUPPLIER_CODE_GENERATION_FAILED",
            "message": "Could not generate a unique supplier code",
        },
    )


def update_supplier(
    db: Session,
    current_user: User,
    supplier_id: int,
    data: dict,
) -> Supplier:
    supplier = get_supplier_or_404(
        db=db,
        supplier_id=supplier_id,
        current_user=current_user,
        include_relations=True,
    )

    for key, value in data.items():
        setattr(supplier, key, _enum_value(value))

    searchable_fields = {
        "name",
        "supplier_type",
        "country",
        "city",
        "address",
        "tax_id",
        "website",
        "status",
        "notes",
    }

    if searchable_fields.intersection(data):
        supplier.description_embedding = safe_embed_supplier_text(
            supplier_searchable_text(supplier)
        )

    db.commit()
    db.refresh(supplier)
    return supplier


def delete_supplier(
    db: Session,
    current_user: User,
    supplier_id: int,
) -> None:
    supplier = get_supplier_or_404(db, supplier_id, current_user)
    db.delete(supplier)
    db.commit()


def get_supplier_contact_or_404(
    db: Session,
    current_user: User,
    supplier_id: int,
    contact_id: int,
) -> SupplierContact:
    get_supplier_or_404(db, supplier_id, current_user)

    contact = (
        db.query(SupplierContact)
        .filter(
            SupplierContact.id == contact_id,
            SupplierContact.supplier_id == supplier_id,
        )
        .first()
    )

    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": SUPPLIER_CONTACT_NOT_FOUND,
                "message": "Supplier contact not found",
            },
        )

    return contact


def add_supplier_contact(
    db: Session,
    current_user: User,
    supplier_id: int,
    data: dict,
) -> SupplierContact:
    get_supplier_or_404(db, supplier_id, current_user)

    if data.get("is_primary"):
        db.query(SupplierContact).filter(
            SupplierContact.supplier_id == supplier_id
        ).update(
            {SupplierContact.is_primary: False},
            synchronize_session=False,
        )

    contact = SupplierContact(supplier_id=supplier_id, **data)
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


def update_supplier_contact(
    db: Session,
    current_user: User,
    supplier_id: int,
    contact_id: int,
    data: dict,
) -> SupplierContact:
    contact = get_supplier_contact_or_404(
        db,
        current_user,
        supplier_id,
        contact_id,
    )

    if data.get("is_primary") is True:
        db.query(SupplierContact).filter(
            SupplierContact.supplier_id == supplier_id,
            SupplierContact.id != contact_id,
        ).update(
            {SupplierContact.is_primary: False},
            synchronize_session=False,
        )

    for key, value in data.items():
        setattr(contact, key, value)

    db.commit()
    db.refresh(contact)
    return contact


def delete_supplier_contact(
    db: Session,
    current_user: User,
    supplier_id: int,
    contact_id: int,
) -> None:
    contact = get_supplier_contact_or_404(
        db,
        current_user,
        supplier_id,
        contact_id,
    )
    db.delete(contact)
    db.commit()


def add_supplier_category(
    db: Session,
    current_user: User,
    supplier_id: int,
    category: str,
) -> SupplierCategory:
    get_supplier_or_404(db, supplier_id, current_user)

    existing = (
        db.query(SupplierCategory)
        .filter(
            SupplierCategory.supplier_id == supplier_id,
            SupplierCategory.category.ilike(category),
        )
        .first()
    )

    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": SUPPLIER_CATEGORY_ALREADY_EXISTS,
                "message": "Supplier category already exists",
            },
        )

    record = SupplierCategory(
        supplier_id=supplier_id,
        category=category,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def delete_supplier_category(
    db: Session,
    current_user: User,
    supplier_id: int,
    category_id: int,
) -> None:
    get_supplier_or_404(db, supplier_id, current_user)

    record = (
        db.query(SupplierCategory)
        .filter(
            SupplierCategory.id == category_id,
            SupplierCategory.supplier_id == supplier_id,
        )
        .first()
    )

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": SUPPLIER_CATEGORY_NOT_FOUND,
                "message": "Supplier category not found",
            },
        )

    db.delete(record)
    db.commit()


def add_supplier_document(
    db: Session,
    current_user: User,
    supplier_id: int,
    data: dict,
) -> SupplierDocument:
    get_supplier_or_404(db, supplier_id, current_user)

    asset_id = data.get("asset_id")

    if asset_id is not None:
        asset = (
            db.query(FileAsset)
            .filter(
                FileAsset.id == asset_id,
                FileAsset.company_id == tenant_id(current_user),
                FileAsset.status == FileAssetStatus.READY.value,
            )
            .first()
        )

        if asset is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": ASSET_NOT_READY,
                    "message": "Asset is unavailable or does not belong to this company",
                },
            )

    record = SupplierDocument(
        supplier_id=supplier_id,
        created_by_user_id=current_user.id,
        **data,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def delete_supplier_document(
    db: Session,
    current_user: User,
    supplier_id: int,
    document_id: int,
) -> None:
    get_supplier_or_404(db, supplier_id, current_user)

    record = (
        db.query(SupplierDocument)
        .filter(
            SupplierDocument.id == document_id,
            SupplierDocument.supplier_id == supplier_id,
        )
        .first()
    )

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": SUPPLIER_DOCUMENT_NOT_FOUND,
                "message": "Supplier document not found",
            },
        )

    db.delete(record)
    db.commit()


def get_supplier_evaluation_or_404(
    db: Session,
    current_user: User,
    supplier_id: int,
    evaluation_id: int,
) -> SupplierEvaluation:
    get_supplier_or_404(db, supplier_id, current_user)

    evaluation = (
        db.query(SupplierEvaluation)
        .filter(
            SupplierEvaluation.id == evaluation_id,
            SupplierEvaluation.supplier_id == supplier_id,
        )
        .first()
    )

    if evaluation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": SUPPLIER_EVALUATION_NOT_FOUND,
                "message": "Supplier evaluation not found",
            },
        )

    return evaluation


def add_supplier_evaluation(
    db: Session,
    current_user: User,
    supplier_id: int,
    data: dict,
) -> SupplierEvaluation:
    get_supplier_or_404(db, supplier_id, current_user)

    evaluation = SupplierEvaluation(
        supplier_id=supplier_id,
        evaluator_user_id=current_user.id,
        **data,
    )
    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)
    return evaluation


def update_supplier_evaluation(
    db: Session,
    current_user: User,
    supplier_id: int,
    evaluation_id: int,
    data: dict,
) -> SupplierEvaluation:
    evaluation = get_supplier_evaluation_or_404(
        db,
        current_user,
        supplier_id,
        evaluation_id,
    )

    for key, value in data.items():
        setattr(evaluation, key, value)

    db.commit()
    db.refresh(evaluation)
    return evaluation


def delete_supplier_evaluation(
    db: Session,
    current_user: User,
    supplier_id: int,
    evaluation_id: int,
) -> None:
    evaluation = get_supplier_evaluation_or_404(
        db,
        current_user,
        supplier_id,
        evaluation_id,
    )
    db.delete(evaluation)
    db.commit()


def get_supplier_performance(
    db: Session,
    current_user: User,
    supplier_id: int,
) -> SupplierPerformanceOut:
    supplier = get_supplier_or_404(
        db,
        supplier_id,
        current_user,
        include_relations=True,
    )
    return calculate_supplier_performance(
        supplier.id,
        list(supplier.evaluations or []),
    )


def ensure_supplier_embeddings(
    db: Session,
    current_user: User,
    supplier_ids: Optional[Sequence[int]] = None,
) -> None:
    query = _supplier_query(db).filter(
        Supplier.company_id == tenant_id(current_user),
        Supplier.description_embedding.is_(None),
    )

    if supplier_ids is not None:
        if not supplier_ids:
            return
        query = query.filter(Supplier.id.in_(supplier_ids))

    changed = False

    for supplier in query.limit(50).all():
        embedding = safe_embed_supplier_text(supplier_searchable_text(supplier))
        if embedding is None:
            continue
        supplier.description_embedding = embedding
        changed = True

    if changed:
        db.commit()
