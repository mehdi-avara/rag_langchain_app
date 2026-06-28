"""Per-company "starter defaults" provisioning.

A new company starts with several hard prerequisites before it can do basic
work: an :class:`Item` needs a category **and** a unit, every money-bearing row
needs a :class:`Currency`, and any stock needs a Warehouse -> Zone ->
StorageLocation chain. Forcing a starter to create all of that by hand before
they can record a single item or receive any goods is needless friction.

This module seeds **sensible, idempotent defaults** so a starter can act
immediately while the full hierarchy stays available for companies that
outgrow it:

* global currencies (at least the company base currency),
* a "General" item category,
* a standard unit set (Each, Kilogram, Liter, Meter, m^2),
* a default "Main Warehouse" -> "General" zone -> "Default" receiving location.

Design notes
------------
* **Schema is owned by Alembic.** This module only writes *data*; it never
  issues DDL.
* **Idempotent.** Every create is a get-or-create keyed on the relevant unique
  constraint, so it is safe to run on registration, at startup, and as a
  backfill across all existing companies (any number of times).
* **App-level seeder, not a domain module.** Like ``db/init_db.py`` and
  ``db/seed_rbac.py`` it composes across modules, so importing several modules'
  models here is intentional and does not break the per-module import rule.
"""
from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy.orm import Session

from db.session import SessionLocal
from Models import (
    Company,
    Currency,
    ItemCategory,
    StorageLocation,
    Unit,
    Warehouse,
    Zone,
)
from material_management.models import UnitType
from warehouse_management.models import WarehouseType

# --- Default catalogues -----------------------------------------------------

# (code, name, symbol, decimal_places). IRT (Iranian Toman) is the company base
# default and is whole-number, so it carries 0 decimal places.
DEFAULT_CURRENCIES: tuple[tuple[str, str, Optional[str], int], ...] = (
    ("IRT", "Iranian Toman", "تومان", 0),
    ("USD", "US Dollar", "$", 2),
    ("EUR", "Euro", "€", 2),
)

DEFAULT_CATEGORY_CODE = "GENERAL"
DEFAULT_CATEGORY_NAME = "General"

# (code, name, unit_type)
DEFAULT_UNITS: tuple[tuple[str, str, str], ...] = (
    ("EA", "Each", UnitType.COUNT.value),
    ("KG", "Kilogram", UnitType.MASS.value),
    ("L", "Liter", UnitType.VOLUME.value),
    ("M", "Meter", UnitType.LENGTH.value),
    ("M2", "Square Meter", UnitType.AREA.value),
)

DEFAULT_WAREHOUSE_CODE = "MAIN"
DEFAULT_WAREHOUSE_NAME = "Main Warehouse"
DEFAULT_ZONE_CODE = "GENERAL"
DEFAULT_ZONE_NAME = "General"
DEFAULT_LOCATION_CODE = "DEFAULT"
DEFAULT_LOCATION_NAME = "Default"


# --- Building blocks --------------------------------------------------------

def ensure_currencies(db: Session) -> dict[str, Currency]:
    """Get-or-create the global currency rows. Returns a {code: Currency} map.

    Currencies are platform-global (no ``company_id``); the unique key is
    ``currencies.code``.
    """
    by_code: dict[str, Currency] = {}
    for code, name, symbol, decimals in DEFAULT_CURRENCIES:
        currency = db.query(Currency).filter(Currency.code == code).first()
        if currency is None:
            currency = Currency(
                code=code,
                name=name,
                symbol=symbol,
                decimal_places=decimals,
                is_active=True,
            )
            db.add(currency)
            db.flush()
        by_code[code] = currency
    return by_code


def _ensure_base_currency(db: Session, company: Company, currencies: dict[str, Currency]) -> None:
    """Link ``company.base_currency_id`` to the row matching its base code."""
    if company.base_currency_id is not None:
        return
    code = (company.base_currency or "IRT").upper()
    currency = currencies.get(code) or db.query(Currency).filter(Currency.code == code).first()
    if currency is not None:
        company.base_currency_id = currency.id


