"""The actual filtered MCP catalogue/protocol must survive native transitions."""

import asyncio
import json

import pytest

from node_contract_io import PRESENTATION, speech, tool_delta, tool_result, wait_for_speech
from pilot_io import (
    REVISION_COLLISION, PilotCall, PilotProviders, logical_function_name, native_tool_names,
)


@pytest.mark.parametrize("is_error,spoken", [
    (False, "The connected fixture was found."),
    (True, "The connected fixture was unavailable."),
])
def test_host_mcp_lookup_survives_the_transition_without_promoting_structured_data(
    is_error, spoken,
):
    async def scenario():
        payload = {
            "content": [{"type": "text", "text": "private-MCP-payload-marker"}],
            "structuredContent": {"available": False, "count": 0},
            "isError": is_error,
        }
        providers = PilotProviders([
            tool_delta("collect_query", {"query": "standard"}),
            tool_delta("mcp_lookup", {"query": "standard"}, call_id="mcp-call"),
            spoken,
        ], mcp_result=payload)
        async with PilotCall(providers=providers, mcp=True) as call:
            await call.activate()
            assert native_tool_names(call) == {
                "collect_query", "mcp_lookup",
            }
            assert {schema.name for schema in call.host_schemas} == {
                "collect_query", "collect_choice", "collect_failure", "mcp_lookup",
                REVISION_COLLISION,
            }
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, PRESENTATION)
            await call.wait_for_node("choice")
            assert native_tool_names(call) == {
                "collect_choice", "mcp_lookup",
            }
            assert not any(message["method"] == "tools/call" for message in providers.mcp_messages)
            await providers.user_turn("Check the connected fixture tool.", turn_index=1)
            await wait_for_speech(call, spoken)
            assert tool_result(call, "mcp-call") == payload
            requests = [body for body in providers.requests if body.get("stream")]
            assert len(requests) == 3
            assert {logical_function_name(tool["function"]["name"]) for tool in requests[1]["tools"]} == {
                "collect_choice", "mcp_lookup",
            }
            wire = next(
                message for message in requests[2]["messages"]
                if message.get("role") == "tool" and message.get("tool_call_id") == "mcp-call"
            )
            assert json.loads(wire["content"]) == payload
            assert all(
                "private-MCP-payload-marker" not in message.get("content", "")
                for message in requests[2]["messages"]
                if message.get("role") in {"system", "developer"}
            )
            assert "private-MCP-payload-marker" not in " ".join(speech(call))
            assert call.adapter.manager.current_node == "choice"
            assert len(providers.business_requests) == 1
            assert len([message for message in providers.mcp_messages
                        if message["method"] == "tools/call"]) == 1
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("name", ["mcp_disabled", "collect_choice", "collect_failure", REVISION_COLLISION])
def test_disabled_and_future_colliding_names_have_no_mcp_dispatch_path(name):
    async def scenario():
        providers = PilotProviders([
            tool_delta(name, {"query": "standard"}), "Please answer the current question.",
        ])
        async with PilotCall(providers=providers, mcp=True) as call:
            await call.activate()
            await providers.user_turn("Please check a fixture.")
            await wait_for_speech(call, "Please answer the current question.")
            assert call.adapter.manager.current_node == "query"
            assert call.adapter.facts == {}
            assert providers.business_requests == []
            assert not any(message["method"] == "tools/call" for message in providers.mcp_messages)
            assert native_tool_names(call) == {
                "collect_query", "mcp_lookup",
            }
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_spent_native_tool_is_not_resurrected_as_an_enabled_mcp_collision():
    async def scenario():
        providers = PilotProviders([
            tool_delta("collect_query", {"query": "standard"}),
            tool_delta("collect_query", {"query": "other"}, call_id="spent-call"),
            "Please choose one of the options.",
        ])
        async with PilotCall(providers=providers, mcp=True) as call:
            await call.activate()
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, PRESENTATION)
            await call.wait_for_node("choice")
            await providers.user_turn("Check another fixture.", turn_index=1)
            await wait_for_speech(call, "Please choose one of the options.")
            assert call.adapter.manager.current_node == "choice"
            assert call.adapter.facts["query"] == "standard"
            assert len(providers.business_requests) == 1
            assert not any(message["method"] == "tools/call" for message in providers.mcp_messages)
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())
