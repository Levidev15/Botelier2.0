"""
Tools API endpoints.

Provides CRUD operations for managing AI assistant tools/functions.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import uuid

from botelier.database import get_db
from botelier.models.tool import Tool, ToolType as DBToolType
from botelier.schemas.tool_schemas import (
    ToolCreate,
    ToolUpdate,
    ToolResponse,
    ToolListResponse,
    ToolType
)

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("", response_model=ToolListResponse)
def list_tools(
    assistant_id: str = None,
    tool_type: str = None,
    db: Session = Depends(get_db)
):
    """
    List all tools with optional filtering.
    
    Query Parameters:
        - assistant_id: Filter by assistant ID
        - tool_type: Filter by tool type (transfer_call, api_request, etc.)
    """
    query = db.query(Tool)
    
    if assistant_id:
        query = query.filter(Tool.assistant_id == assistant_id)
    
    if tool_type:
        try:
            query = query.filter(Tool.tool_type == DBToolType(tool_type))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid tool_type: {tool_type}"
            )
    
    tools = query.all()
    
    return ToolListResponse(
        tools=[ToolResponse(**tool.to_dict()) for tool in tools],
        total=len(tools)
    )


@router.get("/{tool_id}", response_model=ToolResponse)
def get_tool(tool_id: str, db: Session = Depends(get_db)):
    """Get a specific tool by ID."""
    tool = db.query(Tool).filter(Tool.id == tool_id).first()
    
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool with id {tool_id} not found"
        )
    
    return ToolResponse(**tool.to_dict())


@router.post("", response_model=ToolResponse, status_code=status.HTTP_201_CREATED)
def create_tool(tool_data: ToolCreate, db: Session = Depends(get_db)):
    """
    Create a new tool.
    
    Example request body for Transfer Call:
    {
        "name": "transfer_to_front_desk",
        "description": "Transfer call to hotel front desk",
        "tool_type": "transfer_call",
        "config": {
            "phone_number": "+1-555-0123",
            "pre_transfer_message": "Let me connect you..."
        }
    }
    """
    # Generate unique ID
    tool_id = str(uuid.uuid4())
    
    # Convert Pydantic enum to SQLAlchemy enum
    db_tool_type = DBToolType(tool_data.tool_type.value)
    
    # Create database model
    new_tool = Tool(
        id=tool_id,
        name=tool_data.name,
        description=tool_data.description,
        tool_type=db_tool_type,
        config=tool_data.config,
        assistant_id=tool_data.assistant_id,
        is_active="true" if tool_data.is_active else "false"
    )
    
    db.add(new_tool)
    db.commit()
    db.refresh(new_tool)
    
    return ToolResponse(**new_tool.to_dict())


@router.put("/{tool_id}", response_model=ToolResponse)
def update_tool(
    tool_id: str,
    tool_data: ToolUpdate,
    db: Session = Depends(get_db)
):
    """Update an existing tool."""
    tool = db.query(Tool).filter(Tool.id == tool_id).first()
    
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool with id {tool_id} not found"
        )
    
    # Update fields if provided
    if tool_data.name is not None:
        tool.name = tool_data.name
    if tool_data.description is not None:
        tool.description = tool_data.description
    if tool_data.config is not None:
        tool.config = tool_data.config
    if tool_data.is_active is not None:
        tool.is_active = "true" if tool_data.is_active else "false"
    
    db.commit()
    db.refresh(tool)
    
    return ToolResponse(**tool.to_dict())


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tool(tool_id: str, db: Session = Depends(get_db)):
    """Delete a tool."""
    tool = db.query(Tool).filter(Tool.id == tool_id).first()
    
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool with id {tool_id} not found"
        )
    
    db.delete(tool)
    db.commit()
    
    return None
