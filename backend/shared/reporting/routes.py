from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from Models import User
from db.init_db import get_db
from deps import require_permission

from .schemas import KpiRead, ReportRead
from .services import (
    ReportingNotFoundError,
    ReportingValidationError,
    purchase_kpis,
    purchase_report,
    warehouse_kpis,
    warehouse_report,
)


router = APIRouter(tags=["reporting"])


def _raise_validation(message: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": "REPORT_INVALID_REQUEST",
            "message": message,
        },
    )


def _raise_not_found(message: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "REPORT_NOT_FOUND",
            "message": message,
        },
    )


@router.get(
    "/kpi/warehouse_management",
    response_model=list[KpiRead],
)
def get_warehouse_kpis(
    currency_id: int | None = Query(None, gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:summary")
    ),
):
    try:
        return warehouse_kpis(
            db=db,
            current_user=current_user,
            currency_id=currency_id,
        )
    except ReportingValidationError as exc:
        _raise_validation(str(exc))


@router.get(
    "/kpi/purchase_management",
    response_model=list[KpiRead],
)
def get_purchase_kpis(
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    currency_id: int | None = Query(None, gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("purchase_management:summary")
    ),
):
    try:
        return purchase_kpis(
            db=db,
            current_user=current_user,
            date_from=date_from,
            date_to=date_to,
            currency_id=currency_id,
        )
    except ReportingValidationError as exc:
        _raise_validation(str(exc))


@router.get(
    "/reports/warehouse_management/{name}",
    response_model=ReportRead,
)
def get_warehouse_report(
    name: str,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    group_by: str | None = Query(None),
    currency_id: int | None = Query(None, gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:summary")
    ),
):
    try:
        return warehouse_report(
            db=db,
            current_user=current_user,
            name=name,
            date_from=date_from,
            date_to=date_to,
            group_by=group_by,
            currency_id=currency_id,
        )
    except ReportingNotFoundError as exc:
        _raise_not_found(str(exc))
    except ReportingValidationError as exc:
        _raise_validation(str(exc))


@router.get(
    "/reports/purchase_management/{name}",
    response_model=ReportRead,
)
def get_purchase_report(
    name: str,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    group_by: str | None = Query(None),
    currency_id: int | None = Query(None, gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("purchase_management:summary")
    ),
):
    try:
        return purchase_report(
            db=db,
            current_user=current_user,
            name=name,
            date_from=date_from,
            date_to=date_to,
            group_by=group_by,
            currency_id=currency_id,
        )
    except ReportingNotFoundError as exc:
        _raise_not_found(str(exc))
    except ReportingValidationError as exc:
        _raise_validation(str(exc))
