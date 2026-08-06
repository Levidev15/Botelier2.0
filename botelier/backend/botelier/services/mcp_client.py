"""MCP Client Service - Connects to external MCP servers for dynamic tools.

This service handles:
- Connecting to MCP servers via SSE/HTTP transport
- Discovering available tools
- Executing tool calls
- Managing connection state
"""

import asyncio
import json
import ssl
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx
from loguru import logger
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.types import Tool as MCPTool

from botelier.services.ssrf_safe_transport import make_ssrf_safe_mcp_client_factory

SUPPORTED_MCP_TRANSPORT_VALUES = frozenset({"sse", "streamable_http"})


def _iter_exception_leaves(error: BaseException):
    """Yield concrete exceptions hidden inside ExceptionGroup/TaskGroup wrappers."""
    nested = getattr(error, "exceptions", None)
    if nested:
        for child in nested:
            yield from _iter_exception_leaves(child)
        return
    yield error


def _format_mcp_connection_error(error: BaseException) -> str:
    """Return an actionable, sanitized error from nested MCP transport failures."""
    leaves = list(_iter_exception_leaves(error))

    for leaf in leaves:
        chain = [leaf]
        cause = getattr(leaf, "__cause__", None)
        while cause is not None and cause not in chain:
            chain.append(cause)
            cause = getattr(cause, "__cause__", None)
        chain_text = " ".join(str(item) for item in chain).upper()
        if any(
            isinstance(item, ssl.SSLCertVerificationError) for item in chain
        ) or "CERTIFICATE_VERIFY_FAILED" in chain_text:
            return (
                "TLS certificate verification failed. The MCP server certificate "
                "is expired, incomplete, or issued by an untrusted certificate "
                "authority. Renew/fix the server certificate and full certificate "
                "chain, then test again."
            )

    for leaf in leaves:
        if isinstance(leaf, (httpx.ConnectTimeout, httpx.ReadTimeout, TimeoutError)):
            return (
                "Connection to the MCP server timed out. Confirm the URL is reachable "
                "and that the selected transport matches the server."
            )
        if isinstance(leaf, httpx.ConnectError):
            message = str(leaf).strip()
            return (
                f"Could not connect to the MCP server: {message}"
                if message
                else "Could not connect to the MCP server."
            )

    for leaf in leaves:
        message = str(leaf).strip()
        if (
            "Content-Type to contain 'text/event-stream'" in message
            and "application/json" in message
        ):
            return (
                "This server returned Streamable HTTP JSON instead of an SSE stream. "
                "Change the connection transport to 'Streamable HTTP' and test again."
            )

    # Prefer the deepest useful message over the generic outer TaskGroup text.
    for leaf in leaves:
        message = str(leaf).strip()
        if message and "TaskGroup" not in message:
            return message[:500]
    return str(error)[:500] or "MCP connection failed for an unknown reason."


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
    """Client for connecting to MCP servers and executing tools.

    Supports SSE transport for remote MCP server connections.
    Each instance represents a connection to a single MCP server.
    """

    def __init__(
        self,
        server_url: str,
        auth_type: str = "none",
        credentials: Optional[Dict[str, str]] = None,
        connection_config: Optional[Dict[str, Any]] = None,
        transport_type: str = "sse",
    ):
        """Initialize MCP client.

        Args:
            server_url: URL of the MCP server
            auth_type: Authentication type (none, api_key, bearer, basic)
            credentials: Authentication credentials
            connection_config: Additional connection configuration
            transport_type: Transport protocol — "sse" (default) or "streamable_http"
        """
        self.server_url = server_url
        self.auth_type = auth_type
        self.credentials = credentials or {}
        self.connection_config = connection_config or {}
        self.transport_type = transport_type

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

    async def _preflight_streamable_http(
        self, headers: Dict[str, str], timeout: float
    ) -> None:
        """Validate DNS/SSRF/TLS before MCP starts its AnyIO task group.

        A HEAD response of any HTTP status proves the network and TLS handshake
        succeeded; authentication and protocol validation remain the MCP
        initialize request's responsibility.
        """
        client_factory = make_ssrf_safe_mcp_client_factory()
        async with client_factory(
            headers=headers,
            timeout=httpx.Timeout(timeout),
        ) as client:
            await client.head(self.server_url)

    async def connect(self, timeout: float = 30.0) -> Tuple[bool, Optional[str]]:
        """Connect to the MCP server.

        Args:
            timeout: Connection timeout in seconds

        Returns:
            Tuple of (success, error_message)
        """
        try:
            if self.transport_type not in SUPPORTED_MCP_TRANSPORT_VALUES:
                raise MCPConnectionError(
                    f"Unsupported MCP transport {self.transport_type!r}; "
                    "supported transports are 'sse' and 'streamable_http'."
                )
            headers = self._get_headers()

            if self.transport_type == "streamable_http":
                from mcp.client.streamable_http import streamablehttp_client

                await self._preflight_streamable_http(headers, timeout)
                self._context_manager = streamablehttp_client(
                    url=self.server_url,
                    headers=headers,
                    timeout=timeout,
                    httpx_client_factory=make_ssrf_safe_mcp_client_factory(),
                )
            else:
                self._context_manager = sse_client(
                    url=self.server_url,
                    headers=headers,
                    timeout=timeout,
                    httpx_client_factory=make_ssrf_safe_mcp_client_factory(),
                )

            streams = await self._context_manager.__aenter__()
            # streamablehttp_client yields a 3-tuple (read, write, get_session_id);
            # sse_client yields a 2-tuple (read, write).
            if self.transport_type == "streamable_http":
                self._read_stream, self._write_stream, _ = streams
            else:
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
            error_msg = _format_mcp_connection_error(e)
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
        """Discover available tools from the MCP server.

        Returns:
            List of tool definitions in OpenAI-compatible format
        """
        if not self._session:
            raise MCPConnectionError("Not connected to MCP server")

        try:
            result = await self._session.list_tools()
            tools = result.tools if hasattr(result, "tools") else []

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
        """Convert MCP tool definition to OpenAI-compatible format.

        This allows seamless integration with Pipecat's function calling.
        """
        input_schema = mcp_tool.inputSchema if hasattr(mcp_tool, "inputSchema") else {}

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
        """Execute a tool on the MCP server.

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

            if hasattr(result, "content"):
                content = result.content
                if isinstance(content, list) and len(content) > 0:
                    first_content = content[0]
                    if hasattr(first_content, "text"):
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
    transport_type: str = "sse",
) -> Tuple[bool, Optional[str], List[Dict]]:
    """Test connection to an MCP server and discover tools.

    This is a convenience function for testing connections without
    maintaining a persistent client instance.

    Args:
        server_url: URL of the MCP server
        auth_type: Authentication type
        credentials: Authentication credentials
        timeout: Connection timeout
        transport_type: Transport protocol — "sse" or "streamable_http"

    Returns:
        Tuple of (success, error_message, discovered_tools)
    """
    client = MCPClient(
        server_url=server_url,
        auth_type=auth_type,
        credentials=credentials,
        transport_type=transport_type,
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
    """Pool of MCP client connections for multi-tenant use.

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
        transport_type: str = "sse",
    ) -> MCPClient:
        """Get or create an MCP client for the given connection.

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
                transport_type=transport_type,
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
