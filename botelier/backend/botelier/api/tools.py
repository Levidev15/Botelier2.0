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
    hotel_id: str,
    assistant_id: str = None,
    tool_type: str = None,
    db: Session = Depends(get_db)
):
    """
    List all tools for a hotel with optional filtering.
    
    Query Parameters:
        - hotel_id: Hotel ID (REQUIRED for multi-tenant isolation)
        - assistant_id: Filter by assistant ID (optional)
        - tool_type: Filter by tool type (optional)
    """
    query = db.query(Tool).filter(Tool.hotel_id == hotel_id)
    
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
def get_tool(tool_id: str, hotel_id: str, db: Session = Depends(get_db)):
    """Get a specific tool by ID (multi-tenant scoped)."""
    tool = db.query(Tool).filter(
        Tool.id == tool_id,
        Tool.hotel_id == hotel_id
    ).first()
    
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool with id {tool_id} not found for this hotel"
        )
    
    return ToolResponse(**tool.to_dict())


@router.post("", response_model=ToolResponse, status_code=status.HTTP_201_CREATED)
def create_tool(tool_data: ToolCreate, db: Session = Depends(get_db)):
    """
    Create a new tool.
    
    TODO (SECURITY): Once authentication is implemented, hotel_id must be derived from 
    authenticated user context rather than trusted from request body. This endpoint 
    currently validates referential integrity but cannot prevent cross-tenant writes 
    without auth. See backlog for tenant-scoped authentication implementation.
    
    Example request body for Transfer Call:
    {
        "name": "transfer_to_front_desk",
        "description": "Transfer call to hotel front desk",
        "tool_type": "transfer_call",
        "config": {
            "phone_number": "+1-555-0123",
            "pre_transfer_message": "Let me connect you..."
        },
        "hotel_id": "uuid-from-auth-context"
    }
    """
    # Validate hotel_id exists (referential integrity)
    from ..models.hotel import Hotel
    hotel = db.query(Hotel).filter(Hotel.id == tool_data.hotel_id).first()
    if not hotel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hotel with id {tool_data.hotel_id} not found"
        )
    
    # Validate assistant belongs to same hotel (if provided)
    if tool_data.assistant_id:
        from ..models.assistant import Assistant
        assistant = db.query(Assistant).filter(Assistant.id == tool_data.assistant_id).first()
        if not assistant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Assistant with id {tool_data.assistant_id} not found"
            )
        if assistant.hotel_id != tool_data.hotel_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Assistant does not belong to the specified hotel"
            )
    
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
        hotel_id=tool_data.hotel_id,
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
    hotel_id: str,
    tool_data: ToolUpdate,
    db: Session = Depends(get_db)
):
    """Update an existing tool (multi-tenant scoped)."""
    tool = db.query(Tool).filter(
        Tool.id == tool_id,
        Tool.hotel_id == hotel_id
    ).first()
    
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool with id {tool_id} not found for this hotel"
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
def delete_tool(tool_id: str, hotel_id: str, db: Session = Depends(get_db)):
    """Delete a tool (multi-tenant scoped)."""
    tool = db.query(Tool).filter(
        Tool.id == tool_id,
        Tool.hotel_id == hotel_id
    ).first()
    
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool with id {tool_id} not found for this hotel"
        )
    
    db.delete(tool)
    db.commit()
    
    return None


# Flow-specific endpoints

@router.get("/{tool_id}/flow")
def get_tool_flow(tool_id: str, hotel_id: str, db: Session = Depends(get_db)):
    """
    Get flow configuration for a flow-type tool.
    
    Returns the visual flow editor data (nodes, edges, initial_node).
    """
    tool = db.query(Tool).filter(
        Tool.id == tool_id,
        Tool.hotel_id == hotel_id
    ).first()
    
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool with id {tool_id} not found for this hotel"
        )
    
    if tool.tool_type != DBToolType.FLOW:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tool {tool_id} is not a flow type tool"
        )
    
    flow_config = tool.config or {}
    
    return {
        "tool_id": tool.id,
        "hotel_id": str(tool.hotel_id),
        "name": tool.name,
        "flow_config": {
            "initial_node": flow_config.get("initial_node"),
            "nodes": flow_config.get("nodes", []),
            "edges": flow_config.get("edges", []),
            "variables": flow_config.get("variables", [])
        }
    }


@router.put("/{tool_id}/flow")
def update_tool_flow(
    tool_id: str,
    hotel_id: str,
    flow_data: dict,
    db: Session = Depends(get_db)
):
    """
    Update flow configuration for a flow-type tool.
    
    Saves the visual flow editor data (nodes, edges, initial_node).
    """
    tool = db.query(Tool).filter(
        Tool.id == tool_id,
        Tool.hotel_id == hotel_id
    ).first()
    
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool with id {tool_id} not found for this hotel"
        )
    
    if tool.tool_type != DBToolType.FLOW:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tool {tool_id} is not a flow type tool"
        )
    
    flow_config = flow_data.get("flow_config", {})
    
    tool.config = {
        "initial_node": flow_config.get("initial_node"),
        "nodes": flow_config.get("nodes", []),
        "edges": flow_config.get("edges", []),
        "variables": flow_config.get("variables", [])
    }
    
    db.commit()
    db.refresh(tool)
    
    return {
        "tool_id": tool.id,
        "message": "Flow configuration saved successfully",
        "flow_config": tool.config
    }
