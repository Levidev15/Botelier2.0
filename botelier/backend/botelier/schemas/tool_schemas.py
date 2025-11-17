"""
Pydantic schemas for Tool API validation.

These schemas validate request/response data for the Tools API.
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum


class ToolType(str, Enum):
    """Tool types available for creation."""
    
    transfer_call = "transfer_call"
    api_request = "api_request"
    end_call = "end_call"
    send_sms = "send_sms"
    send_email = "send_email"


# Configuration schemas for each tool type

class TransferCallConfig(BaseModel):
    """Configuration for call transfer tool."""
    
    phone_number: str = Field(..., description="Phone number to transfer to (E.164 format)")
    pre_transfer_message: Optional[str] = Field(
        "Let me connect you with someone who can help...",
        description="Message AI says before transferring"
    )
    
    @validator('phone_number')
    def validate_phone(cls, v):
        """Basic phone number validation."""
        # Remove common formatting
        cleaned = v.replace("+", "").replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
        if not cleaned.isdigit():
            raise ValueError("Phone number must contain only digits and formatting characters")
        return v


class ApiRequestConfig(BaseModel):
    """Configuration for API request tool."""
    
    url: str = Field(..., description="API endpoint URL")
    method: str = Field("GET", description="HTTP method (GET, POST, PUT, DELETE)")
    headers: Optional[Dict[str, str]] = Field(default={}, description="HTTP headers")
    parameters: Optional[Dict[str, Any]] = Field(default={}, description="Request parameters")
    body: Optional[Dict[str, Any]] = Field(default=None, description="Request body (for POST/PUT)")
    
    @validator('method')
    def validate_method(cls, v):
        """Validate HTTP method."""
        allowed = ["GET", "POST", "PUT", "DELETE", "PATCH"]
        if v.upper() not in allowed:
            raise ValueError(f"Method must be one of: {', '.join(allowed)}")
        return v.upper()


class EndCallConfig(BaseModel):
    """Configuration for end call tool."""
    
    goodbye_message: Optional[str] = Field(
        "Thank you for calling. Have a great day!",
        description="Message AI says before ending call"
    )


# Request schemas

class ToolCreate(BaseModel):
    """Schema for creating a new tool."""
    
    name: str = Field(..., min_length=1, max_length=255, description="Tool name (used by AI)")
    description: str = Field(..., min_length=1, description="What this tool does (helps AI decide when to use it)")
    tool_type: ToolType
    config: Dict[str, Any] = Field(..., description="Tool-specific configuration")
    assistant_id: Optional[str] = Field(None, description="Associated assistant ID")
    is_active: bool = Field(True, description="Whether tool is enabled")
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "transfer_to_front_desk",
                "description": "Transfer call to hotel front desk when guest needs human assistance",
                "tool_type": "transfer_call",
                "config": {
                    "phone_number": "+1-555-0123",
                    "pre_transfer_message": "Let me connect you with our front desk team..."
                },
                "is_active": True
            }
        }


class ToolUpdate(BaseModel):
    """Schema for updating an existing tool."""
    
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, min_length=1)
    config: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


# Response schemas

class ToolResponse(BaseModel):
    """Schema for tool API responses."""
    
    id: str
    name: str
    description: str
    tool_type: str
    config: Dict[str, Any]
    assistant_id: Optional[str]
    is_active: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True  # Allows creation from SQLAlchemy models


class ToolListResponse(BaseModel):
    """Schema for list of tools."""
    
    tools: list[ToolResponse]
    total: int
