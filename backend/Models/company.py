from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

from db.base import Base


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False)
    slug = Column(String(120), nullable=False, unique=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    base_currency = Column(String(12), nullable=False, default="IRT")
    # Legacy column retained for schema parity with existing deployments.
    # Plain integer (no FK) per the codebase's module-isolation pattern; the
    # active base-currency value lives in the `base_currency` string column.
    base_currency_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    users = relationship("User", back_populates="company")


