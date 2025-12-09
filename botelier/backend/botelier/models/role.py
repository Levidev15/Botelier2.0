"""
Role and Permission Models - Flexible RBAC system for Botelier.

Supports:
- Default role templates (account_admin, staff)
- Granular feature-level permissions
- Per-user permission overrides
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from botelier.database import Base


class Role(Base):
    """
    Role template with default permissions.
    
    Roles can be:
    - System roles (account_admin, staff) - created by platform
    - Custom roles - created by account admins
    """
    __tablename__ = "roles"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=True)
    
    is_system_role = Column(Boolean, default=False)
    
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True)
    
    permissions = Column(JSON, default=dict)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)
    
    account = relationship("Account", back_populates="roles")
    memberships = relationship("AccountMembership", back_populates="role")
    
    def has_permission(self, permission: str) -> bool:
        """Check if role has a specific permission."""
        if not self.permissions:
            return False
        
        parts = permission.split(".")
        current = self.permissions
        
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return current is True
            
            if current is None:
                return False
        
        return current is True
    
    def __repr__(self):
        return f"<Role {self.name} (system={self.is_system_role})>"


class AccountMembership(Base):
    """
    Links users to accounts with specific roles.
    
    A user can be a member of multiple accounts with different roles.
    Supports individual permission overrides.
    """
    __tablename__ = "account_memberships"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False)
    
    permission_overrides = Column(JSON, default=dict)
    
    is_owner = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    
    invited_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    invited_at = Column(DateTime, nullable=True)
    accepted_at = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)
    
    user = relationship("User", back_populates="account_memberships", foreign_keys=[user_id])
    account = relationship("Account", back_populates="memberships")
    role = relationship("Role", back_populates="memberships")
    invited_by = relationship("User", foreign_keys=[invited_by_id])
    
    def has_permission(self, permission: str) -> bool:
        """
        Check if user has permission via role + overrides.
        
        Permission overrides take precedence over role permissions.
        """
        if self.permission_overrides:
            override = self._check_permission_in_dict(permission, self.permission_overrides)
            if override is not None:
                return override
        
        return self.role.has_permission(permission)
    
    def _check_permission_in_dict(self, permission: str, perms: dict):
        """Check permission in a nested dict, returns True/False/None."""
        parts = permission.split(".")
        current = perms
        
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, bool):
                return current
            else:
                return None
            
            if current is None:
                return None
        
        if isinstance(current, bool):
            return current
        return None
    
    def __repr__(self):
        return f"<AccountMembership user={self.user_id} account={self.account_id} role={self.role_id}>"
