"""Tests for _mcp_isolated_tool_call — the per-call MCP connection wrapper.

Covers the three isolation-critical scenarios:

1. Server-side transport close (child AnyIO scope fires) → fallback response,
   parent task stays alive, result_callback is invoked.
2. Parent pipeline cancellation → CancelledError propagated, result_callback
   is NOT invoked, child task is cancelled.
3. MCP startup or call_tool failure → exception caught, fallback returned,
   client.close() is always awaited.

Also covers the Universal Commerce Protocol (UCP) support added on top of
the isolated wrapper: detecting/stripping a `meta.ucp-agent.profile`
envelope from the LLM-facing schema, injecting it back in automatically at
call time, and unwrapping the real transport error (e.g. an HTTP status)
from the ExceptionGroup that `client.close()` raises after an aborted
request.
"""

import asyncio
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pipecat.adapters.schemas.function_schema import FunctionSchema

import botelier.voice.call_handler as _call_handler_module
from botelier.voice.call_handler import (
    _describe_mcp_transport_error,
    _detect_and_strip_ucp_meta,
    _mcp_isolated_tool_call,
)

# NOTE: `import ... as _call_handler_module` above captures a direct
# reference to the real module object at collection time. Some other test
# file (test_voice_webhook_authenticity.py) replaces
# sys.modules["botelier.voice.call_handler"] with a bare stub at *its own*
# module import time and never restores it, so later in a full-suite run
# `unittest.mock.patch("botelier.voice.call_handler.logger")` (a string
# path, re-resolved via sys.modules) would hit that stub and raise
# AttributeError. Patching the captured module object directly
# (`patch.object(_call_handler_module, "logger")`) is immune to that
# swap, since it's the same object `_mcp_isolated_tool_call`'s `__globals__`
# already points to.


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


# ---------------------------------------------------------------------------
# 7. close() raises CancelledError — real result must NOT be discarded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_cancellederror_does_not_discard_real_result():
    """Regression: Streamable-HTTP server closes the connection immediately
    after returning each tool response.  exit_stack.aclose() then hits the
    already-closed AnyIO transport and raises CancelledError.  Because
    CancelledError is a BaseException (not Exception), a bare
    `except Exception: pass` misses it and the exception overrides the
    computed return value.  The fix catches (Exception, CancelledError) so
    the real result survives."""
    params = _make_params("search_catalog", {"query": "protein"})

    mock_result = MagicMock()
    mock_result.content = [_make_content("Whey protein, 2 lb bag")]

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=mock_result)

    mock_client = MagicMock()
    mock_client.start = AsyncMock()
    # close() raises CancelledError — simulating AnyIO transport teardown
    # against an already-closed Streamable-HTTP connection.
    mock_client.close = AsyncMock(
        side_effect=asyncio.CancelledError("transport already closed")
    )
    mock_client._active_session = mock_session
    MockClass = MagicMock(return_value=mock_client)

    # Must not raise, and must return the *real* tool result, not the fallback.
    await _mcp_isolated_tool_call(params, server_params=object(), mcpc_class=MockClass)

    params.result_callback.assert_awaited_once_with("Whey protein, 2 lb bag")


# ---------------------------------------------------------------------------
# 8. UCP meta.ucp-agent.profile detection + schema stripping
# ---------------------------------------------------------------------------


def _ucp_schema(name: str = "search_catalog") -> FunctionSchema:
    """Build a FunctionSchema shaped like Shopify's UCP-compliant MCP tools:
    a required top-level `meta` object carrying `ucp-agent.profile`."""
    return FunctionSchema(
        name=name,
        description="Search the catalog",
        properties={
            "catalog": {"type": "object", "properties": {"query": {"type": "string"}}},
            "meta": {
                "type": "object",
                "properties": {
                    "ucp-agent": {
                        "type": "object",
                        "properties": {"profile": {"type": "string", "format": "uri"}},
                        "required": ["profile"],
                    }
                },
                "required": ["ucp-agent"],
            },
        },
        required=["catalog", "meta"],
    )


def test_detect_and_strip_ucp_meta_removes_meta_and_returns_true():
    """A UCP-shaped schema has `meta` stripped from both properties and
    required, and the function reports the tool needs profile injection."""
    schema = _ucp_schema()

    needs_injection = _detect_and_strip_ucp_meta(schema)

    assert needs_injection is True
    assert "meta" not in schema.properties
    assert "meta" not in schema.required
    # Unrelated properties must survive untouched.
    assert "catalog" in schema.properties


def test_detect_and_strip_ucp_meta_ignores_non_ucp_schema():
    """A plain tool schema with no `meta` property (or an unrelated `meta`
    shape) is left untouched and reported as not needing injection."""
    plain_schema = FunctionSchema(
        name="echo",
        description="Echo the input",
        properties={"text": {"type": "string"}},
        required=["text"],
    )

    assert _detect_and_strip_ucp_meta(plain_schema) is False
    assert plain_schema.properties == {"text": {"type": "string"}}
    assert plain_schema.required == ["text"]

    # A `meta` property that doesn't match the UCP ucp-agent.profile shape
    # must not be mistaken for one and must not be stripped.
    unrelated_meta_schema = FunctionSchema(
        name="log_event",
        description="Log a telemetry event",
        properties={"meta": {"type": "object", "properties": {"source": {"type": "string"}}}},
        required=[],
    )

    assert _detect_and_strip_ucp_meta(unrelated_meta_schema) is False
    assert "meta" in unrelated_meta_schema.properties


