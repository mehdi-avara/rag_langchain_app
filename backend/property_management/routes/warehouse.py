from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from db.init_db import get_db
from deps import require_permission
from Models import User
from model_management.models import ManagedModel

from ..models import WarehouseItem
from ..schemas import WarehouseCountAdjustRequest, WarehouseItemCreate, WarehouseItemOut, WarehouseItemUpdate, WarehouseSearchRequest
from ..services import get_model_or_404, get_warehouse_item_or_404, require_company, warehouse_item_to_out


router = APIRouter(prefix="/warehouse")


@router.post("", response_model=WarehouseItemOut, status_code=status.HTTP_201_CREATED)
def create_warehouse_item(
    payload: WarehouseItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("property_management:create")),
):
    model = get_model_or_404(db, payload.model_id, current_user)

    item = WarehouseItem(
        company_id=require_company(current_user),
        owner_id=current_user.id,
        model_id=model.id,
        color=payload.color,
        count=payload.count,
        description=payload.description,
        unit_cost=payload.unit_cost,
        unit_current_value=payload.unit_current_value,
    )
    item.model = model

    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Warehouse item already exists for this model and color") from exc
    db.refresh(item)

    return warehouse_item_to_out(item)


@router.get("", response_model=List[WarehouseItemOut])
def list_warehouse_items(
    model_id: Optional[int] = Query(None),
    model_query: Optional[str] = Query(None),
    model_type: Optional[str] = Query(None),
    color: Optional[str] = Query(None),
    description: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("property_management:read")),
):
    query = (
        db.query(WarehouseItem)
        .options(joinedload(WarehouseItem.model))
        .join(WarehouseItem.model)
        .filter(WarehouseItem.company_id == require_company(current_user))
    )

    if model_id is not None:
        query = query.filter(WarehouseItem.model_id == model_id)

    if model_query:
        pattern = f"%{model_query}%"
        query = query.filter(
            or_(
                ManagedModel.manufacturer.ilike(pattern),
                ManagedModel.model.ilike(pattern),
            )
        )

    if model_type:
        query = query.filter(ManagedModel.type == model_type)

    if color:
        query = query.filter(WarehouseItem.color.ilike(f"%{color}%"))

    if description:
        query = query.filter(WarehouseItem.description.ilike(f"%{description}%"))

    items = query.order_by(WarehouseItem.created_at.desc()).offset(offset).limit(limit).all()
    return [warehouse_item_to_out(item) for item in items]



@router.post("/search", response_model=List[WarehouseItemOut])
def search_warehouse_items(
    payload: WarehouseSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("property_management:read")),
):
    query = (
        db.query(WarehouseItem)
        .options(joinedload(WarehouseItem.model))
        .join(WarehouseItem.model)
        .filter(WarehouseItem.company_id == require_company(current_user))
    )

    if payload.ids:
        query = query.filter(WarehouseItem.id.in_(list(dict.fromkeys(payload.ids))))

    if payload.model_type:
        query = query.filter(ManagedModel.type == payload.model_type)

    pattern = f"%{payload.query}%"
    query = query.filter(
        or_(
            ManagedModel.manufacturer.ilike(pattern),
            ManagedModel.model.ilike(pattern),
            ManagedModel.type.ilike(pattern),
            WarehouseItem.color.ilike(pattern),
            WarehouseItem.description.ilike(pattern),
        )
    )

    items = (
        query
        .order_by(WarehouseItem.created_at.desc())
        .offset(payload.offset)
        .limit(payload.limit)
        .all()
    )

    return [warehouse_item_to_out(item) for item in items]


@router.get("/{item_id}", response_model=WarehouseItemOut)
def get_warehouse_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("property_management:read")),
):
    item = (
        db.query(WarehouseItem)
        .options(joinedload(WarehouseItem.model))
        .filter(WarehouseItem.id == item_id, WarehouseItem.company_id == require_company(current_user))
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Warehouse item not found")
    return warehouse_item_to_out(item)


@router.put("/{item_id}", response_model=WarehouseItemOut)
def update_warehouse_item(
    item_id: int,
    payload: WarehouseItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("property_management:update")),
):
    item = get_warehouse_item_or_404(db, item_id, current_user)
    data = payload.model_dump(exclude_unset=True)

    if "model_id" in data and data["model_id"] is not None:
        model = get_model_or_404(db, data["model_id"], current_user)
        item.model_id = model.id
        item.model = model

    for key, value in data.items():
        if key == "model_id":
            continue
        setattr(item, key, value)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Warehouse item already exists for this model and color") from exc
    db.refresh(item)
    return warehouse_item_to_out(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_warehouse_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("property_management:delete")),
):
    item = get_warehouse_item_or_404(db, item_id, current_user)
    if item.count > 0:
        raise HTTPException(status_code=409, detail="Cannot delete a warehouse item with positive count")

    db.delete(item)
    db.commit()
    return None


@router.post("/{item_id}/increase", response_model=WarehouseItemOut)
def increase_warehouse_count(
    item_id: int,
    payload: WarehouseCountAdjustRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("property_management:update")),
):
    item = get_warehouse_item_or_404(db, item_id, current_user)
    item.count += payload.amount
    db.commit()
    db.refresh(item)
    return warehouse_item_to_out(item)


@router.post("/{item_id}/decrease", response_model=WarehouseItemOut)
def decrease_warehouse_count(
    item_id: int,
    payload: WarehouseCountAdjustRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("property_management:update")),
):
    item = get_warehouse_item_or_404(db, item_id, current_user)
    if item.count < payload.amount:
        raise HTTPException(status_code=409, detail="Warehouse item count cannot become negative")

    item.count -= payload.amount
    db.commit()
    db.refresh(item)
    return warehouse_item_to_out(item)
