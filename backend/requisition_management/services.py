from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from Models.company import Company
from Models.user import User
from core.exceptions.error_codes import (
    MATERIAL_REQUISITION_ACCESS_DENIED,
    MATERIAL_REQUISITION_HAS_NO_ITEMS,
    MATERIAL_REQUISITION_INVALID_ESTIMATED_COST,
    MATERIAL_REQUISITION_INVALID_STATUS_TRANSITION,
    MATERIAL_REQUISITION_ITEM_NOT_FOUND,
    MATERIAL_REQUISITION_NOT_EDITABLE,
    MATERIAL_REQUISITION_NOT_FOUND,
    MATERIAL_REQUISITION_NUMBER_GENERATION_FAILED,
    USER_HAS_NO_COMPANY,
)

from .models import (
    MaterialRequisition,
    MaterialRequisitionItem,
    MaterialRequisitionPriority,
    MaterialRequisitionStatus,
    MaterialRequisitionStatusHistory,
)


def _raise(status_code: int, code: str, message: str):
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def tenant_id(current_user: User) -> int:
    if current_user.company_id is None:
        _raise(
            status.HTTP_403_FORBIDDEN,
            USER_HAS_NO_COMPANY,
            "Current user does not belong to a company",
        )
    return current_user.company_id


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _requisition_query(db: Session):
    return db.query(MaterialRequisition).options(
        selectinload(MaterialRequisition.items),
        selectinload(MaterialRequisition.status_history),
    )


def _next_mr_number(db: Session, company_id: int) -> str:
    year = datetime.utcnow().year
    highest = 0

    rows = (
        db.query(MaterialRequisition.mr_number)
        .filter(
            MaterialRequisition.company_id == company_id,
            MaterialRequisition.mr_number.like(f"MR-{year}-%"),
        )
        .all()
    )

    for (mr_number,) in rows:
        match = re.fullmatch(rf"MR-{year}-(\d+)", mr_number or "")
        if match:
            highest = max(highest, int(match.group(1)))

    return f"MR-{year}-{highest + 1:04d}"


def get_requisition_or_404(
    db: Session,
    current_user: User,
    requisition_id: int,
) -> MaterialRequisition:
    requisition = (
        _requisition_query(db)
        .filter(
            MaterialRequisition.id == requisition_id,
            MaterialRequisition.company_id == tenant_id(current_user),
        )
        .first()
    )

    if requisition is None:
        _raise(
            status.HTTP_404_NOT_FOUND,
            MATERIAL_REQUISITION_NOT_FOUND,
            "Material requisition not found",
        )

    return requisition


def _get_requisition_item_or_404(
    db: Session,
    requisition: MaterialRequisition,
    requisition_item_id: int,
) -> MaterialRequisitionItem:
    requisition_item = (
        db.query(MaterialRequisitionItem)
        .filter(
            MaterialRequisitionItem.id == requisition_item_id,
            MaterialRequisitionItem.material_requisition_id == requisition.id,
        )
        .first()
    )

    if requisition_item is None:
        _raise(
            status.HTTP_404_NOT_FOUND,
            MATERIAL_REQUISITION_ITEM_NOT_FOUND,
            "Material requisition item not found",
        )

    return requisition_item


def _assert_requester(
    requisition: MaterialRequisition,
    current_user: User,
) -> None:
    if requisition.requested_by_user_id != current_user.id:
        _raise(
            status.HTTP_403_FORBIDDEN,
            MATERIAL_REQUISITION_ACCESS_DENIED,
            "Only the requester can modify this material requisition",
        )


def _assert_draft(requisition: MaterialRequisition) -> None:
    if requisition.status != MaterialRequisitionStatus.DRAFT.value:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            MATERIAL_REQUISITION_NOT_EDITABLE,
            "Only draft material requisitions can be modified",
        )


def _user_has_permission(current_user: User, permission_name: str) -> bool:
    return any(
        permission.name == permission_name
        for role in current_user.roles
        if role.is_active
        for permission in role.permissions
    )


def _require_approval_permission(current_user: User) -> None:
    if not _user_has_permission(
        current_user,
        "requisition_management:approve",
    ):
        _raise(
            status.HTTP_403_FORBIDDEN,
            MATERIAL_REQUISITION_ACCESS_DENIED,
            "Approval permission is required",
        )


def _self_approval_allowed(db: Session, current_user: User) -> bool:
    """Whether this user's company permits approving one's own requisition.

    Controlled by Company.allow_self_approval (a company-admin setting). Defaults
    to False, preserving the requester-cannot-approve-own segregation of duties.
    The workflow steps (Draft → Submitted → Approved) are unchanged either way;
    this flag only governs whether the same user may perform the approval step.
    """
    if current_user.company_id is None:
        return False

    allowed = (
        db.query(Company.allow_self_approval)
        .filter(Company.id == current_user.company_id)
        .scalar()
    )

    return bool(allowed)


