"""
User Model - Represents users in the system with role-based access control.

Users are linked to Replit Auth (OIDC) and can have roles at platform or account level.
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


class User(Base):
    """
    User model representing authenticated users.
    
    Links to Replit Auth via the 'sub' claim (stable user ID).
    Platform admins can access all accounts.
    Account users belong to specific accounts with assigned roles.
    """
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    replit_id = Column(String, unique=True, nullable=False, index=True)
    
    email = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    profile_image_url = Column(String, nullable=True)
    
    user_type = Column(SQLEnum(UserType), default=UserType.ACCOUNT_USER, nullable=False)
    
    is_active = Column(Boolean, default=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)
    
    account_memberships = relationship("AccountMembership", back_populates="user", cascade="all, delete-orphan")
    
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
