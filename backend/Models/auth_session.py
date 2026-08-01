from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import relationship

from db.base import Base


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(
        String(32),
        primary_key=True,
    )
    user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    company_id = Column(
        Integer,
        ForeignKey(
            "companies.id",
            ondelete="CASCADE",
        ),
        nullable=True,
        index=True,
    )
    token_version = Column(
        Integer,
        nullable=False,
    )
    refresh_jti_hash = Column(
        String(64),
        nullable=False,
        unique=True,
    )
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    last_rotated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    last_used_at = Column(
        DateTime,
        nullable=True,
    )
    expires_at = Column(
        DateTime,
        nullable=False,
        index=True,
    )
    revoked_at = Column(
        DateTime,
        nullable=True,
        index=True,
    )
    revoked_reason = Column(
        String(64),
        nullable=True,
    )

    user = relationship(
        "User",
        back_populates="auth_sessions",
    )
