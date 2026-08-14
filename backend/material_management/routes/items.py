from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from Models import User
from Models.task_result import TaskResult
from core.celery.celery_app import celery_app
from db.init_db import get_db
from deps import require_permission

from ..schemas import (
    ItemAlternativeCreate,
    ItemAlternativeOut,
    ItemAlternativeUpdate,
    ItemCategoryCreate,
    ItemCategoryOut,
    ItemCategoryTreeOut,
    ItemCategoryUpdate,
    ItemCreate,
    ItemDocumentCreate,
    ItemDocumentOut,
    ItemImportRequest,
    ItemImportTaskOut,
    ItemOut,
    ItemType,
    ItemUpdate,
    UnitCreate,
    UnitOut,
    UnitType,
    UnitUpdate,
)
from ..services import (
    add_item_alternative,
    add_item_document,
    alternative_to_out,
    build_category_tree,
    category_to_out,
    create_category,
    create_item,
    create_unit,
    delete_category,
    delete_item,
    delete_item_alternative,
    delete_item_document,
    delete_unit,
    document_to_out,
    get_item_or_404,
    items_to_out,
    list_categories,
    list_items,
    list_units,
    unit_to_out,
    update_category,
    update_item,
    update_item_alternative,
    update_unit,
    validate_item_import_asset,
)

router = APIRouter()


@router.get("/categories/tree", response_model=list[ItemCategoryTreeOut])
def get_category_tree(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("material_management:read")),
):
    return build_category_tree(list_categories(db, current_user))


@router.post(
    "/categories", response_model=ItemCategoryOut, status_code=status.HTTP_201_CREATED
)
def create_item_category(
    payload: ItemCategoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("material_management:create")),
):
    return category_to_out(create_category(db, current_user, payload.model_dump()))


@router.patch("/categories/{category_id}", response_model=ItemCategoryOut)
def patch_item_category(
    category_id: int,
    payload: ItemCategoryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("material_management:update")),
):
    return category_to_out(
        update_category(
            db,
            current_user,
            category_id,
            payload.model_dump(exclude_unset=True),
        )
    )


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_item_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("material_management:delete")),
):
    delete_category(db, current_user, category_id)
    return None


@router.get("/units", response_model=list[UnitOut])
def get_units(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("material_management:read")),
):
    return [unit_to_out(unit) for unit in list_units(db, current_user)]


@router.post("/units", response_model=UnitOut, status_code=status.HTTP_201_CREATED)
def create_item_unit(
    payload: UnitCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("material_management:create")),
):
    return unit_to_out(create_unit(db, current_user, payload.model_dump()))


@router.patch("/units/{unit_id}", response_model=UnitOut)
def patch_item_unit(
    unit_id: int,
    payload: UnitUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("material_management:update")),
):
    return unit_to_out(
        update_unit(
            db,
            current_user,
            unit_id,
            payload.model_dump(exclude_unset=True),
        )
    )


@router.delete("/units/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_item_unit(
    unit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("material_management:delete")),
):
    delete_unit(db, current_user, unit_id)
    return None


@router.post(
    "/import", response_model=ItemImportTaskOut, status_code=status.HTTP_202_ACCEPTED
)
def import_items(
    payload: ItemImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("material_management:import")),
):
    validate_item_import_asset(db, current_user, payload.asset_id)

    task = TaskResult(
        task_type="material_import",
        status="pending",
        created_by_user_id=current_user.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    try:
        dispatched = celery_app.send_task(
            "material_management.tasks.import_items",
            args=[str(task.id), payload.asset_id, current_user.id],
        )
        task.celery_task_id = dispatched.id
        db.commit()
    except Exception as exc:
        task.status = "failure"
        task.error_message = str(exc)
        db.commit()
        raise

    return ItemImportTaskOut(
        task_id=str(task.id),
        task_type=task.task_type,
        status=task.status,
    )


@router.post("", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
def create_material_item(
    payload: ItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("material_management:create")),
):
    item = create_item(db, current_user, payload.model_dump())
    return items_to_out(
        db,
        current_user,
        [item],
        include_relations=True,
    )[0]


@router.get("", response_model=list[ItemOut])
def get_material_items(
    q: Optional[str] = Query(None, min_length=1),
    category_id: Optional[int] = Query(None, alias="category", gt=0),
    item_type: Optional[ItemType] = Query(None),
    is_active: Optional[bool] = Query(None),
    model_id: Optional[int] = Query(None, gt=0),
    model: Optional[str] = Query(None, min_length=1),
    manufacturer: Optional[str] = Query(None, min_length=1),
    model_type: Optional[str] = Query(None, min_length=1),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("material_management:read")),
):
    items = list_items(
        db=db,
        current_user=current_user,
        query_text=q,
        category_id=category_id,
        item_type=item_type.value if item_type else None,
        is_active=is_active,
        model_id=model_id,
        model_name=model,
        manufacturer=manufacturer,
        model_type=model_type,
        limit=limit,
        offset=offset,
    )
    return items_to_out(
        db,
        current_user,
        items,
        include_relations=False,
    )


@router.post(
    "/{item_id}/alternatives",
    response_model=ItemAlternativeOut,
    status_code=status.HTTP_201_CREATED,
)
def create_alternative(
    item_id: int,
    payload: ItemAlternativeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("material_management:update")),
):
    return alternative_to_out(
        add_item_alternative(
            db,
            current_user,
            item_id,
            payload.model_dump(),
        )
    )


@router.patch(
    "/{item_id}/alternatives/{alternative_id}", response_model=ItemAlternativeOut
)
def patch_alternative(
    item_id: int,
    alternative_id: int,
    payload: ItemAlternativeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("material_management:update")),
):
    return alternative_to_out(
        update_item_alternative(
            db,
            current_user,
            item_id,
            alternative_id,
            payload.model_dump(exclude_unset=True),
        )
    )


@router.delete(
    "/{item_id}/alternatives/{alternative_id}", status_code=status.HTTP_204_NO_CONTENT
)
def remove_alternative(
    item_id: int,
    alternative_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("material_management:update")),
):
    delete_item_alternative(db, current_user, item_id, alternative_id)
    return None


@router.post(
    "/{item_id}/documents",
    response_model=ItemDocumentOut,
    status_code=status.HTTP_201_CREATED,
)
def create_document(
    item_id: int,
    payload: ItemDocumentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("material_management:update")),
):
    return document_to_out(
        add_item_document(
            db,
            current_user,
            item_id,
            payload.model_dump(),
        )
    )


@router.delete(
    "/{item_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT
)
def remove_document(
    item_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("material_management:update")),
):
    delete_item_document(db, current_user, item_id, document_id)
    return None


@router.get("/{item_id}", response_model=ItemOut)
def get_material_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("material_management:read")),
):
    item = get_item_or_404(db, current_user, item_id, include_relations=True)
    return items_to_out(
        db,
        current_user,
        [item],
        include_relations=True,
    )[0]


@router.patch("/{item_id}", response_model=ItemOut)
def patch_material_item(
    item_id: int,
    payload: ItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("material_management:update")),
):
    item = update_item(
        db,
        current_user,
        item_id,
        payload.model_dump(exclude_unset=True),
    )
    return items_to_out(
        db,
        current_user,
        [item],
        include_relations=True,
    )[0]


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_material_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("material_management:delete")),
):
    delete_item(db, current_user, item_id)
    return None
