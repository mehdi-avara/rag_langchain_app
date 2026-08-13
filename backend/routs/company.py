from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from core.admin_audit import append_admin_audit
from Models import Company, User
from financial_management.models import FinancialReceipt
from schemas.company import CompanySettingsOut, CompanySettingsUpdate

router = APIRouter()


def _get_current_company(db: Session, current_user: User) -> Company:
    if current_user.company_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has no company")

    company = db.query(Company).filter(Company.id == current_user.company_id).first()

    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    return company


@router.get("/settings", response_model=CompanySettingsOut)
def get_company_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("company:read")),
):
    company = _get_current_company(db, current_user)
    return company


@router.patch("/settings", response_model=CompanySettingsOut)
def update_company_settings(
    payload: CompanySettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("company:update")),
):
    company = _get_current_company(db, current_user)
    data = payload.model_dump(exclude_unset=True)

    before_state = {
        "name": company.name,
        "base_currency": company.base_currency,
        "allow_self_approval": (
            company.allow_self_approval
        ),
    }

    if "name" in data and data["name"] is not None:
        company.name = data["name"].strip()

    if "base_currency" in data and data["base_currency"] is not None:
        new_base_currency = data["base_currency"].value

        if new_base_currency != company.base_currency:
            receipt_exists = (
                db.query(FinancialReceipt.id)
                .filter(FinancialReceipt.company_id == company.id)
                .first()
                is not None
            )

            if receipt_exists:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot change company base_currency after financial receipts have been created",
                )

            company.base_currency = new_base_currency

    if "allow_self_approval" in data and data["allow_self_approval"] is not None:
        company.allow_self_approval = bool(data["allow_self_approval"])

    after_state = {
        "name": company.name,
        "base_currency": company.base_currency,
        "allow_self_approval": (
            company.allow_self_approval
        ),
    }

    if before_state != after_state:
        append_admin_audit(
            db,
            company_id=company.id,
            actor_user_id=current_user.id,
            action="company.settings_updated",
            target_type="company",
            target_id=company.id,
            details={
                "before": before_state,
                "after": after_state,
            },
        )

    db.commit()
    db.refresh(company)

    return company
