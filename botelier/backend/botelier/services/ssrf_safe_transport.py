"""
SSRF-Safe HTTP Transport.

Provides an httpx.AsyncHTTPTransport subclass that prevents Server-Side
Request Forgery (SSRF) by resolving the destination hostname once at
request time, validating every resolved IP address against private,
loopback, link-local and reserved ranges, and then rewriting the
request URL to the validated IP so that httpcore never performs a second
DNS resolution (eliminating the TOCTOU DNS-rebinding window).

For HTTPS connections the original hostname is preserved via the
``sni_hostname`` request extension, which httpcore 1.x uses for the TLS
handshake and certificate verification, so certificate checks remain
fully intact.

Usage in httpx::

    transport = SSRFSafeTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await client.get("https://example.com/api")

Usage as an MCP httpx_client_factory::

    client_factory = make_ssrf_safe_mcp_client_factory()
    async with sse_client(url, httpx_client_factory=client_factory) as streams:
        ...
"""

import asyncio
import ipaddress
import socket
from typing import Optional

import httpx

_BLOCKED_LITERAL_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "metadata.google.internal",
    "169.254.169.254",
}


class SSRFSafeTransport(httpx.AsyncHTTPTransport):
    """
    SSRF-safe async transport.

    Resolves the hostname **once** inside handle_async_request, validates
    every resolved IP against private/loopback/link-local/reserved ranges,
    then rewrites the request URL to use the validated IP so that httpcore
    never issues a second DNS lookup (eliminating the TOCTOU DNS-rebinding
    window).  For HTTPS the original hostname is passed via the
    ``sni_hostname`` extension so TLS SNI and certificate verification use
    the correct hostname.
    """

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        hostname = request.url.host
        port = request.url.port or (443 if request.url.scheme == "https" else 80)

        if hostname in _BLOCKED_LITERAL_HOSTS:
            raise httpx.ConnectError(
                f"Blocked: requests to internal address {hostname!r} are not allowed",
                request=request,
            )

        loop = asyncio.get_event_loop()
        try:
            results: list = await loop.run_in_executor(
                None,
                lambda: socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM),
            )
        except socket.gaierror:
            raise httpx.ConnectError(
                f"Unable to resolve hostname: {hostname}", request=request
            )

        safe_ip: Optional[str] = None
        for _, _, _, _, sockaddr in results:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise httpx.ConnectError(
                    f"Blocked: private/internal address for {hostname}: {ip}",
                    request=request,
                )
            if safe_ip is None:
                safe_ip = sockaddr[0]

        if safe_ip is None:
            raise httpx.ConnectError(
                f"No valid public address found for {hostname}", request=request
            )

        safe_url = request.url.copy_with(host=safe_ip)

        headers = dict(request.headers)
        if "host" not in {k.lower() for k in headers}:
            headers["host"] = hostname

        extensions = dict(request.extensions)
        extensions["sni_hostname"] = hostname.encode("ascii")

        safe_request = httpx.Request(
            method=request.method,
            url=safe_url,
            headers=headers,
            content=request.content,
            extensions=extensions,
        )

        return await super().handle_async_request(safe_request)


def make_ssrf_safe_mcp_client_factory():
    """
    Return an MCP-compatible httpx_client_factory that injects the
    SSRFSafeTransport into every httpx.AsyncClient created by the MCP
    SSE transport, preventing DNS-rebinding SSRF on MCP connections.
    """
    import httpx as _httpx

    def _factory(
        headers=None,
        timeout=None,
        auth=None,
    ) -> _httpx.AsyncClient:
        kwargs = {"follow_redirects": True, "transport": SSRFSafeTransport()}
        if timeout is None:
            kwargs["timeout"] = _httpx.Timeout(30.0, read=300.0)
        else:
            kwargs["timeout"] = timeout
        if headers is not None:
            kwargs["headers"] = headers
        if auth is not None:
            kwargs["auth"] = auth
        return _httpx.AsyncClient(**kwargs)

    return _factory
