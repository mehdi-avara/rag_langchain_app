from sqlalchemy import Column, Integer, String, ForeignKey, Table, Boolean, Index
from sqlalchemy.orm import relationship
from db.base import Base


role_permission = Table(
    "role_permission",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


user_role = Table(
    "user_role",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True)
    name = Column(String(50), nullable=False, index=True)
    description = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_system = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("uq_roles_system_name", "name", unique=True, postgresql_where=company_id.is_(None)),
        Index("uq_roles_company_name", "company_id", "name", unique=True, postgresql_where=company_id.is_not(None)),
    )

    permissions = relationship("Permission", secondary=role_permission, back_populates="roles", lazy="selectin")
    users = relationship("User", secondary=user_role, back_populates="roles", lazy="selectin")


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    resource = Column(String(50), nullable=False)
    action = Column(String(20), nullable=False)
    description = Column(String(200), nullable=True)

    roles = relationship("Role", secondary=role_permission, back_populates="permissions", lazy="selectin")