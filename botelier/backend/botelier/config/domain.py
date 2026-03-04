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
    
    # Priority 2: Replit domain — covers both development (REPLIT_DEV_DOMAIN) and
    # production (REPLIT_DOMAINS, a comma-separated list; first entry is canonical).
    # In dev, we may need to append the port from the Host header.
    replit_domain = os.environ.get("REPLIT_DEV_DOMAIN")
    if not replit_domain:
        # Production: REPLIT_DOMAINS = "my-app.username.repl.co,my-app.replit.app"
        replit_domains_str = os.environ.get("REPLIT_DOMAINS", "")
        if replit_domains_str:
            replit_domain = replit_domains_str.split(",")[0].strip()
    if replit_domain:
        # In dev environments, include the port from the Host header if non-standard
        if fallback_host and ":" in fallback_host:
            port = fallback_host.split(":", 1)[1]
            # Only append port if it's not 443 (standard HTTPS)
            if port and port != "443":
                return f"https://{replit_domain}:{port}"
        return f"https://{replit_domain}"
    
    # Priority 3: Fallback host from request (preserve port for non-standard ports)
    if fallback_host:
        # Keep the full host including port (e.g., "localhost:5000")
        # This is critical for dev environments where backend runs on non-standard ports
        return f"https://{fallback_host}"
    
    # Priority 4: localhost (won't work for external webhooks!)
    return "https://localhost"


def get_websocket_url(
    path: str = "/api/ws/call",
    fallback_host: Optional[str] = None,
    query_params: Optional[dict] = None
) -> str:
    """
    Get the WebSocket URL for Twilio Media Streams.
    
    Architecture:
    - HTTP API calls (dashboard): Frontend (5000) → Next.js proxy → Backend (3001)
    - WebSocket calls (Twilio): Twilio → Backend (3001) DIRECTLY (no proxy)
    
    This connects directly to the FastAPI backend on port 3001, bypassing the Next.js
    frontend entirely. This is the standard Pipecat pattern and avoids proxy issues.
    
    Args:
        path: WebSocket endpoint path (default: "/api/ws/call")
        fallback_host: Optional host from request headers (unused, kept for compatibility)
        query_params: Optional dict of query parameters to append
        
    Returns:
        WebSocket URL pointing directly to backend port 3001
        
    Examples:
        >>> # Replit dev - direct to backend
        >>> os.environ["REPLIT_DEV_DOMAIN"] = "abc123.repl.dev"
        >>> get_websocket_url()
        "wss://abc123.repl.dev:3001/api/ws/call"
        
        >>> # Production with custom backend URL
        >>> os.environ["BACKEND_WS_URL"] = "wss://api.botelier.com"
        >>> get_websocket_url()
        "wss://api.botelier.com/api/ws/call"
    """
    from urllib.parse import urlencode
    
    # Priority 1: Explicit backend WebSocket URL (for production with custom domains)
    backend_ws_url = os.environ.get("BACKEND_WS_URL")
    if backend_ws_url:
        # Ensure it has wss:// scheme
        if not backend_ws_url.startswith(("ws://", "wss://")):
            backend_ws_url = f"wss://{backend_ws_url}"
        ws_url = backend_ws_url.rstrip("/")
    else:
        # Priority 2: Replit domain — dev (REPLIT_DEV_DOMAIN) or production (REPLIT_DOMAINS)
        # In dev, the backend runs on port 3001 (no reverse proxy), so we include :3001.
        # In production (vm deployment), the backend also runs on 3001 internally,
        # but Replit exposes it via the same domain through port mapping.
        replit_domain = os.environ.get("REPLIT_DEV_DOMAIN")
        if not replit_domain:
            replit_domains_str = os.environ.get("REPLIT_DOMAINS", "")
            if replit_domains_str:
                replit_domain = replit_domains_str.split(",")[0].strip()
        if replit_domain:
            ws_url = f"wss://{replit_domain}:3001"
        else:
            # Fallback: localhost (for local development)
            ws_url = "ws://localhost:3001"
    
    # Ensure path starts with /
    if not path.startswith("/"):
        path = f"/{path}"
    
    # Build final URL
    full_url = f"{ws_url}{path}"
    
    # Add query parameters if provided
    if query_params:
        query_string = urlencode(query_params)
        full_url = f"{full_url}?{query_string}"
    
    return full_url
