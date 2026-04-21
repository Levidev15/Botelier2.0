"""
MCP Client Service - Connects to external MCP servers for dynamic tools.

This service handles:
- Connecting to MCP servers via SSE/HTTP transport
- Discovering available tools
- Executing tool calls
- Managing connection state
"""

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger
import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.types import Tool as MCPTool

from botelier.services.ssrf_safe_transport import make_ssrf_safe_mcp_client_factory


class MCPClientError(Exception):
    """Base exception for MCP client errors."""
    pass


class MCPConnectionError(MCPClientError):
    """Raised when connection to MCP server fails."""
    pass


class MCPToolExecutionError(MCPClientError):
    """Raised when tool execution fails."""
    pass


class MCPClient:
    """
    Client for connecting to MCP servers and executing tools.
    
    Supports SSE transport for remote MCP server connections.
    Each instance represents a connection to a single MCP server.
    """
    
    def __init__(
        self,
        server_url: str,
        auth_type: str = "none",
        credentials: Optional[Dict[str, str]] = None,
        connection_config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize MCP client.
        
        Args:
            server_url: URL of the MCP server (SSE endpoint)
            auth_type: Authentication type (none, api_key, bearer, basic)
            credentials: Authentication credentials
            connection_config: Additional connection configuration
        """
        self.server_url = server_url
        self.auth_type = auth_type
        self.credentials = credentials or {}
        self.connection_config = connection_config or {}
        
        self._session: Optional[ClientSession] = None
        self._read_stream = None
        self._write_stream = None
        self._context_manager = None
        self._discovered_tools: List[Dict] = []
    
    def _get_headers(self) -> Dict[str, str]:
        """Build authentication headers based on auth_type."""
        headers = {}
        
        if self.auth_type == "api_key":
            api_key = self.credentials.get("api_key", "")
            header_name = self.credentials.get("header_name", "X-API-Key")
            headers[header_name] = api_key
        
        elif self.auth_type == "bearer":
            token = self.credentials.get("token", "")
            headers["Authorization"] = f"Bearer {token}"
        
        elif self.auth_type == "basic":
            import base64
            username = self.credentials.get("username", "")
            password = self.credentials.get("password", "")
            encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        
        return headers
    
    async def connect(self, timeout: float = 30.0) -> Tuple[bool, Optional[str]]:
        """
        Connect to the MCP server.
        
        Args:
            timeout: Connection timeout in seconds
            
        Returns:
            Tuple of (success, error_message)
        """
        try:
            headers = self._get_headers()
            
            self._context_manager = sse_client(
                url=self.server_url,
                headers=headers,
                timeout=timeout,
                httpx_client_factory=make_ssrf_safe_mcp_client_factory(),
            )
            
            streams = await self._context_manager.__aenter__()
            self._read_stream, self._write_stream = streams
            
            self._session = ClientSession(
                read_stream=self._read_stream,
                write_stream=self._write_stream,
            )
            
            await self._session.__aenter__()
            
            await self._session.initialize()
            
            logger.info(f"Connected to MCP server: {self.server_url}")
            return True, None
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to connect to MCP server {self.server_url}: {error_msg}")
            await self.disconnect()
            return False, error_msg
    
    async def disconnect(self):
        """Disconnect from the MCP server."""
        try:
            if self._session:
                try:
                    await self._session.__aexit__(None, None, None)
                except Exception:
                    pass
                self._session = None
            
            if self._context_manager:
                try:
                    await self._context_manager.__aexit__(None, None, None)
                except Exception:
                    pass
                self._context_manager = None
            
            self._read_stream = None
            self._write_stream = None
            self._discovered_tools = []
            
            logger.info(f"Disconnected from MCP server: {self.server_url}")
        except Exception as e:
            logger.error(f"Error during disconnect: {e}")
    
    async def discover_tools(self) -> List[Dict]:
        """
        Discover available tools from the MCP server.
        
        Returns:
            List of tool definitions in OpenAI-compatible format
        """
        if not self._session:
            raise MCPConnectionError("Not connected to MCP server")
        
        try:
            result = await self._session.list_tools()
            tools = result.tools if hasattr(result, 'tools') else []
            
            self._discovered_tools = []
            for tool in tools:
                tool_def = self._convert_mcp_tool_to_openai_format(tool)
                self._discovered_tools.append(tool_def)
            
            logger.info(f"Discovered {len(self._discovered_tools)} tools from MCP server")
            return self._discovered_tools
            
        except Exception as e:
            logger.error(f"Failed to discover tools: {e}")
            raise MCPClientError(f"Failed to discover tools: {e}")
    
    def _convert_mcp_tool_to_openai_format(self, mcp_tool: MCPTool) -> Dict:
        """
        Convert MCP tool definition to OpenAI-compatible format.
        
        This allows seamless integration with Pipecat's function calling.
        """
        input_schema = mcp_tool.inputSchema if hasattr(mcp_tool, 'inputSchema') else {}
        
        if isinstance(input_schema, dict):
            properties = input_schema.get("properties", {})
            required = input_schema.get("required", [])
        else:
            properties = {}
            required = []
        
        return {
            "name": mcp_tool.name,
            "description": mcp_tool.description or f"Execute {mcp_tool.name}",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
            "source": "mcp",
        }
    
    async def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute a tool on the MCP server.
        
        Args:
            tool_name: Name of the tool to execute
            arguments: Arguments to pass to the tool
            
        Returns:
            Tool execution result
        """
        if not self._session:
            raise MCPConnectionError("Not connected to MCP server")
        
        try:
            logger.info(f"Executing MCP tool: {tool_name} with args: {arguments}")
            
            result = await self._session.call_tool(tool_name, arguments)
            
            if hasattr(result, 'content'):
                content = result.content
                if isinstance(content, list) and len(content) > 0:
                    first_content = content[0]
                    if hasattr(first_content, 'text'):
                        return {"result": first_content.text, "success": True}
                    return {"result": str(first_content), "success": True}
                return {"result": str(content), "success": True}
            
            return {"result": str(result), "success": True}
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"MCP tool execution failed: {error_msg}")
            return {"error": error_msg, "success": False}
    
    @property
    def is_connected(self) -> bool:
        """Check if connected to MCP server."""
        return self._session is not None
    
    @property
    def discovered_tools_list(self) -> List[Dict]:
        """Get list of discovered tools."""
        return self._discovered_tools