# ---------------------------------------------------------------------------
# 9. UCP meta injection at call time
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ucp_meta_injected_when_tool_needs_it():
    """When `ucp_meta` is supplied and the LLM's arguments don't already
    carry a `meta` key, it is merged in before call_tool is invoked — the
    LLM never has to (and cannot) supply a valid profile URI itself."""
    params = _make_params("search_catalog", {"catalog": {"query": "cookies"}})

    mock_result = MagicMock()
    mock_result.content = [_make_content("Chocolate chip cookies")]

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=mock_result)

    mock_client = MagicMock()
    mock_client.start = AsyncMock()
    mock_client.close = AsyncMock()
    mock_client._active_session = mock_session
    MockClass = MagicMock(return_value=mock_client)

    ucp_meta = {"ucp-agent": {"profile": "https://example.com/api/ucp/agent-profile.json"}}
    await _mcp_isolated_tool_call(
        params, server_params=object(), mcpc_class=MockClass, ucp_meta=ucp_meta
    )

    mock_session.call_tool.assert_awaited_once_with(
        "search_catalog",
        arguments={"catalog": {"query": "cookies"}, "meta": ucp_meta},
    )
    params.result_callback.assert_awaited_once_with("Chocolate chip cookies")


@pytest.mark.asyncio
async def test_ucp_meta_not_injected_for_non_ucp_tool():
    """Tools that don't need UCP profile negotiation (ucp_meta=None) get
    their arguments passed through unchanged."""
    params = _make_params("echo", {"text": "hello"})

    mock_result = MagicMock()
    mock_result.content = [_make_content("hello")]

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=mock_result)

    mock_client = MagicMock()
    mock_client.start = AsyncMock()
    mock_client.close = AsyncMock()
    mock_client._active_session = mock_session
    MockClass = MagicMock(return_value=mock_client)

    await _mcp_isolated_tool_call(
        params, server_params=object(), mcpc_class=MockClass, ucp_meta=None
    )

    mock_session.call_tool.assert_awaited_once_with("echo", arguments={"text": "hello"})


@pytest.mark.asyncio
async def test_ucp_meta_does_not_override_existing_meta_argument():
    """If arguments already carry a `meta` key (e.g. a future scenario where
    the model legitimately supplies one), auto-injection must not clobber
    it."""
    params = _make_params(
        "search_catalog", {"catalog": {"query": "cookies"}, "meta": {"custom": "value"}}
    )

    mock_result = MagicMock()
    mock_result.content = [_make_content("Chocolate chip cookies")]

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=mock_result)

    mock_client = MagicMock()
    mock_client.start = AsyncMock()
    mock_client.close = AsyncMock()
    mock_client._active_session = mock_session
    MockClass = MagicMock(return_value=mock_client)

    ucp_meta = {"ucp-agent": {"profile": "https://example.com/api/ucp/agent-profile.json"}}
    await _mcp_isolated_tool_call(
        params, server_params=object(), mcpc_class=MockClass, ucp_meta=ucp_meta
    )

    mock_session.call_tool.assert_awaited_once_with(
        "search_catalog",
        arguments={"catalog": {"query": "cookies"}, "meta": {"custom": "value"}},
    )


# ---------------------------------------------------------------------------
# 10. Real transport error extraction from a close()-time ExceptionGroup
# ---------------------------------------------------------------------------


def test_describe_mcp_transport_error_unwraps_http_status_error():
    """The mcp SDK's streamable-http transport raises HTTPStatusError inside
    a TaskGroup child task; client.close() re-raises it wrapped in one or
    more nested ExceptionGroups. The helper must find and describe it."""
    request = httpx.Request("POST", "https://merchant.example.com/api/ucp/mcp")
    response = httpx.Response(
        422,
        request=request,
        text='{"error":{"code":"profile_malformed"}}',
    )
    http_error = httpx.HTTPStatusError(
        "422 Unprocessable Entity", request=request, response=response
    )
    nested = BaseExceptionGroup("inner", [http_error])
    outer = BaseExceptionGroup("outer", [nested])

    detail = _describe_mcp_transport_error(outer)

    assert detail is not None
    assert "422" in detail
    assert "merchant.example.com" in detail
    assert "profile_malformed" in detail


def test_describe_mcp_transport_error_falls_back_to_first_exception():
    """When no HTTPStatusError is present anywhere in the (possibly nested)
    group, fall back to describing whatever exception was found first
    rather than returning nothing."""
    plain_error = RuntimeError("transport reset by peer")

    detail = _describe_mcp_transport_error(plain_error)

    assert detail == "RuntimeError: transport reset by peer"


@pytest.mark.asyncio
async def test_close_exceptiongroup_detail_is_logged_on_cancellation():
    """End-to-end: when close() raises a CancelledError-wrapping
    ExceptionGroup that contains the real HTTP failure, the cancellation
    log message includes that detail instead of the generic-only text."""
    params = _make_params("search_catalog", {"catalog": {"query": "cookies"}})

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(side_effect=asyncio.CancelledError("scope"))

    request = httpx.Request("POST", "https://merchant.example.com/api/ucp/mcp")
    response = httpx.Response(422, request=request, text="profile_malformed")
    http_error = httpx.HTTPStatusError("422", request=request, response=response)

    mock_client = MagicMock()
    mock_client.start = AsyncMock()
    mock_client.close = AsyncMock(side_effect=BaseExceptionGroup("close", [http_error]))
    mock_client._active_session = mock_session
    MockClass = MagicMock(return_value=mock_client)

    with patch.object(_call_handler_module, "logger") as mock_logger:
        await _mcp_isolated_tool_call(
            params, server_params=object(), mcpc_class=MockClass
        )

    params.result_callback.assert_awaited_once_with("Sorry, could not call the mcp tool")
    logged_messages = " ".join(str(c.args[0]) for c in mock_logger.error.call_args_list)
    assert "422" in logged_messages
    assert "merchant.example.com" in logged_messages
