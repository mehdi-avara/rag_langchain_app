"""SQLAlchemy models for Currency and ExchangeRate."""
from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from db.base import Base


class ExchangeRateSource(str, enum.Enum):
    MANUAL = "manual"
    API = "api"


class Currency(Base):
    __tablename__ = "currencies"
    __table_args__ = (
        UniqueConstraint("code", name="uq_currencies_code"),
        Index("ix_currencies_code", "code"),
        Index("ix_currencies_is_active", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    # Uniqueness and indexing are declared explicitly in __table_args__
    # (uq_currencies_code / ix_currencies_code); avoid column-level
    # unique=/index= here, which would create a duplicate ix_currencies_code.
    code = Column(String(10), nullable=False)
    name = Column(String(100), nullable=False)
    symbol = Column(String(10), nullable=True)
    decimal_places = Column(Integer, nullable=False, default=2)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    from_rates = relationship(
        "ExchangeRate",
        foreign_keys="ExchangeRate.from_currency_id",
        back_populates="from_currency",
        cascade="all, delete-orphan",
    )
    to_rates = relationship(
        "ExchangeRate",
        foreign_keys="ExchangeRate.to_currency_id",
        back_populates="to_currency",
    )

    def __repr__(self) -> str:
        return f"<Currency {self.code}>"


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"
    __table_args__ = (
        Index("ix_exchange_rates_from_currency_id", "from_currency_id"),
        Index("ix_exchange_rates_to_currency_id", "to_currency_id"),
        Index("ix_exchange_rates_effective_date", "effective_date"),
    )

    id = Column(Integer, primary_key=True)
    from_currency_id = Column(Integer, ForeignKey("currencies.id", ondelete="CASCADE"), nullable=False)
    to_currency_id = Column(Integer, ForeignKey("currencies.id", ondelete="CASCADE"), nullable=False)
    # High-precision rate — 28 significant digits, 10 decimal places
    rate = Column(Numeric(28, 10), nullable=False)
    effective_date = Column(Date, nullable=False)
    source = Column(String(20), nullable=False, default=ExchangeRateSource.MANUAL.value)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    from_currency = relationship("Currency", foreign_keys=[from_currency_id], back_populates="from_rates")
    to_currency = relationship("Currency", foreign_keys=[to_currency_id], back_populates="to_rates")
    created_by = relationship("User", foreign_keys=[created_by_user_id])

    def __repr__(self) -> str:
        return f"<ExchangeRate {self.from_currency_id}→{self.to_currency_id} @ {self.effective_date}>"
