from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from Models.user import User

from .schemas import BusinessFlowResponse
from .services import BusinessFlowNotFound, build_business_flow


business_router = APIRouter(
    prefix="/business-management",
    tags=["business_management"],
)


@business_router.get(
    "/flow/{type}/{id}",
    response_model=BusinessFlowResponse,
)
def get_business_flow(
    type: Literal["mr", "rfq", "po", "grn", "stock"],
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("business_management:flow:read")),
) -> BusinessFlowResponse:
    if current_user.company_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has no active company.",
        )

    try:
        return build_business_flow(
            db=db,
            company_id=current_user.company_id,
            root_type=type,
            root_id=id,
        )
    except BusinessFlowNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
