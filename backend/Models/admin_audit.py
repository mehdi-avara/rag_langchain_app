from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB

from db.base import Base


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"
    __table_args__ = (
        Index(
            "ix_admin_audit_company_created",
            "company_id",
            "created_at",
        ),
        Index(
            "ix_admin_audit_actor_created",
            "actor_user_id",
            "created_at",
        ),
        Index(
            "ix_admin_audit_action",
            "action",
        ),
        Index(
            "ix_admin_audit_target",
            "target_type",
            "target_id",
        ),
    )

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
    actor_user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    action = Column(
        String(80),
        nullable=False,
    )
    target_type = Column(
        String(40),
        nullable=False,
    )
    target_id = Column(
        String(64),
        nullable=False,
    )
    details_json = Column(
        JSONB,
        nullable=False,
        default=dict,
    )
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )


def _prevent_admin_audit_mutation(
    *_args,
    **_kwargs,
):
    raise ValueError(
        "Admin audit logs are append-only"
    )


event.listen(
    AdminAuditLog,
    "before_update",
    _prevent_admin_audit_mutation,
)

event.listen(
    AdminAuditLog,
    "before_delete",
    _prevent_admin_audit_mutation,
)
