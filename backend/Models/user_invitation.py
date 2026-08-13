from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    and_,
)
from sqlalchemy.orm import relationship

from db.base import Base


user_invitation_role = Table(
    "user_invitation_role",
    Base.metadata,
    Column(
        "invitation_id",
        Integer,
        ForeignKey(
            "user_invitations.id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    ),
    Column(
        "role_id",
        Integer,
        ForeignKey(
            "roles.id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    ),
    Index(
        "ix_user_invitation_role_role_id",
        "role_id",
    ),
)


class UserInvitation(Base):
    __tablename__ = "user_invitations"

    id = Column(
        Integer,
        primary_key=True,
    )

    company_id = Column(
        Integer,
        ForeignKey(
            "companies.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    email = Column(
        String(255),
        nullable=False,
    )

    first_name = Column(
        String(100),
        nullable=False,
    )

    last_name = Column(
        String(100),
        nullable=True,
    )

    token_hash = Column(
        String(64),
        nullable=False,
        unique=True,
    )

    role_count = Column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )

    expires_at = Column(
        DateTime,
        nullable=False,
    )

    accepted_at = Column(
        DateTime,
        nullable=True,
    )

    revoked_at = Column(
        DateTime,
        nullable=True,
    )

    invited_by_user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    roles = relationship(
        "Role",
        secondary=user_invitation_role,
        lazy="selectin",
    )

    __table_args__ = (
        Index(
            "ix_user_invitations_company_created",
            "company_id",
            "created_at",
        ),
        Index(
            "ix_user_invitations_company_email",
            "company_id",
            "email",
        ),
        Index(
            "ix_user_invitations_expires_at",
            "expires_at",
        ),
        Index(
            "uq_user_invitations_open_company_email",
            "company_id",
            "email",
            unique=True,
            postgresql_where=and_(
                accepted_at.is_(None),
                revoked_at.is_(None),
            ),
        ),
        CheckConstraint(
            "role_count >= 1",
            name="role_count_positive",
        ),
        CheckConstraint(
            "NOT (accepted_at IS NOT NULL "
            "AND revoked_at IS NOT NULL)",
            name="terminal_state_exclusive",
        ),
    )
