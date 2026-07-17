from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship

from db.base import Base


class OrganizationDepartment(Base):
    __tablename__ = "organization_departments"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "code",
            name="uq_organization_departments_company_code",
        ),
        UniqueConstraint(
            "company_id",
            "name",
            name="uq_organization_departments_company_name",
        ),
        CheckConstraint(
            "parent_department_id IS NULL OR parent_department_id <> id",
            name="not_self_parent",
        ),
        Index(
            "ix_organization_departments_company_id",
            "company_id",
        ),
        Index(
            "ix_organization_departments_parent_department_id",
            "parent_department_id",
        ),
        Index(
            "ix_organization_departments_manager_user_id",
            "manager_user_id",
        ),
        Index(
            "ix_organization_departments_is_active",
            "is_active",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(
        Integer,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_department_id = Column(
        Integer,
        ForeignKey(
            "organization_departments.id",
            name="fk_org_departments_parent",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    manager_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    code = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
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

    company = relationship("Company")
    parent = relationship(
        "OrganizationDepartment",
        remote_side=[id],
        back_populates="children",
        foreign_keys=[parent_department_id],
    )
    children = relationship(
        "OrganizationDepartment",
        back_populates="parent",
        foreign_keys=[parent_department_id],
    )
    manager = relationship(
        "User",
        foreign_keys=[manager_user_id],
    )
    positions = relationship(
        "OrganizationPosition",
        back_populates="department",
    )
    assignments = relationship(
        "OrganizationUserAssignment",
        back_populates="department",
    )


class OrganizationPosition(Base):
    __tablename__ = "organization_positions"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "code",
            name="uq_organization_positions_company_code",
        ),
        Index(
            "ix_organization_positions_company_id",
            "company_id",
        ),
        Index(
            "ix_organization_positions_department_id",
            "department_id",
        ),
        Index(
            "ix_organization_positions_is_active",
            "is_active",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(
        Integer,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    department_id = Column(
        Integer,
        ForeignKey(
            "organization_departments.id",
            name="fk_org_positions_department",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    code = Column(String(50), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    is_manager = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
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

    company = relationship("Company")
    department = relationship(
        "OrganizationDepartment",
        back_populates="positions",
    )
    assignments = relationship(
        "OrganizationUserAssignment",
        back_populates="position",
    )


class OrganizationUserAssignment(Base):
    __tablename__ = "organization_user_assignments"
    __table_args__ = (
        CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name="valid_dates",
        ),
        Index(
            "ix_organization_user_assignments_company_id",
            "company_id",
        ),
        Index(
            "ix_organization_user_assignments_user_id",
            "user_id",
        ),
        Index(
            "ix_organization_user_assignments_department_id",
            "department_id",
        ),
        Index(
            "ix_organization_user_assignments_position_id",
            "position_id",
        ),
        Index(
            "ix_organization_user_assignments_is_active",
            "is_active",
        ),
        Index(
            "uq_organization_assignments_active_primary_user",
            "company_id",
            "user_id",
            unique=True,
            postgresql_where=text(
                "is_primary IS TRUE AND is_active IS TRUE"
            ),
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(
        Integer,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    department_id = Column(
        Integer,
        ForeignKey(
            "organization_departments.id",
            name="fk_org_assignments_department",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    position_id = Column(
        Integer,
        ForeignKey(
            "organization_positions.id",
            name="fk_org_assignments_position",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    is_primary = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    start_date = Column(Date, nullable=True, default=date.today)
    end_date = Column(Date, nullable=True)
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

    company = relationship("Company")
    user = relationship(
        "User",
        foreign_keys=[user_id],
    )
    department = relationship(
        "OrganizationDepartment",
        back_populates="assignments",
    )
    position = relationship(
        "OrganizationPosition",
        back_populates="assignments",
    )