def _validate_estimated_cost_values(
    db: Session,
    values: dict[str, Any],
) -> None:
    fields = (
        "estimated_unit_cost",
        "currency_id",
        "estimated_unit_cost_base",
        "base_currency_id",
        "exchange_rate_used",
    )
    selected = [values.get(field) for field in fields]

    if all(value is None for value in selected):
        return

    if any(value is None for value in selected):
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            MATERIAL_REQUISITION_INVALID_ESTIMATED_COST,
            "Estimated cost fields must be provided together",
        )

    from shared.currency.services import get_currency_or_404

    get_currency_or_404(db, values["currency_id"])
    get_currency_or_404(db, values["base_currency_id"])


def _build_requisition_item(
    db: Session,
    current_user: User,
    material_requisition_id: int,
    data: dict[str, Any],
) -> MaterialRequisitionItem:
    from material_management.services import get_item_reference

    reference = get_item_reference(
        db=db,
        current_user=current_user,
        item_id=data["item_id"],
    )

    _validate_estimated_cost_values(db, data)

    return MaterialRequisitionItem(
        material_requisition_id=material_requisition_id,
        item_id=reference["id"],
        item_code=reference["item_code"],
        item_name=reference["name"],
        unit_id=reference["unit_id"],
        unit_code=reference["unit_code"],
        quantity=data["quantity"],
        estimated_unit_cost=data.get("estimated_unit_cost"),
        currency_id=data.get("currency_id"),
        estimated_unit_cost_base=data.get("estimated_unit_cost_base"),
        base_currency_id=data.get("base_currency_id"),
        exchange_rate_used=data.get("exchange_rate_used"),
        notes=data.get("notes"),
    )


def _record_status_history(
    db: Session,
    requisition: MaterialRequisition,
    from_status: Optional[str],
    to_status: str,
    action: str,
    current_user: User,
    note: Optional[str],
) -> None:
    history = MaterialRequisitionStatusHistory(
        material_requisition_id=requisition.id,
        from_status=from_status,
        to_status=to_status,
        action=action,
        note=note,
        changed_by_user_id=current_user.id,
    )
    requisition.status_history.append(history)
    db.add(history)


def create_requisition(
    db: Session,
    current_user: User,
    data: dict[str, Any],
) -> MaterialRequisition:
    company_id = tenant_id(current_user)
    items = data.get("items", [])

    for _ in range(5):
        try:
            requisition = MaterialRequisition(
                company_id=company_id,
                mr_number=_next_mr_number(db, company_id),
                requested_by_user_id=current_user.id,
                department_id=data.get("department_id"),
                needed_by_date=data.get("needed_by_date"),
                reason=str(data["reason"]).strip(),
                priority=_enum_value(data.get("priority"))
                or MaterialRequisitionPriority.NORMAL.value,
                status=MaterialRequisitionStatus.DRAFT.value,
                notes=data.get("notes"),
            )
            db.add(requisition)
            db.flush()

            for item_data in items:
                db.add(
                    _build_requisition_item(
                        db=db,
                        current_user=current_user,
                        material_requisition_id=requisition.id,
                        data=item_data,
                    )
                )

            _record_status_history(
                db=db,
                requisition=requisition,
                from_status=None,
                to_status=MaterialRequisitionStatus.DRAFT.value,
                action="created",
                current_user=current_user,
                note=None,
            )

            db.commit()
            return get_requisition_or_404(db, current_user, requisition.id)

        except IntegrityError as exc:
            db.rollback()
            if (
                "uq_material_requisitions_company_mr_number"
                not in str(exc.orig)
            ):
                raise

        except Exception:
            db.rollback()
            raise

    _raise(
        status.HTTP_409_CONFLICT,
        MATERIAL_REQUISITION_NUMBER_GENERATION_FAILED,
        "Could not generate a unique material requisition number",
    )


