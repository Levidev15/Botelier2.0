"""
API endpoints for ToolSet management.

ToolSets are named collections of tools that can be assigned to assistants.
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from sqlalchemy.orm import Session

from botelier.database import get_db
from botelier.models.tool_set import ToolSet
from botelier.models.tool import Tool, ToolType

router = APIRouter(prefix="/api/tool-sets", tags=["tool-sets"])


class ToolSetCreate(BaseModel):
    account_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class ToolSetUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None


class ToolSetResponse(BaseModel):
    id: UUID
    account_id: UUID
    name: str
    description: Optional[str]
    tool_count: int
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


class ToolSetListResponse(BaseModel):
    tool_sets: List[ToolSetResponse]
    total: int


class ToolResponse(BaseModel):
    id: str
    tool_set_id: Optional[UUID]
    name: str
    description: str
    tool_type: str
    config: dict
    is_active: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


class ToolListResponse(BaseModel):
    tools: List[ToolResponse]
    total: int


@router.get("", response_model=ToolSetListResponse)
async def list_tool_sets(
    account_id: UUID = Query(..., description="Account ID to filter by"),
    db: Session = Depends(get_db)
):
    """List all tool sets for an account."""
    tool_sets = db.query(ToolSet).filter(ToolSet.account_id == account_id).all()
    
    result = []
    for ts in tool_sets:
        tool_count = db.query(Tool).filter(Tool.tool_set_id == ts.id).count()
        result.append({
            "id": ts.id,
            "account_id": ts.account_id,
            "name": ts.name,
            "description": ts.description,
            "tool_count": tool_count,
            "created_at": ts.created_at,
            "updated_at": ts.updated_at,
        })
    
    return {"tool_sets": result, "total": len(result)}


@router.post("", response_model=ToolSetResponse)
async def create_tool_set(data: ToolSetCreate, db: Session = Depends(get_db)):
    """Create a new tool set."""
    try:
        tool_set = ToolSet(
            account_id=data.account_id,
            name=data.name,
            description=data.description,
        )
        
        db.add(tool_set)
        db.commit()
        db.refresh(tool_set)
        
        return {
            "id": tool_set.id,
            "account_id": tool_set.account_id,
            "name": tool_set.name,
            "description": tool_set.description,
            "tool_count": 0,
            "created_at": tool_set.created_at,
            "updated_at": tool_set.updated_at,
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{tool_set_id}")
async def get_tool_set(tool_set_id: UUID, db: Session = Depends(get_db)):
    """Get a specific tool set by ID."""
    tool_set = db.query(ToolSet).filter(ToolSet.id == tool_set_id).first()
    
    if not tool_set:
        raise HTTPException(status_code=404, detail="Tool set not found")
    
    tool_count = db.query(Tool).filter(Tool.tool_set_id == tool_set.id).count()
    
    return {
        "id": tool_set.id,
        "account_id": tool_set.account_id,
        "name": tool_set.name,
        "description": tool_set.description,
        "tool_count": tool_count,
        "created_at": tool_set.created_at,
        "updated_at": tool_set.updated_at,
    }


@router.put("/{tool_set_id}")
async def update_tool_set(tool_set_id: UUID, data: ToolSetUpdate, db: Session = Depends(get_db)):
    """Update a tool set."""
    try:
        tool_set = db.query(ToolSet).filter(ToolSet.id == tool_set_id).first()
        
        if not tool_set:
            raise HTTPException(status_code=404, detail="Tool set not found")
        
        if data.name is not None:
            tool_set.name = data.name
        if data.description is not None:
            tool_set.description = data.description
        
        db.commit()
        db.refresh(tool_set)
        
        tool_count = db.query(Tool).filter(Tool.tool_set_id == tool_set.id).count()
        
        return {
            "id": tool_set.id,
            "account_id": tool_set.account_id,
            "name": tool_set.name,
            "description": tool_set.description,
            "tool_count": tool_count,
            "created_at": tool_set.created_at,
            "updated_at": tool_set.updated_at,
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{tool_set_id}")
async def delete_tool_set(tool_set_id: UUID, db: Session = Depends(get_db)):
    """Delete a tool set and all its tools."""
    try:
        tool_set = db.query(ToolSet).filter(ToolSet.id == tool_set_id).first()
        
        if not tool_set:
            raise HTTPException(status_code=404, detail="Tool set not found")
        
        tool_count = db.query(Tool).filter(Tool.tool_set_id == tool_set.id).count()
        
        db.query(Tool).filter(Tool.tool_set_id == tool_set.id).delete()
        db.delete(tool_set)
        db.commit()
        
        return {"message": f"Tool set deleted with {tool_count} tools"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{tool_set_id}/tools", response_model=ToolListResponse)
async def list_tools_in_set(tool_set_id: UUID, db: Session = Depends(get_db)):
    """List all tools in a tool set."""
    tool_set = db.query(ToolSet).filter(ToolSet.id == tool_set_id).first()
    if not tool_set:
        raise HTTPException(status_code=404, detail="Tool set not found")
    
    tools = db.query(Tool).filter(Tool.tool_set_id == tool_set_id).all()
    
    result = []
    for tool in tools:
        result.append({
            "id": tool.id,
            "tool_set_id": tool.tool_set_id,
            "name": tool.name,
            "description": tool.description,
            "tool_type": tool.tool_type.value,
            "config": tool.config,
            "is_active": tool.is_active == "true",
            "created_at": tool.created_at,
            "updated_at": tool.updated_at,
        })
    
    return {"tools": result, "total": len(result)}
