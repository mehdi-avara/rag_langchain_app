from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.orm import Session

from Models.user import User

from ..models import MaterialRequisition, MaterialRequisitionItem
from ..services import tenant_id


def search_requisitions_by_item_ids(
    db: Session,
    current_user: User,
    item_ids: Sequence[int],
    requisition_ids: Sequence[int] | None,
    limit: int,
) -> list[MaterialRequisition]:
    if not item_ids:
        return []

    query = (
        db.query(MaterialRequisition)
        .join(
            MaterialRequisitionItem,
            MaterialRequisitionItem.material_requisition_id
            == MaterialRequisition.id,
        )
        .filter(
            MaterialRequisition.company_id == tenant_id(current_user),
            MaterialRequisitionItem.item_id.in_(list(item_ids)),
        )
        .distinct()
    )

    if requisition_ids:
        query = query.filter(
            MaterialRequisition.id.in_(list(requisition_ids))
        )

    return (
        query.order_by(MaterialRequisition.created_at.desc())
        .limit(limit)
        .all()
    )
