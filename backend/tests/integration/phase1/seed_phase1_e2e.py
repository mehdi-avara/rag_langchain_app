from __future__ import annotations

import os

from db.provision_company_defaults import (
    provision_company_defaults,
)
from db.session import SessionLocal
from Models import (
    Company,
    Currency,
    FinancialCard,
    Item,
    ItemCategory,
    Supplier,
    Unit,
    User,
)
from settings import get_settings


EXPECTED_DATABASE = "rag_phase1_integration_ci"
SEED_ITEM_CODE = "CI-PHASE1-TEMPLATE"
SEED_CARD_NUMBER = "CI-PHASE1-0001"
SEED_SUPPLIER_CODE = "CI-PHASE1-SUPPLIER"


def main() -> None:
    settings = get_settings()

    if os.getenv("PORSA_PHASE1_E2E_SEED_ALLOW") != "1":
        raise RuntimeError(
            "Phase 1 E2E seed requires "
            "PORSA_PHASE1_E2E_SEED_ALLOW=1"
        )

    if settings.POSTGRES_DB != EXPECTED_DATABASE:
        raise RuntimeError(
            "Refusing Phase 1 E2E seed outside disposable CI DB: "
            f"{settings.POSTGRES_DB!r}"
        )

    db = SessionLocal()

    try:
        company = (
            db.query(Company)
            .filter(
                Company.slug
                == settings.DEFAULT_COMPANY_SLUG
            )
            .one()
        )

        user = (
            db.query(User)
            .filter(
                User.username
                == settings.default_username
            )
            .one()
        )

        if user.company_id != company.id:
            raise RuntimeError(
                "CI bootstrap user/company mismatch"
            )

        company.is_active = True
        company.allow_self_approval = True

        provision_company_defaults(
            db,
            company,
            created_by_user_id=user.id,
        )

        db.flush()

        aed = (
            db.query(Currency)
            .filter(Currency.code == "AED")
            .first()
        )

        if aed is None:
            aed = Currency(
                code="AED",
                name="UAE Dirham",
                symbol="AED",
                decimal_places=2,
                is_active=True,
            )
            db.add(aed)
        else:
            aed.name = "UAE Dirham"
            aed.symbol = "AED"
            aed.decimal_places = 2
            aed.is_active = True

        category = (
            db.query(ItemCategory)
            .filter(
                ItemCategory.company_id == company.id,
                ItemCategory.code == "GENERAL",
            )
            .one()
        )

        unit = (
            db.query(Unit)
            .filter(
                Unit.company_id == company.id,
                Unit.code == "EA",
            )
            .one()
        )

        item = (
            db.query(Item)
            .filter(
                Item.company_id == company.id,
                Item.item_code == SEED_ITEM_CODE,
            )
            .first()
        )

        if item is None:
            item = Item(
                company_id=company.id,
                item_code=SEED_ITEM_CODE,
                name="CI Phase 1 Template Item",
                description=(
                    "Disposable Phase 1 integration seed"
                ),
                category_id=category.id,
                unit_id=unit.id,
                specs={},
                item_type="material",
                is_active=True,
                is_critical=False,
                created_by_user_id=user.id,
            )
            db.add(item)
        else:
            item.category_id = category.id
            item.unit_id = unit.id
            item.is_active = True

        card = (
            db.query(FinancialCard)
            .filter(
                FinancialCard.company_id == company.id,
                FinancialCard.card_number
                == SEED_CARD_NUMBER,
            )
            .first()
        )

        if card is None:
            card = FinancialCard(
                company_id=company.id,
                owner_id=user.id,
                title="CI Phase 1 Card",
                card_number=SEED_CARD_NUMBER,
                bank_name="CI Test Bank",
                account_owner_name=user.First_name,
                description=(
                    "Disposable Phase 1 integration seed"
                ),
                is_active=True,
            )
            db.add(card)
        else:
            card.owner_id = user.id
            card.is_active = True

        supplier = (
            db.query(Supplier)
            .filter(
                Supplier.company_id == company.id,
                Supplier.code == SEED_SUPPLIER_CODE,
            )
            .first()
        )

        if supplier is None:
            supplier = Supplier(
                company_id=company.id,
                code=SEED_SUPPLIER_CODE,
                name="CI Phase 1 Supplier",
                supplier_type="local",
                status="approved",
                notes=(
                    "Disposable Phase 1 integration seed"
                ),
                created_by_user_id=user.id,
            )
            db.add(supplier)
        else:
            supplier.status = "approved"

        db.commit()

        print(
            "Phase 1 E2E seed ready:",
            f"company={company.id}",
            f"user={user.id}",
            f"currency=AED",
            f"item={SEED_ITEM_CODE}",
            f"card={SEED_CARD_NUMBER}",
            f"supplier={SEED_SUPPLIER_CODE}",
        )

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    main()
