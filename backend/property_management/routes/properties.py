from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from Models import User

from ..models import OwnedProperty
from ..schemas import OwnedPropertyCreate, OwnedPropertyOut, OwnedPropertyUpdate
from ..services import get_owned_property_or_404, owned_property_to_out, require_company


router = APIRouter(prefix="/properties")


@router.post("", response_model=OwnedPropertyOut, status_code=status.HTTP_201_CREATED)
def create_property(
    payload: OwnedPropertyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("property_management:create")),
):
    owned_property = OwnedProperty(
        company_id=require_company(current_user),
        owner_id=current_user.id,
        category=payload.category,
        title=payload.title,
        purchase_cost=payload.purchase_cost,
        current_estimated_value=payload.current_estimated_value,
        description=payload.description,
    )
    db.add(owned_property)
    db.commit()
    db.refresh(owned_property)
    return owned_property_to_out(owned_property)


@router.get("", response_model=List[OwnedPropertyOut])
def list_properties(
    category: Optional[str] = Query(None),
    title: Optional[str] = Query(None),
    description: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("property_management:read")),
):
    query = db.query(OwnedProperty).filter(OwnedProperty.company_id == require_company(current_user))

    if category:
        query = query.filter(OwnedProperty.category == category)

    if title:
        query = query.filter(OwnedProperty.title.ilike(f"%{title}%"))

    if description:
        query = query.filter(OwnedProperty.description.ilike(f"%{description}%"))

    properties = query.order_by(OwnedProperty.created_at.desc()).offset(offset).limit(limit).all()
    return [owned_property_to_out(item) for item in properties]


@router.get("/{property_id}", response_model=OwnedPropertyOut)
def get_property(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("property_management:read")),
):
    return owned_property_to_out(get_owned_property_or_404(db, property_id, current_user))


@router.put("/{property_id}", response_model=OwnedPropertyOut)
def update_property(
    property_id: int,
    payload: OwnedPropertyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("property_management:update")),
):
    owned_property = get_owned_property_or_404(db, property_id, current_user)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(owned_property, key, value)
    db.commit()
    db.refresh(owned_property)
    return owned_property_to_out(owned_property)


@router.delete("/{property_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_property(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("property_management:delete")),
):
    owned_property = get_owned_property_or_404(db, property_id, current_user)
    db.delete(owned_property)
    db.commit()
    return None
