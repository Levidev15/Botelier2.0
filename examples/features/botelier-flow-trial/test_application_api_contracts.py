"""Drive STT -> real model tool parsing -> API action -> mapped state -> TTS."""

import asyncio

import pytest

from node_contract_io import (
    BRIDGE, ERROR, NARRATION, PRESENTATION, PRIVATE, WAIT,
    NodeCall, NodeProviders, flow_config, speech, tool_delta, tool_result,
    wait_for_speech, wait_for_tool_result,
)
from test_application_transcripts import start_conversation


@pytest.mark.parametrize("source", ["custom", "integration"])
def test_api_jsonpath_mapping_preserves_arrays_and_zero_for_direct_narration(source):
    """Breaking extraction, slot propagation or mapper narration fails on real speech."""
    async def scenario():
        providers = NodeProviders([tool_delta("collect_query", {"query": "standard"})])
        async with NodeCall(config=flow_config(source=source), providers=providers) as call:
            await start_conversation(call)
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_tool_result(call)
            assert call.executor.state.collected_slots["rooms"] == [
                {"name": "Standard", "price": 0},
            ]
            assert call.executor.state.collected_slots["price"] == 0
            await wait_for_speech(call, NARRATION)
            assert call.executor.state.current_node_id == "choice"
            assert len(providers.business_requests) == 1
            assert str(providers.business_requests[0].url) == (
                "https://api.fixture.invalid/search?query=standard"
            )
            assert speech(call)[1:] == [WAIT, NARRATION]
            assert PRIVATE not in " ".join(speech(call))
            assert tool_result(call)["current_node_id"] == "choice"
            assert "thinking_message" not in tool_result(call)
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_response_presentation_owns_speech_without_a_second_narration_or_bridge():
    """An API_RESPONSE must not be followed by the API node's duplicate narration."""
    async def scenario():
        providers = NodeProviders([tool_delta("collect_query", {"query": "standard"})])
        async with NodeCall(config=flow_config(presentation=True), providers=providers) as call:
            await start_conversation(call)
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, PRESENTATION)
            await call.wait_until(lambda: not call.created[16].get_audio_contexts())
            assert speech(call)[1:] == [WAIT, PRESENTATION]
            result = tool_result(call)
            assert result["result"] == PRESENTATION
            assert result["current_node_id"] == "choice"
            assert "Private next-node guidance" in result["current_node_context"]
            assert sum(bool(request.get("stream")) for request in providers.requests) == 1
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_raw_result_digest_reaches_model_context_but_not_direct_speech():
    """A raw field digest cannot become a TTSSpeakFrame or suppress model narration."""
    async def scenario():
        providers = NodeProviders([
            tool_delta("collect_query", {"query": "standard"}),
            "The standard fixture is available at no cost.",
        ])
        async with NodeCall(config=flow_config(narration=False), providers=providers) as call:
            await start_conversation(call)
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, "The standard fixture is available at no cost.")
            requests = [body for body in providers.requests if body.get("stream")]
            assert len(requests) == 2
            wire_result = next(message for message in requests[1]["messages"]
                               if message.get("role") == "tool")
            assert "price" in wire_result["content"].casefold()
            assert "Standard" in wire_result["content"]
            assert speech(call)[1:] == [
                WAIT, BRIDGE, "The standard fixture is available at no cost.",
            ]
            assert "Extracted data" not in " ".join(speech(call))
            assert "voice_result_is_auto_summary" not in wire_result["content"]
            names = {tool["function"]["name"] for tool in requests[1]["tools"]}
            assert names == {"collect_choice"}
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("source", ["custom", "integration"])
@pytest.mark.parametrize("status", [403, 422, 503])
def test_failed_api_routes_to_failure_without_reading_raw_provider_error(source, status):
    """HTTP success must not be invented and the failed node must not remain current."""
    async def scenario():
        providers = NodeProviders([
            tool_delta("collect_query", {"query": "standard"}),
            "Would you like to try another fixture?",
        ], status=status, payload={"message": "internal-provider-detail-marker"})
        async with NodeCall(config=flow_config(source=source), providers=providers) as call:
            await start_conversation(call)
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, "Would you like to try another fixture?")
            assert call.executor.state.current_node_id == "failure"
            assert tool_result(call)["success"] is False
            assert tool_result(call)["status_code"] == status
            assert len(providers.business_requests) == 1
            assert speech(call)[1:] == [WAIT, ERROR, "Would you like to try another fixture?"]
            assert "internal-provider-detail-marker" not in " ".join(speech(call))
            assert "rooms" not in call.executor.state.collected_slots
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_empty_presentation_uses_no_results_branch_without_a_success_narration():
    async def scenario():
        providers = NodeProviders([
            tool_delta("collect_query", {"query": "standard"}),
        ], payload={"rooms": []})
        async with NodeCall(config=flow_config(presentation=True), providers=providers) as call:
            await start_conversation(call)
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, "No fixture options were found.")
            assert call.executor.state.collected_slots["rooms"] == []
            assert call.executor.state.current_node_id == "failure"
            assert tool_result(call)["current_node_id"] == "failure"
            assert speech(call)[1:] == [WAIT, "No fixture options were found."]
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("source", ["custom", "integration"])
@pytest.mark.parametrize("method,expected_requests", [("GET", 3), ("POST", 1)])
def test_transport_timeout_retries_reads_but_never_reissues_an_uncertain_write(
    source, method, expected_requests,
):
    """An integration's internal retry loop cannot bypass the flow's write guard."""
    async def scenario():
        config = flow_config(source=source, method=method)
        next(node["data"]["api"] for node in config["nodes"]
             if node["type"] == "api_request")["retryCount"] = 2
        providers = NodeProviders([
            tool_delta("collect_query", {"query": "standard"}),
            "The fixture could not be checked.",
        ], status="timeout")
        async with NodeCall(config=config, providers=providers) as call:
            await start_conversation(call)
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, "The fixture could not be checked.")
            assert len(providers.business_requests) == expected_requests
            assert tool_result(call)["success"] is False
            assert call.executor.state.current_node_id == "failure"
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_stale_api_tool_does_not_repeat_wait_or_failure_announcements():
    """A rejected stale tool call is not a new API request or an API outage."""
    async def scenario():
        providers = NodeProviders([
            tool_delta("collect_query", {"query": "standard"}),
            tool_delta("execute_lookup", call_id="stale-call"),
            "Please choose an option.",
        ])
        async with NodeCall(providers=providers) as call:
            await start_conversation(call)
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, NARRATION)
            await providers.user_turn("What should I choose?", turn_index=1)
            await wait_for_speech(call, "Please choose an option.")
            assert tool_result(call, "stale-call")["out_of_order"] is True
            assert call.executor.state.current_node_id == "choice"
            assert len(providers.business_requests) == 1
            assert speech(call)[1:] == [WAIT, NARRATION, "Please choose an option."]
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_model_cannot_replace_the_configured_api_destination_or_method():
    """Treat extra model arguments as untrusted, not as transport configuration."""
    async def scenario():
        providers = NodeProviders([tool_delta("execute_lookup", {
            "url": "https://unapproved.fixture.invalid/write", "method": "POST",
        })])
        async with NodeCall(providers=providers) as call:
            call.executor.state.advance_to("lookup")
            call.executor.state.set_variable("query", "standard")
            call.mapper.update_llm_tools_for_flow("fixture")
            await start_conversation(call)
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, NARRATION)
            assert len(providers.business_requests) == 1
            assert providers.business_requests[0].method == "GET"
            assert str(providers.business_requests[0].url) == (
                "https://api.fixture.invalid/search?query=standard"
            )
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("source", ["custom", "integration"])
def test_hangup_cancels_pending_api_io_without_speaking_or_advancing_late(source):
    async def scenario():
        providers = NodeProviders([
            tool_delta("collect_query", {"query": "standard"}),
        ], status="hold")
        async with NodeCall(config=flow_config(source=source), providers=providers) as call:
            await start_conversation(call)
            await providers.user_turn("Please check the standard fixture.")
            await call.wait_until(lambda: providers.business_started.is_set() and WAIT in speech(call))
            await call.finish("caller_hangup")
            assert providers.business_cancelled
            assert not providers.release_business.is_set()
            assert len(providers.business_requests) == 1
            assert call.executor.state.current_node_id == "lookup"
            assert "price" not in call.executor.state.collected_slots
            assert speech(call)[1:] == [WAIT]
            assert sum(bool(body.get("stream")) for body in providers.requests) == 1
            call.assert_clean()
    asyncio.run(scenario())
