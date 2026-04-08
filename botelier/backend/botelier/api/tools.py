"""
Tools API endpoints.

Provides CRUD operations for managing AI assistant tools/functions.
Tools are scoped through their ToolSet's account_id for multi-tenant isolation.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import uuid

from botelier.database import get_db
from botelier.models.tool import Tool, ToolType as DBToolType
from botelier.models.tool_set import ToolSet
from botelier.models.user import User
from botelier.auth.middleware import get_current_user, check_account_permission, get_hotel_context, AccountContext
from botelier.schemas.tool_schemas import (
    ToolCreate,
    ToolUpdate,
    ToolResponse,
    ToolListResponse,
    ToolType
)

router = APIRouter(prefix="/api/tools", tags=["tools"])


def _scope_query_by_account(query, db, tool_set_id: str = None, account_id: str = None):
    """Apply multi-tenant scoping to a tool query.
    
    Tools are scoped through their ToolSet's account_id.
    When account_id is provided, it resolves through ToolSet.account_id.
    """
    if tool_set_id:
        query = query.filter(Tool.tool_set_id == tool_set_id)
    elif account_id:
        query = query.join(ToolSet, Tool.tool_set_id == ToolSet.id).filter(
            ToolSet.account_id == account_id
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either tool_set_id or account_id is required"
        )
    return query


@router.get("")
def list_tools(
    tool_set_id: str = None,
    assistant_id: str = None,
    tool_type: str = None,
    ctx: AccountContext = Depends(get_hotel_context("tools.view")),
    db: Session = Depends(get_db),
):
    """List tools scoped by tool_set_id or account_id."""
    account_id = str(ctx.account.id)
    query = db.query(Tool)
    query = _scope_query_by_account(query, db, tool_set_id, account_id)

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

    return {"tools": [tool.to_dict() for tool in tools], "total": len(tools)}


@router.get("/{tool_id}")
def get_tool(
    tool_id: str,
    tool_set_id: str = None,
    account_id: str = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a specific tool by ID, scoped by tool_set_id or account_id."""
    if account_id:
        check_account_permission(user, account_id, "tools.view", db)
    elif tool_set_id:
        ts = db.query(ToolSet).filter(ToolSet.id == tool_set_id).first()
        if ts:
            check_account_permission(user, str(ts.account_id), "tools.view", db)
    query = db.query(Tool).filter(Tool.id == tool_id)
    query = _scope_query_by_account(query, db, tool_set_id, account_id)

    tool = query.first()

    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tool not found"
        )

    return tool.to_dict()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_tool(
    tool_data: ToolCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new tool, scoped to a tool set."""
    if not tool_data.tool_set_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tool_set_id is required"
        )

    tool_set = db.query(ToolSet).filter(ToolSet.id == tool_data.tool_set_id).first()
    if not tool_set:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tool set not found"
        )
    check_account_permission(user, str(tool_set.account_id), "tools.create", db)

    tool_id = str(uuid.uuid4())
    db_tool_type = DBToolType(tool_data.tool_type.value)

    new_tool = Tool(
        id=tool_id,
        name=tool_data.name,
        description=tool_data.description,
        tool_type=db_tool_type,
        config=tool_data.config,
        tool_set_id=tool_data.tool_set_id,
        is_active="true" if tool_data.is_active else "false"
    )

    db.add(new_tool)
    db.commit()
    db.refresh(new_tool)

    return new_tool.to_dict()


@router.put("/{tool_id}")
def update_tool(
    tool_id: str,
    tool_data: ToolUpdate,
    tool_set_id: str = None,
    account_id: str = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update an existing tool, scoped by tool_set_id or account_id."""
    if account_id:
        check_account_permission(user, account_id, "tools.edit", db)
    elif tool_set_id:
        ts = db.query(ToolSet).filter(ToolSet.id == tool_set_id).first()
        if ts:
            check_account_permission(user, str(ts.account_id), "tools.edit", db)
    query = db.query(Tool).filter(Tool.id == tool_id)
    query = _scope_query_by_account(query, db, tool_set_id, account_id)

    tool = query.first()

    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tool not found"
        )

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

    return tool.to_dict()


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tool(
    tool_id: str,
    tool_set_id: str = None,
    account_id: str = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a tool, scoped by tool_set_id or account_id."""
    if account_id:
        check_account_permission(user, account_id, "tools.delete", db)
    elif tool_set_id:
        ts = db.query(ToolSet).filter(ToolSet.id == tool_set_id).first()
        if ts:
            check_account_permission(user, str(ts.account_id), "tools.delete", db)
    query = db.query(Tool).filter(Tool.id == tool_id)
    query = _scope_query_by_account(query, db, tool_set_id, account_id)

    tool = query.first()

    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tool not found"
        )

    db.delete(tool)
    db.commit()

    return None
