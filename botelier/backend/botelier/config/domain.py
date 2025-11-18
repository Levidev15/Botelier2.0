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
    2. REPLIT_DEV_DOMAIN - Automatic Replit development domain
    3. fallback_host - Optional Host header from incoming request
    4. localhost - Last resort (will not work for external webhooks)
    
    Args:
        fallback_host: Optional host from request headers (e.g., request.headers.get("Host"))
        
    Returns:
        Public base URL with https:// scheme (e.g., "https://mydomain.com")
        
    Examples:
        >>> get_public_base_url()
        "https://abc123.username.repl.co"
        
        >>> os.environ["PUBLIC_BASE_URL"] = "https://api.botelier.com"
        >>> get_public_base_url()
        "https://api.botelier.com"
    """
    # Priority 1: Explicit production URL
    public_url = os.environ.get("PUBLIC_BASE_URL")
    if public_url:
        # Ensure it has a scheme
        if not public_url.startswith(("http://", "https://")):
            public_url = f"https://{public_url}"
        return public_url.rstrip("/")
    
    # Priority 2: Replit development domain
    replit_domain = os.environ.get("REPLIT_DEV_DOMAIN")
    if replit_domain:
        return f"https://{replit_domain}"
    
    # Priority 3: Fallback host from request
    if fallback_host:
        # Remove port if present (use standard HTTPS port)
        host_without_port = fallback_host.split(":")[0]
        return f"https://{host_without_port}"
    
    # Priority 4: localhost (won't work for external webhooks!)
    return "https://localhost"


def get_websocket_url(path: str = "/ws/call", fallback_host: Optional[str] = None) -> str:
    """
    Get the WebSocket URL for Twilio Media Streams.
    
    Converts the public base URL from https:// to wss:// and appends the path.
    
    Args:
        path: WebSocket endpoint path (default: "/ws/call")
        fallback_host: Optional host from request headers
        
    Returns:
        WebSocket URL with wss:// scheme (e.g., "wss://mydomain.com/ws/call")
        
    Examples:
        >>> get_websocket_url()
        "wss://abc123.username.repl.co/ws/call"
        
        >>> get_websocket_url("/ws/custom")
        "wss://abc123.username.repl.co/ws/custom"
    """
    base_url = get_public_base_url(fallback_host=fallback_host)
    
    # Convert https:// to wss:// (or http:// to ws:// for localhost)
    ws_url = base_url.replace("https://", "wss://").replace("http://", "ws://")
    
    # Ensure path starts with /
    if not path.startswith("/"):
        path = f"/{path}"
    
    return f"{ws_url}{path}"
