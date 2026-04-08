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
    
    transfer_call = "TRANSFER_CALL"
    api_request = "API_REQUEST"
    end_call = "END_CALL"
    send_sms = "SEND_SMS"
    send_email = "SEND_EMAIL"
    flow = "FLOW"  # Conversation flow for structured multi-step interactions


# Configuration schemas for each tool type

class TransferCallConfig(BaseModel):
    """Configuration for call transfer tool."""
    
    phone_number: str = Field(..., description="Phone number to transfer to (E.164 format)")
    pre_transfer_message: Optional[str] = Field(
        "Let me connect you with someone who can help...",
        description="Message AI says before transferring"
    )
    transfer_mode: str = Field(
        "warm",
        description="'warm' keeps Twilio bridging both legs (trackable, ongoing charges). 'cold' uses SIP REFER — Twilio exits after handoff, no ongoing charges, no second-leg tracking."
    )
    
    @validator('phone_number')
    def validate_phone(cls, v):
        """Basic phone number validation."""
        cleaned = v.replace("+", "").replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
        if not cleaned.isdigit():
            raise ValueError("Phone number must contain only digits and formatting characters")
        return v
    
    @validator('transfer_mode')
    def validate_transfer_mode(cls, v):
        """Validate transfer mode."""
        if v not in ("warm", "cold"):
            raise ValueError("transfer_mode must be 'warm' or 'cold'")
        return v


class ApiRequestConfig(BaseModel):
    """Configuration for API request tool."""
    
    url: str = Field(..., description="API endpoint URL")
    method: str = Field("GET", description="HTTP method (GET, POST, PUT, DELETE)")
    headers: Optional[Dict[str, str]] = Field(default={}, description="HTTP headers")
    parameters: Optional[Dict[str, Any]] = Field(default={}, description="Request parameters")
    body: Optional[Dict[str, Any]] = Field(default=None, description="Request body (for POST/PUT)")
    body_template: Optional[str] = Field(default=None, description="Request body as template string with {{variable}} placeholders")
    response_mapping: Optional[Dict[str, str]] = Field(default=None, description="Map response JSON paths to variable names, e.g. {'guest_name': 'data.guest.name'}")
    response_instructions: Optional[str] = Field(default=None, description="Instructions telling the AI how to format/present the API response to the caller")
    timeout: Optional[int] = Field(default=30, description="Request timeout in seconds")
    
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


class FlowConfig(BaseModel):
    """Configuration for flow tool - stores the visual flow editor data."""
    
    initial_node: Optional[str] = Field(None, description="ID of the starting node")
    nodes: list[Dict[str, Any]] = Field(default=[], description="Flow nodes with positions and data")
    edges: list[Dict[str, Any]] = Field(default=[], description="Connections between nodes")


# Request schemas

class ToolCreate(BaseModel):
    """Schema for creating a new tool."""
    
    name: str = Field(..., min_length=1, max_length=255, description="Tool name (used by AI)")
    description: str = Field(..., min_length=1, description="What this tool does (helps AI decide when to use it)")
    tool_type: ToolType
    config: Dict[str, Any] = Field(..., description="Tool-specific configuration")
    tool_set_id: Optional[str] = Field(None, description="Tool set ID")
    account_id: Optional[str] = Field(None, description="Account UUID")
    assistant_id: Optional[str] = Field(None, description="Associated assistant ID")
    is_active: bool = Field(True, description="Whether tool is enabled")


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
    tool_set_id: Optional[str] = None
    account_id: Optional[str] = None
    assistant_id: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class ToolListResponse(BaseModel):
    """Schema for list of tools."""
    
    tools: list[ToolResponse]
    total: int