def list_requisitions(
    db: Session,
    current_user: User,
    requisition_status: Optional[str] = None,
    priority: Optional[str] = None,
    requested_by_user_id: Optional[int] = None,
    department_id: Optional[int] = None,
    page: int = 1,
    size: int = 20,
) -> list[MaterialRequisition]:
    query = _requisition_query(db).filter(
        MaterialRequisition.company_id == tenant_id(current_user)
    )

    if requisition_status:
        query = query.filter(MaterialRequisition.status == requisition_status)

    if priority:
        query = query.filter(MaterialRequisition.priority == _enum_value(priority))

    if requested_by_user_id:
        query = query.filter(
            MaterialRequisition.requested_by_user_id == requested_by_user_id
        )

    if department_id:
        query = query.filter(
            MaterialRequisition.department_id == department_id
        )

    return (
        query.order_by(MaterialRequisition.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )


def search_requisitions(
    db: Session,
    current_user: User,
    query_text: str,
    page: int = 1,
    size: int = 20,
) -> list[MaterialRequisition]:
    pattern = f"%{query_text.strip()}%"

    query = (
        _requisition_query(db)
        .outerjoin(
            MaterialRequisitionItem,
            MaterialRequisitionItem.material_requisition_id
            == MaterialRequisition.id,
        )
        .filter(
            MaterialRequisition.company_id == tenant_id(current_user),
            or_(
                MaterialRequisition.mr_number.ilike(pattern),
                MaterialRequisition.reason.ilike(pattern),
                MaterialRequisition.notes.ilike(pattern),
                MaterialRequisitionItem.item_name.ilike(pattern),
                MaterialRequisitionItem.item_code.ilike(pattern),
            ),
        )
        .distinct()
    )

    return (
        query.order_by(MaterialRequisition.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )


def update_requisition(
    db: Session,
    current_user: User,
    requisition_id: int,
    data: dict[str, Any],
) -> MaterialRequisition:
    requisition = get_requisition_or_404(
        db,
        current_user,
        requisition_id,
    )
    _assert_requester(requisition, current_user)
    _assert_draft(requisition)

    if "department_id" in data:
        requisition.department_id = data["department_id"]

    if "needed_by_date" in data:
        requisition.needed_by_date = data["needed_by_date"]

    if "reason" in data:
        requisition.reason = str(data["reason"]).strip()

    if "priority" in data:
        requisition.priority = _enum_value(data["priority"])

    if "notes" in data:
        requisition.notes = data["notes"]

    db.commit()
    return get_requisition_or_404(db, current_user, requisition.id)


def delete_requisition(
    db: Session,
    current_user: User,
    requisition_id: int,
) -> None:
    requisition = get_requisition_or_404(
        db,
        current_user,
        requisition_id,
    )
    _assert_requester(requisition, current_user)
    _assert_draft(requisition)

    db.delete(requisition)
    db.commit()


def add_requisition_item(
    db: Session,
    current_user: User,
    requisition_id: int,
    data: dict[str, Any],
) -> MaterialRequisitionItem:
    requisition = get_requisition_or_404(
        db,
        current_user,
        requisition_id,
    )
    _assert_requester(requisition, current_user)
    _assert_draft(requisition)

    requisition_item = _build_requisition_item(
        db=db,
        current_user=current_user,
        material_requisition_id=requisition.id,
        data=data,
    )
    db.add(requisition_item)
    db.commit()
    db.refresh(requisition_item)
    return requisition_item


def update_requisition_item(
    db: Session,
    current_user: User,
    requisition_id: int,
    requisition_item_id: int,
    data: dict[str, Any],
) -> MaterialRequisitionItem:
    requisition = get_requisition_or_404(
        db,
        current_user,
        requisition_id,
    )
    _assert_requester(requisition, current_user)
    _assert_draft(requisition)

    requisition_item = _get_requisition_item_or_404(
        db,
        requisition,
        requisition_item_id,
    )

    if "item_id" in data:
        if data["item_id"] is None:
            _raise(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                MATERIAL_REQUISITION_INVALID_ESTIMATED_COST,
                "item_id cannot be null",
            )

        from material_management.services import get_item_reference

        reference = get_item_reference(
            db=db,
            current_user=current_user,
            item_id=data["item_id"],
        )
        requisition_item.item_id = reference["id"]
        requisition_item.item_code = reference["item_code"]
        requisition_item.item_name = reference["name"]
        requisition_item.unit_id = reference["unit_id"]
        requisition_item.unit_code = reference["unit_code"]

    if "quantity" in data:
        requisition_item.quantity = data["quantity"]

    if "notes" in data:
        requisition_item.notes = data["notes"]

    estimate_fields = (
        "estimated_unit_cost",
        "currency_id",
        "estimated_unit_cost_base",
        "base_currency_id",
        "exchange_rate_used",
    )

    if any(field in data for field in estimate_fields):
        merged_values = {
            field: data[field]
            if field in data
            else getattr(requisition_item, field)
            for field in estimate_fields
        }
        _validate_estimated_cost_values(db, merged_values)

        for field, value in merged_values.items():
            setattr(requisition_item, field, value)

    db.commit()
    db.refresh(requisition_item)
    return requisition_item


def delete_requisition_item(
    db: Session,
    current_user: User,
    requisition_id: int,
    requisition_item_id: int,
) -> None:
    requisition = get_requisition_or_404(
        db,
        current_user,
        requisition_id,
    )
    _assert_requester(requisition, current_user)
    _assert_draft(requisition)

    requisition_item = _get_requisition_item_or_404(
        db,
        requisition,
        requisition_item_id,
    )
    db.delete(requisition_item)
    db.commit()


def get_transition_target(
    current_status: str,
    action: str,
) -> Optional[str]:
    transitions = {
        "submit": {
            MaterialRequisitionStatus.DRAFT.value:
            MaterialRequisitionStatus.SUBMITTED.value,
        },
        "start_review": {
            MaterialRequisitionStatus.SUBMITTED.value:
            MaterialRequisitionStatus.UNDER_REVIEW.value,
        },
        "approve": {
            MaterialRequisitionStatus.SUBMITTED.value:
            MaterialRequisitionStatus.APPROVED.value,
            MaterialRequisitionStatus.UNDER_REVIEW.value:
            MaterialRequisitionStatus.APPROVED.value,
        },
        "reject": {
            MaterialRequisitionStatus.SUBMITTED.value:
            MaterialRequisitionStatus.REJECTED.value,
            MaterialRequisitionStatus.UNDER_REVIEW.value:
            MaterialRequisitionStatus.REJECTED.value,
        },
    }

    return transitions.get(action, {}).get(current_status)


def transition_requisition(
    db: Session,
    current_user: User,
    requisition_id: int,
    action: str,
    note: Optional[str] = None,
) -> MaterialRequisition:
    requisition = get_requisition_or_404(
        db,
        current_user,
        requisition_id,
    )
    normalized_action = action.strip().lower()

    if normalized_action == "submit":
        _assert_requester(requisition, current_user)

        if not requisition.items:
            _raise(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                MATERIAL_REQUISITION_HAS_NO_ITEMS,
                "A material requisition must contain at least one item before submission",
            )
    else:
        _require_approval_permission(current_user)

        if (
            requisition.requested_by_user_id == current_user.id
            and not _self_approval_allowed(db, current_user)
        ):
            _raise(
                status.HTTP_403_FORBIDDEN,
                MATERIAL_REQUISITION_ACCESS_DENIED,
                "The requester cannot review, approve, or reject their own requisition",
            )

    target_status = get_transition_target(
        requisition.status,
        normalized_action,
    )

    if target_status is None:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            MATERIAL_REQUISITION_INVALID_STATUS_TRANSITION,
            f"Cannot apply action '{normalized_action}' from status '{requisition.status}'",
        )

    previous_status = requisition.status
    requisition.status = target_status

    _record_status_history(
        db=db,
        requisition=requisition,
        from_status=previous_status,
        to_status=target_status,
        action=normalized_action,
        current_user=current_user,
        note=note,
    )

    db.commit()
    return get_requisition_or_404(db, current_user, requisition.id)


def list_approval_inbox(
    db: Session,
    current_user: User,
    page: int = 1,
    size: int = 20,
) -> list[MaterialRequisition]:
    _require_approval_permission(current_user)

    return (
        _requisition_query(db)
        .filter(
            MaterialRequisition.company_id == tenant_id(current_user),
            MaterialRequisition.status.in_(
                [
                    MaterialRequisitionStatus.SUBMITTED.value,
                    MaterialRequisitionStatus.UNDER_REVIEW.value,
                ]
            ),
        )
        .order_by(
            MaterialRequisition.needed_by_date.asc(),
            MaterialRequisition.created_at.asc(),
        )
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )


def list_status_history(
    db: Session,
    current_user: User,
    requisition_id: int,
) -> list[MaterialRequisitionStatusHistory]:
    requisition = get_requisition_or_404(
        db,
        current_user,
        requisition_id,
    )
    return requisition.status_history

def mark_requisition_ordered_from_purchase_order(
    db: Session,
    current_user: User,
    requisition_id: int,
    purchase_order_reference: str,
) -> MaterialRequisition:
    requisition = get_requisition_or_404(
        db=db,
        current_user=current_user,
        requisition_id=requisition_id,
    )

    if requisition.status == MaterialRequisitionStatus.ORDERED.value:
        return requisition

    if requisition.status != MaterialRequisitionStatus.APPROVED.value:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            MATERIAL_REQUISITION_INVALID_STATUS_TRANSITION,
            "Only approved material requisitions can be marked as ordered",
        )

    previous_status = requisition.status
    requisition.status = MaterialRequisitionStatus.ORDERED.value

    _record_status_history(
        db=db,
        requisition=requisition,
        from_status=previous_status,
        to_status=MaterialRequisitionStatus.ORDERED.value,
        action="purchase_order_created",
        current_user=current_user,
        note=f"Purchase order {purchase_order_reference} was created",
    )

    return requisition
