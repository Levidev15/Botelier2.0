"""
Domain configuration utilities for Botelier.

Provides helpers to reliably get the public base URL for webhook callbacks
and WebSocket connections in both development (Replit) and production environments.
"""

import os
from typing import Optional


def get_public_base_url(fallback_host: Optional[str] = None) -> str:
    """
    Get the public base URL for this application.
    
    This is used for Twilio webhooks, WebSocket URLs, and other callbacks
    that need to reach this server from external services.
    
    Priority order:
    1. PUBLIC_BASE_URL - Explicitly configured for production (with custom domains)
    2. REPLIT_DEV_DOMAIN - Automatic Replit development domain (with port from Host header)
    3. fallback_host - Optional Host header from incoming request (preserves port)
    4. localhost - Last resort (will not work for external webhooks)
    
    Args:
        fallback_host: Optional host from request headers (e.g., request.headers.get("Host"))
        
    Returns:
        Public base URL with https:// scheme (e.g., "https://mydomain.com:5000")
        
    Examples:
        >>> get_public_base_url()
        "https://abc123.username.repl.co"
        
        >>> os.environ["PUBLIC_BASE_URL"] = "https://api.botelier.com"
        >>> get_public_base_url()
        "https://api.botelier.com"
        
        >>> get_public_base_url(fallback_host="abc123.repl.dev:5000")
        "https://abc123.repl.dev:5000"  # Preserves port in dev
    """
    # Priority 1: Explicit production URL (no port modification)
    public_url = os.environ.get("PUBLIC_BASE_URL")
    if public_url:
        # Ensure it has a scheme
        if not public_url.startswith(("http://", "https://")):
            public_url = f"https://{public_url}"
        return public_url.rstrip("/")
    
    # Priority 2: Replit development domain
    # In dev, we need to include the port from the Host header if available
    replit_domain = os.environ.get("REPLIT_DEV_DOMAIN")
    if replit_domain:
        # Check if fallback_host includes a port and use it
        if fallback_host and ":" in fallback_host:
            # Extract port from Host header (e.g., "abc123.repl.dev:5000" -> ":5000")
            port = fallback_host.split(":", 1)[1]
            return f"https://{replit_domain}:{port}"
        return f"https://{replit_domain}"
    
    # Priority 3: Fallback host from request (preserve port for non-standard ports)
    if fallback_host:
        # Keep the full host including port (e.g., "localhost:5000")
        # This is critical for dev environments where backend runs on non-standard ports
        return f"https://{fallback_host}"
    
    # Priority 4: localhost (won't work for external webhooks!)
    return "https://localhost"


def get_websocket_url(path: str = "/api/ws/call", fallback_host: Optional[str] = None) -> str:
    """
    Get the WebSocket URL for Twilio Media Streams.
    
    Converts the public base URL from https:// to wss:// and appends the path.
    Preserves ports in development environments while using standard ports in production.
    
    Args:
        path: WebSocket endpoint path (default: "/api/ws/call")
        fallback_host: Optional host from request headers (preserves port if present)
        
    Returns:
        WebSocket URL with wss:// scheme (e.g., "wss://mydomain.com:5000/api/ws/call")
        
    Examples:
        >>> get_websocket_url()
        "wss://abc123.username.repl.co/api/ws/call"
        
        >>> get_websocket_url(fallback_host="abc123.repl.dev:5000")
        "wss://abc123.repl.dev:5000/api/ws/call"  # Port preserved for dev
        
        >>> os.environ["PUBLIC_BASE_URL"] = "https://api.botelier.com"
        >>> get_websocket_url()
        "wss://api.botelier.com/api/ws/call"  # No port in production
    """
    base_url = get_public_base_url(fallback_host=fallback_host)
    
    # Convert https:// to wss:// (or http:// to ws:// for localhost)
    # This preserves any port number in the base_url
    ws_url = base_url.replace("https://", "wss://").replace("http://", "ws://")
    
    # Ensure path starts with /
    if not path.startswith("/"):
        path = f"/{path}"
    
    return f"{ws_url}{path}"
