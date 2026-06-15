"""phase_0.3 — currency foundation (currencies + exchange_rates + company.base_currency_id)

Revision ID: a1_phase_0_3_currency
Revises: f6a1c9e2d4b7
Create Date: 2026-06-15 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision: str = "a1_phase_0_3_currency"
down_revision: Union[str, None] = "f6a1c9e2d4b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. currencies table ────────────────────────────────────────────────────
    op.create_table(
        "currencies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(10), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("symbol", sa.String(10), nullable=True),
        sa.Column("decimal_places", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_currencies_code", "currencies", ["code"])
    op.create_index("ix_currencies_is_active", "currencies", ["is_active"])

    # ── 2. exchange_rates table ────────────────────────────────────────────────
    op.create_table(
        "exchange_rates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("from_currency_id", sa.Integer(), sa.ForeignKey("currencies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("to_currency_id",   sa.Integer(), sa.ForeignKey("currencies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rate", sa.Numeric(28, 10), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_exchange_rates_from_currency_id", "exchange_rates", ["from_currency_id"])
    op.create_index("ix_exchange_rates_to_currency_id",   "exchange_rates", ["to_currency_id"])
    op.create_index("ix_exchange_rates_effective_date",    "exchange_rates", ["effective_date"])

    # ── 3. Add base_currency_id to companies (nullable — backward compatible) ──
    op.add_column(
        "companies",
        sa.Column("base_currency_id", sa.Integer(), sa.ForeignKey("currencies.id", ondelete="SET NULL"), nullable=True),
    )

    # ── 4. Seed standard currencies ────────────────────────────────────────────
    op.execute("""
        INSERT INTO currencies (code, name, symbol, decimal_places, is_active) VALUES
            ('IRT', 'Iranian Toman',    '﷼',  0, true),
            ('IRR', 'Iranian Rial',     '﷼',  0, true),
            ('USD', 'US Dollar',        '$',   2, true),
            ('AED', 'UAE Dirham',       'د.إ', 2, true),
            ('IQD', 'Iraqi Dinar',      'ع.د', 0, true),
            ('CNY', 'Chinese Yuan',     '¥',   2, true),
            ('EUR', 'Euro',             '€',   2, true),
            ('GBP', 'British Pound',    '£',   2, true),
            ('TRY', 'Turkish Lira',     '₺',   2, true)
        ON CONFLICT (code) DO NOTHING
    """)

    # ── 5. Seed RBAC permissions for currency module ───────────────────────────
    from sqlalchemy.orm import Session
    from db.seed_rbac import get_or_create_permission
    from shared.currency.permissions import PERMISSIONS

    bind = op.get_bind()
    session = Session(bind=bind)
    for name, resource, action, description in PERMISSIONS:
        get_or_create_permission(session, name, resource, action, description)
    session.commit()


def downgrade() -> None:
    op.drop_column("companies", "base_currency_id")
    op.drop_index("ix_exchange_rates_effective_date", table_name="exchange_rates")
    op.drop_index("ix_exchange_rates_to_currency_id",   table_name="exchange_rates")
    op.drop_index("ix_exchange_rates_from_currency_id", table_name="exchange_rates")
    op.drop_table("exchange_rates")
    op.drop_index("ix_currencies_is_active", table_name="currencies")
    op.drop_index("ix_currencies_code", table_name="currencies")
    op.drop_table("currencies")
