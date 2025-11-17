"""
PhoneNumber Model - Represents a Twilio phone number assigned to a hotel.

Each phone number is:
- Owned by a hotel's Twilio sub-account
- Optionally assigned to a voice assistant
- Used to receive incoming calls
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from botelier.database import Base


class PhoneNumber(Base):
    """
    PhoneNumber model for managing Twilio phone numbers.
    
    Flow:
    1. Hotel purchases number from their sub-account
    2. Number stored with Twilio SID
    3. Number assigned to voice assistant
    4. Incoming calls routed to that assistant
    """
    __tablename__ = "phone_numbers"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Phone number details
    phone_number = Column(String, unique=True, nullable=False)  # E.164 format: +14155551234
    friendly_name = Column(String, nullable=True)  # Optional label
    country_code = Column(String(2), nullable=False)  # US, GB, etc.
    
    # Twilio metadata
    twilio_sid = Column(String, unique=True, nullable=False)  # Twilio's phone number SID
    twilio_capabilities = Column(String, nullable=True)  # JSON: {"voice": true, "sms": true}
    
    # Ownership
    hotel_id = Column(UUID(as_uuid=True), ForeignKey("hotels.id"), nullable=False)
    
    # Assignment to voice assistant
    assistant_id = Column(UUID(as_uuid=True), nullable=True)  # Which assistant handles calls
    
    # Status
    is_active = Column(Boolean, default=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<PhoneNumber {self.phone_number}>"
    
    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "phone_number": self.phone_number,
            "friendly_name": self.friendly_name,
            "country_code": self.country_code,
            "twilio_sid": self.twilio_sid,
            "hotel_id": str(self.hotel_id),
            "assistant_id": str(self.assistant_id) if self.assistant_id else None,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "updated_at": self.updated_at.isoformat() + "Z" if self.updated_at else None,
        }
