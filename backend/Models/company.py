from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from db.base import Base


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False)
    slug = Column(String(120), nullable=False, unique=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    # When True, a user may approve/review a requisition they themselves created
    # (segregation of duties is relaxed — convenient for single-user/small companies).
    # Defaults to True so companies allow self-approval out of the box; a company
    # admin can disable it (to enforce two-person approval) via
    # PATCH /company/settings ("company:update").
    allow_self_approval = Column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    base_currency = Column(String(12), nullable=False, default="IRT")
    base_currency_id = Column(
        Integer,
        ForeignKey("currencies.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    users = relationship("User", back_populates="company")


