"""
Hotel Model - Represents a hotel client in the multi-tenant system.

Each hotel gets its own Twilio sub-account for isolation and billing.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean
from sqlalchemy.dialects.postgresql import UUID
from botelier.database import Base


class Hotel(Base):
    """
    Hotel model representing a client organization.
    
    Each hotel is a separate tenant with:
    - Own Twilio sub-account for phone numbers
    - Own voice assistants and configurations
    - Isolated billing and usage tracking
    """
    __tablename__ = "hotels"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Hotel information
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False)  # URL-friendly identifier
    
    # Contact details
    email = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    
    # Twilio sub-account credentials
    twilio_sub_account_sid = Column(String, nullable=True)  # Created automatically
    twilio_sub_auth_token = Column(String, nullable=True)   # Encrypted in production
    
    # Status
    is_active = Column(Boolean, default=True)
    subscription_tier = Column(String, default="trial")  # trial, basic, pro, enterprise
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<Hotel {self.name} ({self.slug})>"
