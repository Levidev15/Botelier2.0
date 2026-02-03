"""
MCP Connections API - CRUD operations for MCP server connections.

MCP (Model Context Protocol) connections allow accounts to connect to external
MCP servers that provide dynamic tools for their voice assistants.

Architecture:
- MCP Connections are named collections belonging to an account
- Each connection can provide multiple tools from the MCP server
- Assistants reference connections and select which tools to enable

Endpoints:
- POST /api/mcp-connections - Create new MCP connection
- GET /api/mcp-connections - List all MCP connections for account
- GET /api/mcp-connections/{connection_id} - Get connection details
- PUT /api/mcp-connections/{connection_id} - Update connection
- DELETE /api/mcp-connections/{connection_id} - Delete connection
- POST /api/mcp-connections/{connection_id}/test - Test connection
- POST /api/mcp-connections/{connection_id}/discover-tools - Discover available tools
- POST /api/mcp-connections/test - Test connection without saving
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from loguru import logger

from botelier.database import get_db
from botelier.models.mcp_connection import (
    MCPConnection,
    MCPConnectionStatus,
    MCPAuthType,
    MCPTransportType,
)
from botelier.services.mcp_client import test_mcp_connection


router = APIRouter(prefix="/api/mcp-connections", tags=["mcp-connections"])


class MCPCredentials(BaseModel):
    """Credentials for MCP server authentication."""
    api_key: Optional[str] = None
    header_name: Optional[str] = "X-API-Key"
    token: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


class MCPConnectionCreate(BaseModel):
    """Request model for creating an MCP connection."""
    account_id: str
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    transport_type: str = "sse"
    server_url: str = Field(..., min_length=1)
    auth_type: str = "none"
    credentials: Optional[MCPCredentials] = None
    connection_config: Optional[Dict[str, Any]] = None


class MCPConnectionUpdate(BaseModel):
    """Request model for updating an MCP connection."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    transport_type: Optional[str] = None
    server_url: Optional[str] = None
    auth_type: Optional[str] = None
    credentials: Optional[MCPCredentials] = None
    is_active: Optional[bool] = None
    connection_config: Optional[Dict[str, Any]] = None


class MCPConnectionTestRequest(BaseModel):
    """Request model for testing an MCP connection without saving."""
    server_url: str = Field(..., min_length=1)
    auth_type: str = "none"
    credentials: Optional[MCPCredentials] = None


def _validate_transport_type(value: str) -> MCPTransportType:
    """Validate and convert transport type string to enum."""
    try:
        return MCPTransportType(value.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid transport_type. Must be one of: {[t.value for t in MCPTransportType]}"
        )


def _validate_auth_type(value: str) -> MCPAuthType:
    """Validate and convert auth type string to enum."""
    try:
        return MCPAuthType(value.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid auth_type. Must be one of: {[a.value for a in MCPAuthType]}"
        )


@router.post("", status_code=201)
async def create_mcp_connection(
    data: MCPConnectionCreate,
    db: Session = Depends(get_db)
):
    """Create a new MCP connection."""
    transport_type = _validate_transport_type(data.transport_type)
    auth_type = _validate_auth_type(data.auth_type)
    
    connection = MCPConnection(
        account_id=data.account_id,
        name=data.name,
        description=data.description,
        transport_type=transport_type,
        server_url=data.server_url,
        auth_type=auth_type,
        status=MCPConnectionStatus.DISCONNECTED,
        connection_config=data.connection_config or {},
    )
    
    if data.credentials:
        connection.set_credentials(data.credentials.model_dump(exclude_none=True))
    
    db.add(connection)
    db.commit()
    db.refresh(connection)
    
    logger.info(f"Created MCP connection: {connection.name} (ID: {connection.id})")
    
    return connection.to_dict()


@router.get("")
async def list_mcp_connections(
    account_id: str,
    include_tools: bool = False,
    db: Session = Depends(get_db)
):
    """List all MCP connections for an account."""
    connections = db.query(MCPConnection).filter(
        MCPConnection.account_id == account_id
    ).order_by(MCPConnection.created_at.desc()).all()
    
    return [c.to_dict(include_tools=include_tools) for c in connections]


@router.get("/{connection_id}")
async def get_mcp_connection(
    connection_id: str,
    db: Session = Depends(get_db)
):
    """Get a specific MCP connection by ID."""
    connection = db.query(MCPConnection).filter(
        MCPConnection.id == connection_id
    ).first()
    
    if not connection:
        raise HTTPException(status_code=404, detail="MCP connection not found")
    
    return connection.to_dict(include_tools=True)


