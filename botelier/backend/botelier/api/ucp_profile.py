"""Public UCP (Universal Commerce Protocol) agent profile.

Declares the UCP capabilities Botelier's voice/SMS agents support when
calling UCP-shaped MCP tools (Shopify's Catalog/Cart/Checkout MCP servers,
and any other UCP-compliant commerce server). A merchant-side UCP server
fetches this document to negotiate which capabilities are available for a
given request — see the ``meta.ucp-agent.profile`` field that
``botelier/voice/call_handler.py`` injects automatically into every
UCP-shaped tool call (search_catalog, get_cart, create_checkout, etc.).

This endpoint is intentionally public and unauthenticated: UCP requires the
profile to be fetchable by the third-party commerce server without Botelier
credentials. It carries no account-specific or secret data — only a static
declaration of protocol version + capability names, so serving it without
auth is safe.

Reference: https://shopify.dev/docs/agents/profiles
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["ucp"])

# Bump alongside the capability list below if Botelier starts calling
# additional UCP tool families (e.g. fulfillment, discounts).
UCP_VERSION = "2026-08-25"

UCP_AGENT_PROFILE: dict = {
    "ucp": {
        "version": UCP_VERSION,
        "services": {
            "dev.ucp.shopping": [
                {
                    "version": UCP_VERSION,
                    "spec": f"https://ucp.dev/{UCP_VERSION}/specification/overview",
                    "transport": "mcp",
                    "schema": f"https://ucp.dev/{UCP_VERSION}/services/shopping/mcp.openrpc.json",
                }
            ]
        },
        "capabilities": {
            # Botelier's MCP tool set covers cart, checkout, order lookup,
            # and catalog search/lookup — declare exactly those capabilities.
            "dev.ucp.shopping.cart": [
                {
                    "version": UCP_VERSION,
                    "spec": f"https://ucp.dev/{UCP_VERSION}/specification/cart",
                    "schema": f"https://ucp.dev/{UCP_VERSION}/schemas/shopping/cart.json",
                }
            ],
            "dev.ucp.shopping.checkout": [
                {
                    "version": UCP_VERSION,
                }
            ],
            "dev.ucp.shopping.order": [
                {
                    "version": UCP_VERSION,
                    "spec": f"https://ucp.dev/{UCP_VERSION}/specification/order",
                    "schema": f"https://ucp.dev/{UCP_VERSION}/schemas/shopping/order.json",
                }
            ],
            "dev.ucp.shopping.catalog.search": [
                {
                    "version": UCP_VERSION,
                    "spec": f"https://ucp.dev/{UCP_VERSION}/specification/catalog/search",
                    "schema": f"https://ucp.dev/{UCP_VERSION}/schemas/shopping/catalog_search.json",
                }
            ],
            "dev.ucp.shopping.catalog.lookup": [
                {
                    "version": UCP_VERSION,
                    "spec": f"https://ucp.dev/{UCP_VERSION}/specification/catalog/lookup",
                    "schema": f"https://ucp.dev/{UCP_VERSION}/schemas/shopping/catalog_lookup.json",
                }
            ],
        },
        "payment_handlers": {},
    }
}


@router.get("/api/ucp/agent-profile.json", include_in_schema=False)
async def get_ucp_agent_profile() -> JSONResponse:
    """Serve Botelier's UCP agent profile for capability negotiation.

    Must be served as ``application/json`` with a valid ``Cache-Control``
    header — UCP-compliant merchant servers fetch, validate, and cache this
    document, and reject the calling agent's request with a
    ``profile_malformed`` error if the content type or cache directives
    don't meet their expectations.
    """
    return JSONResponse(
        content=UCP_AGENT_PROFILE,
        headers={"Cache-Control": "public, max-age=3600"},
    )
