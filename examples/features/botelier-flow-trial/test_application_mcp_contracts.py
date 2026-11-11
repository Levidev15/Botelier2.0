"""Use actual discovery, JSON-RPC client/session, voice wrapper and native worker."""

import asyncio
import json

import pytest

from node_contract_io import (
    NARRATION, NodeCall, NodeProviders, flow_config, speech, tool_delta,
    wait_for_speech,
)
from test_application_transcripts import start_conversation


def test_enabled_mcp_tool_survives_a_flow_node_tool_refresh():
    """Refreshing current flow tools must not erase previously authorized MCP tools."""
    async def scenario():
        providers = NodeProviders([
            tool_delta("collect_query", {"query": "standard"}),
            tool_delta("collect_choice", {"choice": "standard"}, call_id="choice-call"),
            "Your fixture choice is noted.",
        ])
        async with NodeCall(config=flow_config(source="integration"), providers=providers, mcp=True) as call:
            await start_conversation(call)
            initial = call.created[4].tools.standard_tools
            assert {tool.name for tool in initial} == {"collect_query", "mcp_lookup"}
            assert len([tool for tool in initial if tool.name == "collect_query"]) == 1
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, NARRATION)
            await providers.user_turn("Check the fixture using the connected tool.", turn_index=1)
            await wait_for_speech(call, "Your fixture choice is noted.")
            requests = [body for body in providers.requests if body.get("stream")]
            names = {tool["function"]["name"] for tool in requests[1]["tools"]}
            assert names == {"collect_choice", "mcp_lookup"}
            assert call.executor.state.collected_slots["choice"] == "standard"
            assert "mcp_disabled" not in names
            assert not any(message.get("method") == "tools/call"
                           for message in providers.mcp_messages)
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_mcp_structured_result_and_error_status_survive_the_tool_boundary():
    """Flattening MCP structuredContent or isError must fail the actual wire check."""
    async def scenario():
        providers = NodeProviders([
            tool_delta("mcp_lookup", {"query": "standard"}),
            "I could not complete the fixture lookup.",
        ], mcp_result={
            "content": [{"type": "text", "text": "fixture-error-detail"}],
            "structuredContent": {"status": "unavailable", "count": 0},
            "isError": True,
        })
        async with NodeCall(providers=providers, mcp=True) as call:
            await start_conversation(call)
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, "I could not complete the fixture lookup.")
            requests = [body for body in providers.requests if body.get("stream")]
            message = next(message for message in requests[1]["messages"]
                           if message.get("role") == "tool")
            result = json.loads(message["content"])
            assert result == {
                "content": [{"type": "text", "text": "fixture-error-detail"}],
                "structuredContent": {"status": "unavailable", "count": 0},
                "isError": True,
            }
            assert "fixture-error-detail" not in " ".join(speech(call))
            assert "unavailable" not in " ".join(speech(call))
            assert call.executor.state.current_node_id == "query"
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("result,expected", [
    (
        {"content": [], "structuredContent": {"available": False, "count": 0}, "isError": False},
        {"content": [], "structuredContent": {"available": False, "count": 0}, "isError": False},
    ),
    (
        {"content": [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}],
         "isError": False},
        "firstsecond",
    ),
    (
        {"content": [], "isError": True},
        {"content": [], "isError": True},
    ),
])
def test_mcp_success_and_error_shapes_remain_intact_without_direct_speech(result, expected):
    """Preserve structured-only data and zero/false, plus legacy text concatenation."""
    async def scenario():
        providers = NodeProviders([
            tool_delta("mcp_lookup", {"query": "standard"}),
            "I have the fixture tool response.",
        ], mcp_result=result)
        async with NodeCall(providers=providers, mcp=True) as call:
            await start_conversation(call)
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, "I have the fixture tool response.")
            requests = [body for body in providers.requests if body.get("stream")]
            wire = next(message for message in requests[1]["messages"]
                        if message.get("role") == "tool")
            assert json.loads(wire["content"]) == expected
            assert speech(call)[1:] == ["I have the fixture tool response."]
            assert len([message for message in providers.mcp_messages
                        if message.get("method") == "tools/call"]) == 1
            assert call.executor.state.current_node_id == "query"
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_hangup_cancels_a_pending_mcp_request_without_a_retry_or_late_result():
    async def scenario():
        providers = NodeProviders([
            tool_delta("mcp_lookup", {"query": "standard"}),
        ], mcp_fault="hold")
        async with NodeCall(providers=providers, mcp=True) as call:
            await start_conversation(call)
            await providers.user_turn("Please check the standard fixture.")
            await call.wait_until(providers.mcp_started.is_set)
            await call.finish("caller_hangup")
            assert providers.mcp_cancelled
            assert not providers.release_mcp.is_set()
            assert speech(call)[1:] == []
            assert len([message for message in providers.mcp_messages
                        if message.get("method") == "tools/call"]) == 1
            assert sum(bool(body.get("stream")) for body in providers.requests) == 1
            call.assert_clean()
    asyncio.run(scenario())


def test_disabled_mcp_function_cannot_reach_the_connected_server():
    async def scenario():
        providers = NodeProviders([
            tool_delta("mcp_disabled", {"query": "standard"}),
            "Please choose an available fixture action.",
        ])
        async with NodeCall(providers=providers, mcp=True) as call:
            await start_conversation(call)
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, "Please choose an available fixture action.")
            assert not any(message.get("method") == "tools/call"
                           for message in providers.mcp_messages)
            assert call.executor.state.current_node_id == "query"
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_mcp_transport_timeout_returns_once_and_keeps_the_call_usable():
    async def scenario():
        providers = NodeProviders([
            tool_delta("mcp_lookup", {"query": "standard"}),
            "The fixture tool could not be reached.",
        ], mcp_fault="timeout")
        async with NodeCall(providers=providers, mcp=True) as call:
            await start_conversation(call)
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, "The fixture tool could not be reached.")
            requests = [body for body in providers.requests if body.get("stream")]
            wire = next(message for message in requests[1]["messages"]
                        if message.get("role") == "tool")
            assert json.loads(wire["content"]) == "Sorry, could not call the mcp tool"
            assert speech(call)[1:] == ["The fixture tool could not be reached."]
            assert len([message for message in providers.mcp_messages
                        if message.get("method") == "tools/call"]) == 1
            await call.finish("graceful_end")
            call.assert_clean(expected_errors=(
                r"MCP tool 'mcp_lookup' isolated call cancelled "
                r"\(server-side transport close: ExceptionGroup: unhandled errors "
                r"in a TaskGroup \(1 sub-exception\)\); returning fallback",
            ))
    asyncio.run(scenario())
