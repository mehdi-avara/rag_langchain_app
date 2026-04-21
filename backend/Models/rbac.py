from sqlalchemy import Column, Integer, String, ForeignKey, Table, Boolean
from sqlalchemy.orm import relationship
from db.base import Base

role_permission = Table(
    'role_permission',
    Base.metadata,
    Column('role_id', Integer, ForeignKey('roles.id', ondelete='CASCADE')),
    Column('permission_id', Integer, ForeignKey('permissions.id', ondelete='CASCADE'))
)

user_role = Table(
    'user_role',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id', ondelete='CASCADE')),
    Column('role_id', Integer, ForeignKey('roles.id', ondelete='CASCADE'))
)


class Role(Base):
    __tablename__ = "roles"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)  
    description = Column(String(200))
    is_active = Column(Boolean, default=True)
    
    permissions = relationship("Permission", secondary=role_permission, back_populates="roles", lazy="selectin")
    users = relationship("User", secondary=user_role, back_populates="roles", lazy="selectin", overlaps="user_role,roles")


class Permission(Base):
    __tablename__ = "permissions"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)  
    resource = Column(String(50)) 
    action = Column(String(20)) 
    description = Column(String(200))
    
    roles = relationship("Role", secondary=role_permission, back_populates="permissions", lazy="selectin")