async def test_mcp_connection(
    server_url: str,
    auth_type: str = "none",
    credentials: Optional[Dict[str, str]] = None,
    timeout: float = 10.0,
) -> Tuple[bool, Optional[str], List[Dict]]:
    """
    Test connection to an MCP server and discover tools.
    
    This is a convenience function for testing connections without
    maintaining a persistent client instance.
    
    Args:
        server_url: URL of the MCP server
        auth_type: Authentication type
        credentials: Authentication credentials
        timeout: Connection timeout
        
    Returns:
        Tuple of (success, error_message, discovered_tools)
    """
    client = MCPClient(
        server_url=server_url,
        auth_type=auth_type,
        credentials=credentials,
    )
    
    try:
        success, error = await client.connect(timeout=timeout)
        if not success:
            return False, error, []
        
        tools = await client.discover_tools()
        return True, None, tools
        
    except Exception as e:
        return False, str(e), []
        
    finally:
        await client.disconnect()


class MCPClientPool:
    """
    Pool of MCP client connections for multi-tenant use.
    
    Manages one client per MCP connection, allowing efficient
    reuse of connections across multiple assistants.
    """
    
    def __init__(self):
        self._clients: Dict[str, MCPClient] = {}
        self._lock = asyncio.Lock()
    
    async def get_or_create_client(
        self,
        connection_id: str,
        server_url: str,
        auth_type: str = "none",
        credentials: Optional[Dict[str, str]] = None,
        connection_config: Optional[Dict[str, Any]] = None,
    ) -> MCPClient:
        """
        Get or create an MCP client for the given connection.
        
        Args:
            connection_id: Unique identifier for the connection
            server_url: URL of the MCP server
            auth_type: Authentication type
            credentials: Authentication credentials
            connection_config: Additional configuration
            
        Returns:
            Connected MCPClient instance
        """
        async with self._lock:
            if connection_id in self._clients:
                client = self._clients[connection_id]
                if client.is_connected:
                    return client
                del self._clients[connection_id]
            
            client = MCPClient(
                server_url=server_url,
                auth_type=auth_type,
                credentials=credentials,
                connection_config=connection_config,
            )
            
            success, error = await client.connect()
            if not success:
                raise MCPConnectionError(f"Failed to connect: {error}")
            
            await client.discover_tools()
            self._clients[connection_id] = client
            
            return client
    
    async def remove_client(self, connection_id: str):
        """Remove and disconnect a client from the pool."""
        async with self._lock:
            if connection_id in self._clients:
                await self._clients[connection_id].disconnect()
                del self._clients[connection_id]
    
    async def disconnect_all(self):
        """Disconnect all clients in the pool."""
        async with self._lock:
            for client in self._clients.values():
                await client.disconnect()
            self._clients.clear()


mcp_client_pool = MCPClientPool()
