"""Tests for _mcp_isolated_tool_call — the per-call MCP connection wrapper.

Covers the three isolation-critical scenarios:

1. Server-side transport close (child AnyIO scope fires) → fallback response,
   parent task stays alive, result_callback is invoked.
2. Parent pipeline cancellation → CancelledError propagated, result_callback
   is NOT invoked, child task is cancelled.
3. MCP startup or call_tool failure → exception caught, fallback returned,
   client.close() is always awaited.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from botelier.voice.call_handler import _mcp_isolated_tool_call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_params(fn_name: str = "search_catalog", args: dict | None = None):
    """Build a minimal FunctionCallParams-like mock."""
    cb = AsyncMock()
    params = MagicMock()
    params.function_name = fn_name
    params.arguments = args or {}
    params.result_callback = cb
    return params


def _make_content(text: str):
    chunk = MagicMock()
    chunk.text = text
    return chunk


# ---------------------------------------------------------------------------
# 1. Successful tool call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_call_invokes_result_callback():
    """Happy path: client returns text content → result_callback called with it."""
    params = _make_params("search_catalog", {"query": "snacks"})

    mock_result = MagicMock()
    mock_result.content = [_make_content("Protein bars, whey powder")]

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=mock_result)

    mock_client = MagicMock()
    mock_client.start = AsyncMock()
    mock_client.close = AsyncMock()
    mock_client._active_session = mock_session

    MockClass = MagicMock(return_value=mock_client)

    await _mcp_isolated_tool_call(params, server_params=object(), mcpc_class=MockClass)

    params.result_callback.assert_awaited_once_with("Protein bars, whey powder")
    mock_client.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# 2. Server-side transport close (child CancelledError, parent alive)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_child_transport_close_returns_fallback_and_parent_stays_alive():
    """When the isolated task is cancelled by its own AnyIO scope (server-side
    transport teardown), the parent continues: result_callback is called with
    the fallback string and no CancelledError escapes."""
    params = _make_params("search_catalog")

    async def _start_and_cancel(self_ignored=None):
        raise asyncio.CancelledError("AnyIO cancel scope teardown")

    mock_client = MagicMock()
    mock_client.start = AsyncMock(side_effect=asyncio.CancelledError("transport close"))
    mock_client.close = AsyncMock()
    MockClass = MagicMock(return_value=mock_client)

    # Must not raise — the parent is not being cancelled.
    await _mcp_isolated_tool_call(params, server_params=object(), mcpc_class=MockClass)

    params.result_callback.assert_awaited_once_with("Sorry, could not call the mcp tool")


@pytest.mark.asyncio
async def test_child_call_tool_cancelled_returns_fallback():
    """CancelledError from call_tool (not start) is also treated as server-side
    transport close when the parent has no pending cancellation."""
    params = _make_params("get_cart")

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(side_effect=asyncio.CancelledError("transport"))

    mock_client = MagicMock()
    mock_client.start = AsyncMock()
    mock_client.close = AsyncMock()
    mock_client._active_session = mock_session

    MockClass = MagicMock(return_value=mock_client)

    await _mcp_isolated_tool_call(params, server_params=object(), mcpc_class=MockClass)

    params.result_callback.assert_awaited_once_with("Sorry, could not call the mcp tool")
    # close() must still be called (finally block in _isolated)
    mock_client.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# 3. Parent pipeline cancellation propagates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parent_cancellation_propagates_and_skips_result_callback():
    """When the *parent* task is cancelled (Pipecat teardown), CancelledError
    must propagate out of _mcp_isolated_tool_call; result_callback must NOT
    be invoked."""
    params = _make_params("search_catalog")

    # slow_call simulates an MCP call that is still in flight when the parent
    # task receives a cancellation from outside.
    call_started = asyncio.Event()

    async def slow_call(*_args, **_kwargs):
        call_started.set()
        await asyncio.sleep(10)  # blocks until cancelled

    mock_session = AsyncMock()
    mock_session.call_tool = slow_call

    mock_client = MagicMock()
    mock_client.start = AsyncMock()
    mock_client.close = AsyncMock()
    mock_client._active_session = mock_session
    MockClass = MagicMock(return_value=mock_client)

    async def _run():
        await _mcp_isolated_tool_call(
            params, server_params=object(), mcpc_class=MockClass
        )

    task = asyncio.create_task(_run())
    # Wait until the MCP call has started, then cancel the parent task.
    await call_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    params.result_callback.assert_not_awaited()


# ---------------------------------------------------------------------------
# 4. Startup failure (non-cancel exception)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_startup_failure_returns_fallback():
    """If client.start() raises a non-cancel exception (e.g. network error),
    the fallback is returned and result_callback is called."""
    params = _make_params("update_cart")

    mock_client = MagicMock()
    mock_client.start = AsyncMock(side_effect=ConnectionError("DNS failure"))
    mock_client.close = AsyncMock()
    MockClass = MagicMock(return_value=mock_client)

    await _mcp_isolated_tool_call(params, server_params=object(), mcpc_class=MockClass)

    params.result_callback.assert_awaited_once_with("Sorry, could not call the mcp tool")


# ---------------------------------------------------------------------------
# 5. call_tool failure (non-cancel exception)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_tool_failure_returns_fallback_and_closes_client():
    """If call_tool raises a non-cancel exception, the fallback is returned
    and client.close() is still called (finally block in _isolated)."""
    params = _make_params("get_product")

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(side_effect=RuntimeError("server error"))

    mock_client = MagicMock()
    mock_client.start = AsyncMock()
    mock_client.close = AsyncMock()
    mock_client._active_session = mock_session
    MockClass = MagicMock(return_value=mock_client)

    await _mcp_isolated_tool_call(params, server_params=object(), mcpc_class=MockClass)

    params.result_callback.assert_awaited_once_with("Sorry, could not call the mcp tool")
    mock_client.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# 6. Empty content falls back to fallback string
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_content_returns_fallback():
    """If the MCP server returns a result with no text content, the fallback
    string is used (not an empty string that confuses the LLM)."""
    params = _make_params("search_catalog")

    mock_result = MagicMock()
    mock_result.content = []  # empty

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=mock_result)

    mock_client = MagicMock()
    mock_client.start = AsyncMock()
    mock_client.close = AsyncMock()
    mock_client._active_session = mock_session
    MockClass = MagicMock(return_value=mock_client)

    await _mcp_isolated_tool_call(params, server_params=object(), mcpc_class=MockClass)

    params.result_callback.assert_awaited_once_with("Sorry, could not call the mcp tool")
