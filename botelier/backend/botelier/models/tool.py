"""
Tool model for storing AI assistant function configurations.

Tools define what actions the AI can perform during conversations
(API calls, call transfers, sending messages, etc.)
"""

from sqlalchemy import Column, String, Text, JSON, DateTime, Integer, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
import uuid as uuid_pkg

from botelier.database import Base


class ToolType(str, enum.Enum):
    """Available tool types for AI assistants."""
    
    TRANSFER_CALL = "TRANSFER_CALL"
    API_REQUEST = "API_REQUEST"
    END_CALL = "END_CALL"
    SEND_SMS = "SEND_SMS"
    SEND_EMAIL = "SEND_EMAIL"
    FLOW = "FLOW"  # Conversation flow - guides structured multi-step interactions


class Tool(Base):
    """
    Tool configuration for AI assistant function calling.
    
    Each tool represents an action the AI can perform during a conversation.
    Configuration is stored as JSON to support flexible schemas per tool type.
    
    For FLOW type tools:
    - published_version_id: Points to the current live version (used by calls)
    - draft_version_id: Points to the work-in-progress version (for editing/testing)
    - published_version_number: Quick access to current version number
    
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
    # For non-FLOW tools, this stores the full config
    # For FLOW tools, this is kept for backwards compatibility but versions are preferred
    config = Column(JSON, nullable=False, default={})
    
    # Multi-tenancy - tools belong to a ToolSet collection
    tool_set_id = Column(UUID(as_uuid=True), ForeignKey("tool_sets.id"), nullable=True, index=True)
    account_id = Column(UUID(as_uuid=True), nullable=True, index=True)  # Orphan legacy column (no FK)
    assistant_id = Column(String(36), nullable=True, index=True)  # Legacy
    
    tool_set = relationship("ToolSet", back_populates="tools")
    
    # Flow versioning (only used for FLOW type tools)
    published_version_id = Column(UUID(as_uuid=True), nullable=True)
    draft_version_id = Column(UUID(as_uuid=True), nullable=True)
    published_version_number = Column(Integer, nullable=True, default=0)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Status
    is_active = Column(String(10), default="true")  # "true" or "false" as string
    
    def __repr__(self):
        return f"<Tool(id={self.id}, name={self.name}, type={self.tool_type})>"
    
    def to_dict(self):
        """Convert model to dictionary for API responses."""
        result = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tool_type": self.tool_type.value,
            "config": self.config,
            "tool_set_id": str(self.tool_set_id) if self.tool_set_id else None,
            "account_id": str(self.account_id) if self.account_id else None,
            "assistant_id": self.assistant_id,
            "is_active": self.is_active == "true",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        
        if self.tool_type == ToolType.FLOW:
            result["versioning"] = {
                "published_version_id": str(self.published_version_id) if self.published_version_id else None,
                "draft_version_id": str(self.draft_version_id) if self.draft_version_id else None,
                "published_version_number": self.published_version_number or 0,
                "has_draft": self.draft_version_id is not None,
            }
        
        return result
