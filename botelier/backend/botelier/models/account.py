"""
Account Model - Represents a client organization in the multi-tenant system.

Renamed from "Hotel" to support various business types (hotels, resorts, hospitals, etc.)
Each account gets its own Twilio sub-account for isolation and billing.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Text, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
import enum

from botelier.database import Base


class AccountStatus(str, enum.Enum):
    """Account status in the system."""
    TRIAL = "trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"


class SubscriptionTier(str, enum.Enum):
    """Subscription tier for billing."""
    FREE = "free"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class Account(Base):
    """
    Account model representing a client organization.
    
    Each account is a separate tenant with:
    - Own Twilio sub-account for phone numbers
    - Own voice assistants and configurations
    - Isolated billing and usage tracking
    - Team members with role-based access
    """
    __tablename__ = "accounts"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False, index=True)
    
    business_type = Column(String, nullable=True)
    
    email = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    website = Column(String, nullable=True)
    
    address_line1 = Column(String, nullable=True)
    address_line2 = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    postal_code = Column(String, nullable=True)
    country = Column(String, nullable=True)
    
    twilio_sub_account_sid = Column(String, nullable=True)
    twilio_sub_auth_token = Column(String, nullable=True)
    
    status = Column(SQLEnum(AccountStatus), default=AccountStatus.TRIAL, nullable=False)
    subscription_tier = Column(SQLEnum(SubscriptionTier), default=SubscriptionTier.FREE, nullable=False)
    
    trial_ends_at = Column(DateTime, nullable=True)
    
    settings = Column(Text, nullable=True)

    feature_flags = Column(JSONB, nullable=False, server_default='{}')

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)
    
    memberships = relationship("AccountMembership", back_populates="account", cascade="all, delete-orphan")
    roles = relationship("Role", back_populates="account", cascade="all, delete-orphan")
    
    @property
    def is_active(self) -> bool:
        """Check if account is active (active or trial status)."""
        return self.status in [AccountStatus.ACTIVE, AccountStatus.TRIAL]
    
    @property
    def has_twilio(self) -> bool:
        """Check if account has Twilio configured."""
        return bool(self.twilio_sub_account_sid and self.twilio_sub_auth_token)
    
    def __repr__(self):
        return f"<Account {self.name} ({self.slug}) status={self.status.value}>"
