"""Domain configuration utilities for Botelier.

Provides helpers to reliably get the public base URL for webhook callbacks
and WebSocket connections in both development (Replit) and production environments.
"""

import os
from typing import Optional


def get_frontend_url() -> str:
    """Get the URL of the frontend dashboard application.

    Used by the OAuth2 callback hop so the API server can 302 the browser
    to the dashboard's /dashboard/integrations/oauth/complete page, where the
    user's authenticated session completes the exchange.

    Priority:
    1. FRONTEND_URL — set this in deployments where the API and dashboard run
       on separate hosts (e.g. PUBLIC_BASE_URL=https://api.botelier.com,
       FRONTEND_URL=https://app.botelier.com).
    2. get_public_base_url() — used automatically in single-host deployments
       (Replit dev, Replit prod without a custom API domain) where the API and
       dashboard share the same origin.

    The value must NOT come from request headers or OAuth state — it is
    trust-anchored in server configuration only.
    """
    frontend_url = os.environ.get("FRONTEND_URL", "").strip().rstrip("/")
    if frontend_url:
        if not frontend_url.startswith(("http://", "https://")):
            frontend_url = f"https://{frontend_url}"
        return frontend_url
    return get_public_base_url()


def get_public_base_url(fallback_host: Optional[str] = None) -> str:
    """Get the public base URL for this application.

    This is used for Twilio webhooks, WebSocket URLs, and other callbacks
    that need to reach this server from external services.

    Priority order:
    1. PUBLIC_BASE_URL - Explicitly configured for production (with custom domains)
    2. REPLIT_DOMAINS - Replit production domain (auto-injected by Replit)
    3. REPLIT_DEV_DOMAIN - Automatic Replit development domain (with port from Host header)
    4. fallback_host - Optional Host header from incoming request (preserves port)
    5. localhost - Last resort (will not work for external webhooks)

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

    # Priority 2: Replit domain — production (REPLIT_DOMAINS) takes priority over
    # dev (REPLIT_DEV_DOMAIN). Replit injects REPLIT_DEV_DOMAIN into both dev and
    # production VM environments, so we must check REPLIT_DOMAINS first.
    # Production: REPLIT_DOMAINS = "my-app.replit.app,my-app.username.repl.co"
    replit_domains_str = os.environ.get("REPLIT_DOMAINS", "")
    if replit_domains_str:
        production_domain = replit_domains_str.split(",")[0].strip()
        # Production traffic arrives on standard HTTPS port 443 — no port suffix needed.
        return f"https://{production_domain}"

    # Dev: REPLIT_DEV_DOMAIN is the workspace URL (may need port from Host header).
    replit_dev_domain = os.environ.get("REPLIT_DEV_DOMAIN")
    if replit_dev_domain:
        # In dev environments, include the port from the Host header if non-standard
        if fallback_host and ":" in fallback_host:
            port = fallback_host.split(":", 1)[1]
            # Only append port if it's not 443 (standard HTTPS)
            if port and port != "443":
                return f"https://{replit_dev_domain}:{port}"
        return f"https://{replit_dev_domain}"

    # Priority 3: Fallback host from request (preserve port for non-standard ports)
    if fallback_host:
        # Keep the full host including port (e.g., "localhost:5000")
        # This is critical for dev environments where backend runs on non-standard ports
        return f"https://{fallback_host}"

    # Priority 4: localhost (won't work for external webhooks!)
    return "https://localhost"


def get_voice_webhook_base_url() -> str:
    """Get the base URL to use for Twilio voice webhook configuration.

    Separate from get_public_base_url() so the dashboard backend (Replit) can
    point newly-purchased numbers at the dedicated voice backend (ACA) without
    routing its own HTTP traffic there.

    Priority order:
    1. VOICE_WEBHOOK_BASE_URL — explicit override (set on Replit prod to the ACA URL)
    2. get_public_base_url()  — falls back to the current server's public URL

    Usage: set VOICE_WEBHOOK_BASE_URL=https://botelier-voice.lemonbay-80908dd7.eastus.azurecontainerapps.io
    on the Replit production environment so purchased numbers always route to ACA.
    On ACA itself this env var is not needed — PUBLIC_BASE_URL already covers it.
    """
    voice_url = os.environ.get("VOICE_WEBHOOK_BASE_URL")
    if voice_url:
        if not voice_url.startswith(("http://", "https://")):
            voice_url = f"https://{voice_url}"
        return voice_url.rstrip("/")
    return get_public_base_url()


def get_websocket_url(
    path: str = "/api/ws/call",
    fallback_host: Optional[str] = None,
    query_params: Optional[dict] = None,
) -> str:
    """Get the WebSocket URL for Twilio Media Streams.

    Architecture:
    - HTTP API calls (dashboard): Frontend (5000) → Next.js proxy → Backend (3001)
    - WebSocket calls (Twilio): Twilio → Backend (3001) DIRECTLY (no proxy)

    This connects directly to the FastAPI backend on port 3001, bypassing the Next.js
    frontend entirely. This is the standard Pipecat pattern and avoids proxy issues.

    Priority order:
    1. BACKEND_WS_URL - Explicit WebSocket URL (overrides everything)
    2. PUBLIC_BASE_URL - Derived: https://domain → wss://domain (Azure / custom-domain envs)
    3. REPLIT_DOMAINS - Replit production proxy (no :3001, proxied through port 443)
    4. REPLIT_DEV_DOMAIN - Replit dev direct to :3001
    5. ws://localhost:3001 - Local fallback only

    Args:
        path: WebSocket endpoint path (default: "/api/ws/call")
        fallback_host: Optional host from request headers (unused, kept for compatibility)
        query_params: Optional dict of query parameters to append

    Returns:
        WebSocket URL pointing to the backend

    Examples:
        >>> # Replit dev - direct to backend
        >>> os.environ["REPLIT_DEV_DOMAIN"] = "abc123.repl.dev"
        >>> get_websocket_url()
        "wss://abc123.repl.dev:3001/api/ws/call"

        >>> # Azure / custom domain — derived from PUBLIC_BASE_URL
        >>> os.environ["PUBLIC_BASE_URL"] = "https://voice.botelier.ai"
        >>> get_websocket_url()
        "wss://voice.botelier.ai/api/ws/call"

        >>> # Explicit override
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

    # Priority 2: Derive WebSocket URL from PUBLIC_BASE_URL by converting
    # https:// → wss://. This allows Azure Container Apps (and any environment
    # that only sets PUBLIC_BASE_URL) to self-route correctly without also
    # requiring a separate BACKEND_WS_URL env var.
    elif os.environ.get("PUBLIC_BASE_URL"):
        base = os.environ["PUBLIC_BASE_URL"].rstrip("/")
        if base.startswith("https://"):
            ws_url = "wss://" + base[len("https://"):]
        elif base.startswith("http://"):
            ws_url = "ws://" + base[len("http://"):]
        else:
            ws_url = f"wss://{base}"

    else:
        # Priority 3: Replit domain — production (REPLIT_DOMAINS) before dev (REPLIT_DEV_DOMAIN).
        # Replit injects REPLIT_DEV_DOMAIN into both environments, so check REPLIT_DOMAINS first.
        #
        # Production: WebSocket traffic arrives at port 443 via the Node.js server (port 5000)
        # which proxies /api/ws/* to the backend on localhost:3001. No explicit port needed.
        #
        # Dev: Backend port 3001 is directly reachable via Replit's dev proxy, so we include :3001.
        replit_domains_str = os.environ.get("REPLIT_DOMAINS", "")
        if replit_domains_str:
            production_domain = replit_domains_str.split(",")[0].strip()
            ws_url = f"wss://{production_domain}"  # No :3001 — proxied through port 443
        else:
            replit_dev_domain = os.environ.get("REPLIT_DEV_DOMAIN")
            if replit_dev_domain:
                ws_url = f"wss://{replit_dev_domain}:3001"  # Direct backend access in dev
            else:
                # Fallback: localhost (for local development outside Replit)
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
