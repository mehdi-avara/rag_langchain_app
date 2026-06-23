from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.orm import Session

from Models.user import User

from ..models import RFQItem, RequestForQuotation
from ..services import tenant_id


def search_rfqs_by_item_ids(
    db: Session,
    current_user: User,
    item_ids: Sequence[int],
    rfq_ids: Sequence[int] | None,
    limit: int,
) -> list[RequestForQuotation]:
    if not item_ids:
        return []

    query = (
        db.query(RequestForQuotation)
        .join(RFQItem, RFQItem.rfq_id == RequestForQuotation.id)
        .filter(
            RequestForQuotation.company_id == tenant_id(current_user),
            RFQItem.item_id.in_(list(item_ids)),
        )
        .distinct()
    )

    if rfq_ids:
        query = query.filter(RequestForQuotation.id.in_(list(rfq_ids)))

    return (
        query.order_by(RequestForQuotation.created_at.desc())
        .limit(limit)
        .all()
    )
