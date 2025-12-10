"""
User Model - Represents users in the system with role-based access control.

Users can authenticate via email/password or OAuth (Replit, etc.).
Platform admins can access all accounts.
Account users belong to specific accounts with assigned roles.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Text, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from botelier.database import Base


class UserType(str, enum.Enum):
    """Type of user in the system."""
    PLATFORM_ADMIN = "platform_admin"
    ACCOUNT_USER = "account_user"


class AuthProvider(str, enum.Enum):
    """Authentication provider used by the user."""
    EMAIL = "email"
    REPLIT = "replit"


class User(Base):
    """
    User model representing authenticated users.
    
    Supports both email/password and OAuth authentication.
    Platform admins can access all accounts.
    Account users belong to specific accounts with assigned roles.
    """
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    replit_id = Column(String, unique=True, nullable=True, index=True)
    
    email = Column(String, unique=True, nullable=False, index=True)
    email_verified = Column(Boolean, default=False)
    password_hash = Column(String, nullable=True)
    
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    profile_image_url = Column(String, nullable=True)
    
    auth_provider = Column(SQLEnum(AuthProvider), default=AuthProvider.EMAIL, nullable=False)
    
    user_type = Column(SQLEnum(UserType), default=UserType.ACCOUNT_USER, nullable=False)
    
    is_active = Column(Boolean, default=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)
    
    account_memberships = relationship(
        "AccountMembership", 
        back_populates="user", 
        cascade="all, delete-orphan",
        foreign_keys="[AccountMembership.user_id]"
    )
    
    @property
    def is_platform_admin(self) -> bool:
        """Check if user is a platform admin."""
        return self.user_type == UserType.PLATFORM_ADMIN
    
    @property
    def display_name(self) -> str:
        """Get display name for the user."""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        elif self.first_name:
            return self.first_name
        elif self.email:
            return self.email.split("@")[0]
        return f"User {str(self.id)[:8]}"
    
    def __repr__(self):
        return f"<User {self.display_name} ({self.user_type.value})>"


class SupportSession(Base):
    """
    Support session for platform admins accessing tenant accounts.
    
    Provides SaaS-compliant account access with:
    - Time-limited access (1 hour by default)
    - Audit trail of access reason
    - Trackable session token
    """
    __tablename__ = "support_sessions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_token = Column(String, unique=True, nullable=False, index=True)
    
    admin_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    account_id = Column(UUID(as_uuid=True), nullable=False)
    
    reason = Column(Text, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    
    is_active = Column(Boolean, default=True)
    
    admin = relationship("User", foreign_keys=[admin_id])
    
    @property
    def is_valid(self) -> bool:
        """Check if session is still valid."""
        if not self.is_active:
            return False
        if self.revoked_at:
            return False
        if datetime.utcnow() > self.expires_at:
            return False
        return True
    
    def __repr__(self):
        return f"<SupportSession admin={self.admin_id} account={self.account_id}>"
