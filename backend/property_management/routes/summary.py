from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from Models import User

from ..schemas import NetWorthSummaryOut
from ..services import build_net_worth_summary


router = APIRouter(prefix="/summary")


@router.get("/net-worth", response_model=NetWorthSummaryOut, status_code=status.HTTP_200_OK)
def get_net_worth_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("property_management:summary")),
):
    return build_net_worth_summary(db, current_user)
