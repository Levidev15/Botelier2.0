"""Regression tests for SSRF-safe HTTP request forwarding."""

import socket
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from botelier.services.ssrf_safe_transport import SSRFSafeTransport


class _StreamingBody(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'{"jsonrpc":"2.0"}'


@pytest.mark.asyncio
async def test_preserves_streaming_request_body_when_rewriting_destination():
    """MCP Streamable HTTP POSTs must not be buffered by the SSRF layer."""
    transport = SSRFSafeTransport()
    request = httpx.Request(
        "POST",
        "https://public.example/mcp",
        headers={"content-type": "application/json"},
        stream=_StreamingBody(),
    )
    forwarded = AsyncMock(
        return_value=httpx.Response(200, request=request)
    )

    with (
        patch(
            "botelier.services.ssrf_safe_transport.socket.getaddrinfo",
            return_value=[
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    6,
                    "",
                    ("93.184.216.34", 443),
                )
            ],
        ),
        patch.object(
            httpx.AsyncHTTPTransport,
            "handle_async_request",
            forwarded,
        ),
    ):
        await transport.handle_async_request(request)

    safe_request = forwarded.await_args.args[0]
    assert safe_request.url.host == "93.184.216.34"
    assert safe_request.headers["host"] == "public.example"
    assert safe_request.stream is request.stream