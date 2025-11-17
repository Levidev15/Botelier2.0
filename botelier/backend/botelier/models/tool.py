"""
Tool model for storing AI assistant function configurations.

Tools define what actions the AI can perform during conversations
(API calls, call transfers, sending messages, etc.)
"""

from sqlalchemy import Column, String, Text, JSON, DateTime, Enum as SQLEnum
from sqlalchemy.sql import func
from datetime import datetime
import enum

from botelier.database import Base


class ToolType(str, enum.Enum):
    """Available tool types for AI assistants."""
    
    TRANSFER_CALL = "transfer_call"
    API_REQUEST = "api_request"
    END_CALL = "end_call"
    SEND_SMS = "send_sms"
    SEND_EMAIL = "send_email"


class Tool(Base):
    """
    Tool configuration for AI assistant function calling.
    
    Each tool represents an action the AI can perform during a conversation.
    Configuration is stored as JSON to support flexible schemas per tool type.
    
    Examples:
        Transfer Call Tool:
            {
                "phone_number": "+1-555-0123",
                "pre_transfer_message": "Let me connect you with our front desk..."
            }
        
        API Request Tool:
            {
                "url": "https://api.opera.com/rsv/v1/availability",
                "method": "GET",
                "headers": {"Authorization": "Bearer {{api_key}}"},
                "parameters": {
                    "check_in": "{{check_in_date}}",
                    "check_out": "{{check_out_date}}"
                }
            }
    """
    
    __tablename__ = "tools"
    
    # Primary key
    id = Column(String(36), primary_key=True, index=True)
    
    # Tool metadata
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=False)
    tool_type = Column(SQLEnum(ToolType), nullable=False, index=True)
    
    # Tool configuration (flexible JSON structure)
    config = Column(JSON, nullable=False, default={})
    
    # Multi-tenancy (future: associate with specific hotel/assistant)
    assistant_id = Column(String(36), nullable=True, index=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Status
    is_active = Column(String(10), default="true")  # "true" or "false" as string
    
    def __repr__(self):
        return f"<Tool(id={self.id}, name={self.name}, type={self.tool_type})>"
    
    def to_dict(self):
        """Convert model to dictionary for API responses."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tool_type": self.tool_type.value,
            "config": self.config,
            "assistant_id": self.assistant_id,
            "is_active": self.is_active == "true",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