def _ensure_default_category(db: Session, company_id: int, created_by_user_id: Optional[int]) -> None:
    exists = (
        db.query(ItemCategory)
        .filter(
            ItemCategory.company_id == company_id,
            ItemCategory.code == DEFAULT_CATEGORY_CODE,
        )
        .first()
    )
    if exists is None:
        db.add(
            ItemCategory(
                company_id=company_id,
                code=DEFAULT_CATEGORY_CODE,
                name=DEFAULT_CATEGORY_NAME,
                created_by_user_id=created_by_user_id,
            )
        )


def _ensure_default_units(db: Session, company_id: int, created_by_user_id: Optional[int]) -> None:
    existing_codes = {
        code
        for (code,) in db.query(Unit.code).filter(Unit.company_id == company_id).all()
    }
    for code, name, unit_type in DEFAULT_UNITS:
        if code in existing_codes:
            continue
        db.add(
            Unit(
                company_id=company_id,
                code=code,
                name=name,
                unit_type=unit_type,
                created_by_user_id=created_by_user_id,
            )
        )


def _ensure_default_warehouse_chain(db: Session, company_id: int) -> None:
    """Ensure the company has a default warehouse with a usable location.

    Respects the one-default-warehouse-per-company partial unique index: if the
    company already has a default warehouse we reuse it; otherwise we create
    "MAIN" as the default. We only add the General zone + Default location when
    the resolved default warehouse has no zones yet, so companies that already
    built their own structure are left untouched.
    """
    default_wh = (
        db.query(Warehouse)
        .filter(Warehouse.company_id == company_id, Warehouse.is_default.is_(True))
        .first()
    )
    if default_wh is None:
        # Reuse a MAIN-coded warehouse if one exists but wasn't flagged default.
        default_wh = (
            db.query(Warehouse)
            .filter(
                Warehouse.company_id == company_id,
                Warehouse.code == DEFAULT_WAREHOUSE_CODE,
            )
            .first()
        )
        if default_wh is None:
            default_wh = Warehouse(
                company_id=company_id,
                code=DEFAULT_WAREHOUSE_CODE,
                name=DEFAULT_WAREHOUSE_NAME,
                warehouse_type=WarehouseType.MAIN.value,
                is_default=True,
                is_active=True,
            )
            db.add(default_wh)
            db.flush()
        else:
            default_wh.is_default = True
            db.flush()

    has_zone = (
        db.query(Zone)
        .filter(Zone.warehouse_id == default_wh.id)
        .first()
        is not None
    )
    if has_zone:
        return

    zone = Zone(
        warehouse_id=default_wh.id,
        code=DEFAULT_ZONE_CODE,
        name=DEFAULT_ZONE_NAME,
    )
    db.add(zone)
    db.flush()

    db.add(
        StorageLocation(
            zone_id=zone.id,
            code=DEFAULT_LOCATION_CODE,
            name=DEFAULT_LOCATION_NAME,
            is_active=True,
            is_receiving=True,
        )
    )


# --- Public API -------------------------------------------------------------

def provision_company_defaults(
    db: Session,
    company: Company,
    *,
    created_by_user_id: Optional[int] = None,
    currencies: Optional[dict[str, Currency]] = None,
) -> None:
    """Idempotently provision starter defaults for a single company.

    Does **not** commit — the caller owns the transaction so this can compose
    with registration. Pass ``currencies`` to reuse an already-loaded map when
    provisioning many companies in a loop.
    """
    if currencies is None:
        currencies = ensure_currencies(db)
    _ensure_base_currency(db, company, currencies)
    _ensure_default_category(db, company.id, created_by_user_id)
    _ensure_default_units(db, company.id, created_by_user_id)
    _ensure_default_warehouse_chain(db, company.id)


def provision_all_companies(companies: Optional[Iterable[Company]] = None) -> int:
    """Backfill starter defaults for every company. Idempotent; commits once.

    Returns the number of companies processed. Intended to be run as a one-time
    (and repeatable) backfill, e.g. from ``entrypoint.sh`` on deploy.
    """
    db = SessionLocal()
    try:
        currencies = ensure_currencies(db)
        rows = list(companies) if companies is not None else db.query(Company).all()
        for company in rows:
            provision_company_defaults(db, company, currencies=currencies)
        db.commit()
        return len(rows)
    finally:
        db.close()


if __name__ == "__main__":
    count = provision_all_companies()
    print(f"Provisioned starter defaults for {count} companies.")
