from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from Models import User

from ..models import SupplierStatus, SupplierType
from ..schemas import (
    SupplierCategoryCreate,
    SupplierCategoryOut,
    SupplierContactCreate,
    SupplierContactOut,
    SupplierContactUpdate,
    SupplierCreate,
    SupplierDocumentCreate,
    SupplierDocumentOut,
    SupplierEvaluationCreate,
    SupplierEvaluationOut,
    SupplierEvaluationUpdate,
    SupplierOut,
    SupplierPerformanceOut,
    SupplierUpdate,
)
from ..services import (
    add_supplier_category,
    add_supplier_contact,
    add_supplier_document,
    add_supplier_evaluation,
    category_to_out,
    contact_to_out,
    create_supplier,
    delete_supplier,
    delete_supplier_category,
    delete_supplier_contact,
    delete_supplier_document,
    delete_supplier_evaluation,
    document_to_out,
    evaluation_to_out,
    get_supplier_or_404,
    get_supplier_performance,
    list_suppliers,
    supplier_to_out,
    update_supplier,
    update_supplier_contact,
    update_supplier_evaluation,
)

router = APIRouter(prefix="/suppliers")


@router.post("", response_model=SupplierOut, status_code=status.HTTP_201_CREATED)
def create_supplier_route(
    payload: SupplierCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("supplier_management:create")),
):
    supplier = create_supplier(
        db=db,
        current_user=current_user,
        data=payload.model_dump(),
    )
    return supplier_to_out(supplier, include_relations=False)


@router.get("", response_model=list[SupplierOut])
def list_supplier_routes(
    q: Optional[str] = Query(None, min_length=1),
    supplier_status: Optional[SupplierStatus] = Query(None, alias="status"),
    supplier_type: Optional[SupplierType] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("supplier_management:read")),
):
    suppliers = list_suppliers(
        db=db,
        current_user=current_user,
        query_text=q,
        supplier_status=supplier_status.value if supplier_status else None,
        supplier_type=supplier_type.value if supplier_type else None,
        limit=limit,
        offset=offset,
    )
    return [supplier_to_out(item, include_relations=False) for item in suppliers]


@router.get("/{supplier_id}/performance", response_model=SupplierPerformanceOut)
def supplier_performance(
    supplier_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("supplier_management:read")),
):
    return get_supplier_performance(db, current_user, supplier_id)


@router.post("/{supplier_id}/contacts", response_model=SupplierContactOut, status_code=status.HTTP_201_CREATED)
def create_supplier_contact(
    supplier_id: int,
    payload: SupplierContactCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("supplier_management:update")),
):
    return contact_to_out(
        add_supplier_contact(
            db=db,
            current_user=current_user,
            supplier_id=supplier_id,
            data=payload.model_dump(),
        )
    )


@router.patch("/{supplier_id}/contacts/{contact_id}", response_model=SupplierContactOut)
def patch_supplier_contact(
    supplier_id: int,
    contact_id: int,
    payload: SupplierContactUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("supplier_management:update")),
):
    return contact_to_out(
        update_supplier_contact(
            db=db,
            current_user=current_user,
            supplier_id=supplier_id,
            contact_id=contact_id,
            data=payload.model_dump(exclude_unset=True),
        )
    )


@router.delete("/{supplier_id}/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_supplier_contact(
    supplier_id: int,
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("supplier_management:update")),
):
    delete_supplier_contact(db, current_user, supplier_id, contact_id)
    return None


@router.post("/{supplier_id}/categories", response_model=SupplierCategoryOut, status_code=status.HTTP_201_CREATED)
def create_supplier_category(
    supplier_id: int,
    payload: SupplierCategoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("supplier_management:update")),
):
    return category_to_out(
        add_supplier_category(
            db=db,
            current_user=current_user,
            supplier_id=supplier_id,
            category=payload.category,
        )
    )


@router.delete("/{supplier_id}/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_supplier_category(
    supplier_id: int,
    category_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("supplier_management:update")),
):
    delete_supplier_category(db, current_user, supplier_id, category_id)
    return None


@router.post("/{supplier_id}/documents", response_model=SupplierDocumentOut, status_code=status.HTTP_201_CREATED)
def create_supplier_document(
    supplier_id: int,
    payload: SupplierDocumentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("supplier_management:update")),
):
    return document_to_out(
        add_supplier_document(
            db=db,
            current_user=current_user,
            supplier_id=supplier_id,
            data=payload.model_dump(),
        )
    )


@router.delete("/{supplier_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_supplier_document(
    supplier_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("supplier_management:update")),
):
    delete_supplier_document(db, current_user, supplier_id, document_id)
    return None


@router.post("/{supplier_id}/evaluations", response_model=SupplierEvaluationOut, status_code=status.HTTP_201_CREATED)
def create_supplier_evaluation(
    supplier_id: int,
    payload: SupplierEvaluationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("supplier_management:update")),
):
    return evaluation_to_out(
        add_supplier_evaluation(
            db=db,
            current_user=current_user,
            supplier_id=supplier_id,
            data=payload.model_dump(),
        )
    )


@router.patch("/{supplier_id}/evaluations/{evaluation_id}", response_model=SupplierEvaluationOut)
def patch_supplier_evaluation(
    supplier_id: int,
    evaluation_id: int,
    payload: SupplierEvaluationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("supplier_management:update")),
):
    return evaluation_to_out(
        update_supplier_evaluation(
            db=db,
            current_user=current_user,
            supplier_id=supplier_id,
            evaluation_id=evaluation_id,
            data=payload.model_dump(exclude_unset=True),
        )
    )


@router.delete("/{supplier_id}/evaluations/{evaluation_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_supplier_evaluation(
    supplier_id: int,
    evaluation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("supplier_management:update")),
):
    delete_supplier_evaluation(db, current_user, supplier_id, evaluation_id)
    return None


@router.get("/{supplier_id}", response_model=SupplierOut)
def get_supplier_route(
    supplier_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("supplier_management:read")),
):
    supplier = get_supplier_or_404(
        db=db,
        supplier_id=supplier_id,
        current_user=current_user,
        include_relations=True,
    )
    return supplier_to_out(
        supplier,
        include_relations=True,
        include_performance=True,
    )


@router.patch("/{supplier_id}", response_model=SupplierOut)
def patch_supplier_route(
    supplier_id: int,
    payload: SupplierUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("supplier_management:update")),
):
    supplier = update_supplier(
        db=db,
        current_user=current_user,
        supplier_id=supplier_id,
        data=payload.model_dump(exclude_unset=True),
    )
    return supplier_to_out(
        supplier,
        include_relations=True,
        include_performance=True,
    )


@router.delete("/{supplier_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_supplier_route(
    supplier_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("supplier_management:delete")),
):
    delete_supplier(db, current_user, supplier_id)
    return None
