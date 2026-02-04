"""
Test MCP Server - For testing MCP client integration.

This is a temporary test server that exposes sample tools via SSE transport.
It can be removed once MCP integration is verified.
"""

import os
import json
from datetime import datetime
from typing import Any

from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import JSONResponse
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent
import uvicorn


TEST_API_KEY = os.environ.get("TEST_MCP_API_KEY", "test-api-key-12345")

mcp_server = Server("test-mcp-server")


@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    """Return list of available test tools."""
    return [
        Tool(
            name="get_current_time",
            description="Get the current date and time",
            inputSchema={
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "Timezone (e.g., 'UTC', 'America/New_York'). Defaults to UTC.",
                    }
                },
                "required": [],
            },
        ),
        Tool(
            name="echo_message",
            description="Echo back a message (useful for testing)",
            inputSchema={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The message to echo back",
                    }
                },
                "required": ["message"],
            },
        ),
        Tool(
            name="lookup_guest",
            description="Look up a hotel guest by name or confirmation number",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Guest name to search for",
                    },
                    "confirmation_number": {
                        "type": "string",
                        "description": "Reservation confirmation number",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="check_room_availability",
            description="Check room availability for given dates",
            inputSchema={
                "type": "object",
                "properties": {
                    "check_in_date": {
                        "type": "string",
                        "description": "Check-in date (YYYY-MM-DD)",
                    },
                    "check_out_date": {
                        "type": "string",
                        "description": "Check-out date (YYYY-MM-DD)",
                    },
                    "room_type": {
                        "type": "string",
                        "description": "Room type (e.g., 'standard', 'deluxe', 'suite')",
                    },
                },
                "required": ["check_in_date", "check_out_date"],
            },
        ),
    ]


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool execution."""
    
    if name == "get_current_time":
        tz = arguments.get("timezone", "UTC")
        current_time = datetime.utcnow().isoformat() + "Z"
        return [TextContent(type="text", text=f"Current time ({tz}): {current_time}")]
    
    elif name == "echo_message":
        message = arguments.get("message", "")
        return [TextContent(type="text", text=f"Echo: {message}")]
    
    elif name == "lookup_guest":
        name_query = arguments.get("name", "")
        conf_num = arguments.get("confirmation_number", "")
        
        mock_guests = [
            {"name": "John Smith", "room": "302", "confirmation": "ABC123", "status": "checked_in"},
            {"name": "Jane Doe", "room": "415", "confirmation": "XYZ789", "status": "arriving_today"},
            {"name": "Bob Wilson", "room": "201", "confirmation": "DEF456", "status": "checked_out"},
        ]
        
        for guest in mock_guests:
            if name_query.lower() in guest["name"].lower() or conf_num.upper() == guest["confirmation"]:
                return [TextContent(type="text", text=json.dumps(guest, indent=2))]
        
        return [TextContent(type="text", text="No guest found matching the search criteria.")]
    
    elif name == "check_room_availability":
        check_in = arguments.get("check_in_date", "")
        check_out = arguments.get("check_out_date", "")
        room_type = arguments.get("room_type", "any")
        
        availability = {
            "check_in": check_in,
            "check_out": check_out,
            "available_rooms": [
                {"type": "standard", "count": 5, "rate": 150},
                {"type": "deluxe", "count": 3, "rate": 225},
                {"type": "suite", "count": 2, "rate": 400},
            ],
        }
        
        return [TextContent(type="text", text=json.dumps(availability, indent=2))]
    
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


sse_transport = SseServerTransport("/sse")


async def root_handler(request):
    return JSONResponse({
        "name": "Test MCP Server",
        "description": "A test MCP server for verifying MCP client integration",
        "tools": ["get_current_time", "echo_message", "lookup_guest", "check_room_availability"],
        "auth_required": os.environ.get("TEST_MCP_REQUIRE_AUTH", "false").lower() == "true",
    })


async def handle_sse(scope, receive, send):
    """Raw ASGI handler for SSE GET connections."""
    require_auth = os.environ.get("TEST_MCP_REQUIRE_AUTH", "false").lower() == "true"
    
    if require_auth:
        headers = dict(scope.get("headers", []))
        api_key = headers.get(b"x-api-key", b"").decode()
        if api_key != TEST_API_KEY:
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [[b"content-type", b"application/json"]],
            })
            await send({
                "type": "http.response.body",
                "body": b'{"error": "Invalid API key"}',
            })
            return
    
    async with sse_transport.connect_sse(scope, receive, send) as streams:
        await mcp_server.run(
            streams[0],
            streams[1],
            mcp_server.create_initialization_options(),
        )


async def handle_sse_post(scope, receive, send):
    """Raw ASGI handler for SSE POST messages."""
    require_auth = os.environ.get("TEST_MCP_REQUIRE_AUTH", "false").lower() == "true"
    
    if require_auth:
        headers = dict(scope.get("headers", []))
        api_key = headers.get(b"x-api-key", b"").decode()
        if api_key != TEST_API_KEY:
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [[b"content-type", b"application/json"]],
            })
            await send({
                "type": "http.response.body",
                "body": b'{"error": "Invalid API key"}',
            })
            return
    
    await sse_transport.handle_post_message(scope, receive, send)


async def sse_app(scope, receive, send):
    """ASGI app that routes SSE requests by method."""
    if scope["type"] != "http":
        return
    
    method = scope.get("method", "GET")
    
    if method == "GET":
        await handle_sse(scope, receive, send)
    elif method == "POST":
        await handle_sse_post(scope, receive, send)
    else:
        await send({
            "type": "http.response.start",
            "status": 405,
            "headers": [[b"content-type", b"application/json"]],
        })
        await send({
            "type": "http.response.body",
            "body": b'{"error": "Method not allowed"}',
        })


app = Starlette(
    routes=[
        Route("/", endpoint=root_handler),
        Mount("/sse", app=sse_app),
    ]
)


if __name__ == "__main__":
    print("🧪 Starting Test MCP Server on port 3002...")
    print(f"📍 SSE endpoint: http://localhost:3002/sse")
    print(f"🔑 API Key auth: {os.environ.get('TEST_MCP_REQUIRE_AUTH', 'false')}")
    
    uvicorn.run(app, host="0.0.0.0", port=3002)