@router.put("/{connection_id}")
async def update_mcp_connection(
    connection_id: str,
    data: MCPConnectionUpdate,
    db: Session = Depends(get_db)
):
    """Update an existing MCP connection."""
    connection = db.query(MCPConnection).filter(
        MCPConnection.id == connection_id
    ).first()
    
    if not connection:
        raise HTTPException(status_code=404, detail="MCP connection not found")
    
    if data.name is not None:
        connection.name = data.name
    if data.description is not None:
        connection.description = data.description
    if data.transport_type is not None:
        connection.transport_type = _validate_transport_type(data.transport_type)
    if data.server_url is not None:
        connection.server_url = data.server_url
        connection.status = MCPConnectionStatus.DISCONNECTED
        connection.discovered_tools = []
    if data.auth_type is not None:
        connection.auth_type = _validate_auth_type(data.auth_type)
    if data.is_active is not None:
        connection.is_active = data.is_active
    if data.connection_config is not None:
        connection.connection_config = data.connection_config
    if data.credentials is not None:
        connection.set_credentials(data.credentials.model_dump(exclude_none=True))
    
    db.commit()
    db.refresh(connection)
    
    logger.info(f"Updated MCP connection: {connection.name}")
    
    return connection.to_dict()


@router.delete("/{connection_id}")
async def delete_mcp_connection(
    connection_id: str,
    db: Session = Depends(get_db)
):
    """Delete an MCP connection."""
    connection = db.query(MCPConnection).filter(
        MCPConnection.id == connection_id
    ).first()
    
    if not connection:
        raise HTTPException(status_code=404, detail="MCP connection not found")
    
    db.delete(connection)
    db.commit()
    
    logger.info(f"Deleted MCP connection: {connection.name}")
    
    return {"status": "deleted", "id": connection_id}


@router.post("/{connection_id}/test")
async def test_existing_connection(
    connection_id: str,
    db: Session = Depends(get_db)
):
    """Test an existing MCP connection and update its status."""
    connection = db.query(MCPConnection).filter(
        MCPConnection.id == connection_id
    ).first()
    
    if not connection:
        raise HTTPException(status_code=404, detail="MCP connection not found")
    
    connection.status = MCPConnectionStatus.CONNECTING
    db.commit()
    
    try:
        credentials = connection.get_credentials()
        success, error, tools = await test_mcp_connection(
            server_url=connection.server_url,
            auth_type=connection.auth_type.value if connection.auth_type else "none",
            credentials=credentials,
            timeout=15.0,
        )
        
        if success:
            connection.status = MCPConnectionStatus.CONNECTED
            connection.discovered_tools = tools
            connection.last_connected_at = datetime.utcnow()
            connection.last_error = None
        else:
            connection.status = MCPConnectionStatus.ERROR
            connection.last_error = error
        
        db.commit()
        db.refresh(connection)
        
        return {
            "success": success,
            "error": error,
            "tools": tools if success else [],
            "connection": connection.to_dict(include_tools=True),
        }
        
    except Exception as e:
        connection.status = MCPConnectionStatus.ERROR
        connection.last_error = str(e)
        db.commit()
        
        logger.error(f"Failed to test MCP connection {connection_id}: {e}")
        return {
            "success": False,
            "error": str(e),
            "tools": [],
            "connection": connection.to_dict(),
        }


@router.post("/{connection_id}/discover-tools")
async def discover_tools(
    connection_id: str,
    db: Session = Depends(get_db)
):
    """Discover available tools from an MCP server."""
    connection = db.query(MCPConnection).filter(
        MCPConnection.id == connection_id
    ).first()
    
    if not connection:
        raise HTTPException(status_code=404, detail="MCP connection not found")
    
    try:
        credentials = connection.get_credentials()
        success, error, tools = await test_mcp_connection(
            server_url=connection.server_url,
            auth_type=connection.auth_type.value if connection.auth_type else "none",
            credentials=credentials,
            timeout=15.0,
        )
        
        if success:
            connection.discovered_tools = tools
            connection.status = MCPConnectionStatus.CONNECTED
            connection.last_connected_at = datetime.utcnow()
            connection.last_error = None
            db.commit()
            
            return {
                "success": True,
                "tools": tools,
                "count": len(tools),
            }
        else:
            connection.status = MCPConnectionStatus.ERROR
            connection.last_error = error
            db.commit()
            
            return {
                "success": False,
                "error": error,
                "tools": [],
                "count": 0,
            }
            
    except Exception as e:
        logger.error(f"Failed to discover tools for {connection_id}: {e}")
        return {
            "success": False,
            "error": str(e),
            "tools": [],
            "count": 0,
        }


@router.post("/test")
async def test_connection_without_saving(
    data: MCPConnectionTestRequest,
):
    """Test an MCP connection without saving it."""
    try:
        credentials = data.credentials.model_dump(exclude_none=True) if data.credentials else {}
        
        success, error, tools = await test_mcp_connection(
            server_url=data.server_url,
            auth_type=data.auth_type,
            credentials=credentials,
            timeout=15.0,
        )
        
        return {
            "success": success,
            "error": error,
            "tools": tools if success else [],
            "count": len(tools) if success else 0,
        }
        
    except Exception as e:
        logger.error(f"Failed to test MCP connection: {e}")
        return {
            "success": False,
            "error": str(e),
            "tools": [],
            "count": 0,
        }
