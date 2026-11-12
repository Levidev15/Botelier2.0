"""Node-entry safety, not activation of corrections or editable graphs.

These tests explicitly drive the native host API. The admitted graph, spent
node protection and caller mute policy must remain unchanged.
"""

import asyncio
from dataclasses import dataclass, replace

import pytest
from pipecat.frames.frames import DataFrame

from node_contract_io import ERROR, PRESENTATION, PRIVATE, WAIT, speech, tool_delta, tool_result, wait_for_speech
from pilot_io import PilotCall, PilotProviders, logical_function_name, native_schema, native_tool_names


HOST_GUIDANCE = {
    "role": "developer",
    "content": "Current saved flow node: query. Preserve this unrelated host policy.",
}
FRESH_INSTRUCTIONS = "Private re-entry guidance: keep the previous lookup unchanged."


@dataclass
class EntryFence(DataFrame):
    """Test-only normal-queue fence with no application state changes."""


async def enter_node(call, node):
    """Settle both real tool consumers before issuing another native visit."""
    consumed = asyncio.Event()
    fence = EntryFence()

    @call.created[3].assistant().event_handler("on_after_process_frame")
    async def processed(processor, frame):
        if frame is fence:
            consumed.set()

    await call.adapter.manager.set_node_from_config(node)
    await call.created[1].queue_frame(fence)
    await call.wait_until(consumed.is_set)
    await call.wait_for_node(node["name"])


@pytest.mark.parametrize("status,payload,origin,outcome,utterance", [
    (200, {"rooms": [{"name": "Standard", "price": 0}]},
     "choice", "has_results", PRESENTATION),
    (503, {"message": "internal-provider-detail-marker"},
     "failure", "failure", ERROR + " Try a different fixture?"),
    (200, {"rooms": []}, "failure", "no_results",
     "No fixture options were found. Try a different fixture?"),
])
def test_return_to_an_earlier_node_keeps_policy_history_and_fresh_entry_data(
    status, payload, origin, outcome, utterance,
):
    async def scenario():
        providers = PilotProviders([
            tool_delta("collect_query", {"query": "standard"}),
            tool_delta("collect_query", {"query": "premium"}, call_id="reentered-query"),
            "The previous lookup remains unchanged.",
        ], status=status, payload=payload)
        async with PilotCall(providers=providers) as call:
            await call.wait_until(lambda: call.started.is_set())
            call.created[4].add_message(HOST_GUIDANCE.copy())
            await call.activate()
            host_policy = next(
                message["content"].split("\n\n## ASSISTANT LOCAL TIME", 1)[0]
                for message in call.created[4].messages if message.get("role") == "system"
            )
            retained_query = native_schema(call, "query")
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, utterance)
            await call.wait_for_node(origin)
            previous_guidance = call.adapter._guidance
            previous_facts = call.adapter.facts
            prior_history = [
                message for message in call.created[4].messages
                if message.get("role") != "system" and message is not previous_guidance
            ]

            # A fresh visit has its own instructions and prompt. Do not reset
            # accepted nodes or grant an earlier tool permission to act again.
            fresh_query = replace(call.compiled.query, instructions=FRESH_INSTRUCTIONS)
            await enter_node(call, call.adapter._node(
                fresh_query, "Which corrected fixture?",
            ))
            messages = call.created[4].messages
            assert messages and messages[0]["role"] == "system", "Node entry lost the host policy"
            assert messages[0]["content"].startswith(host_policy)
            assert HOST_GUIDANCE in messages
            assert not any(message is previous_guidance for message in messages)
            assert sum(message is call.adapter._guidance for message in messages) == 1
            assert FRESH_INSTRUCTIONS in call.adapter._guidance["content"]
            assert all(any(message is prior for message in messages) for prior in prior_history)
            assert any(
                message.get("role") == "user"
                and message.get("content") == "Please check the standard fixture."
                for message in messages
            )
            assert any(
                message.get("role") == "assistant"
                and message.get("content") == "Hello, this is the offline fixture."
                for message in messages
            )
            assert any(
                message.get("role") == "assistant" and any(
                    logical_function_name(tool["function"]["name"]) == "collect_query"
                    for tool in message.get("tool_calls", [])
                )
                for message in messages
            )
            assert tool_result(call)["outcome"] == outcome
            await wait_for_speech(call, "Which corrected fixture?")

            assert await call.invoke_retained(retained_query, {"query": "premium"}) == {
                "status": "rejected", "reason": "busy_or_stale",
            }
            await providers.user_turn("Search premium now.", turn_index=1)
            await wait_for_speech(call, "The previous lookup remains unchanged.")
            requests = [body for body in providers.requests if body.get("stream")]
            assert len(requests) == 3
            model_messages = requests[1]["messages"]
            assert model_messages[0]["role"] == "system"
            assert model_messages[0]["content"].startswith(host_policy)
            assert HOST_GUIDANCE in model_messages
            assert any(
                message.get("role") == "developer"
                and FRESH_INSTRUCTIONS in message.get("content", "")
                for message in model_messages
            )
            assert not any(
                message.get("role") == "developer"
                and "Private next-node guidance" in message.get("content", "")
                for message in model_messages
            )
            assert tool_result(call, "reentered-query") == {
                "status": "rejected", "reason": "busy_or_stale",
            }
            assert call.adapter.facts == previous_facts
            assert len(providers.business_requests) == 1
            assert native_tool_names(call) == {"collect_query"}
            issued = speech(call)
            assert issued.count("Which fixture?") == 1
            assert issued.count("Which corrected fixture?") == 1
            assert issued.count(WAIT) == 1
            assert issued.count(utterance) == 1
            assert PRIVATE not in " ".join(issued)
            assert FRESH_INSTRUCTIONS not in " ".join(issued)
            assert HOST_GUIDANCE["content"] not in " ".join(issued)
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("reuse_config", [False, True])
def test_repeated_entries_refresh_instructions_without_accumulating_action_handlers(reuse_config):
    async def scenario():
        providers = PilotProviders([])
        async with PilotCall(providers=providers) as call:
            await call.activate()
            slots = (call.compiled.query, call.compiled.choice, call.compiled.failure)
            reusable = {
                slot.node_id: call.adapter._node(slot, f"Repeat the {slot.node_id} question.")
                for slot in slots
            }
            registered = None
            for visit in range(9):
                slot = slots[visit % 3]
                instructions = f"Private instructions for {slot.node_id} visit {visit}."
                fresh_slot = replace(slot, instructions=instructions)
                utterance = (
                    f"Repeat the {slot.node_id} question."
                    if reuse_config else f"Question for {slot.node_id} visit {visit}."
                )
                node = reusable[slot.node_id] if reuse_config else call.adapter._node(
                    fresh_slot, utterance,
                )
                before = len(speech(call))
                previous_guidance = call.adapter._guidance
                await enter_node(call, node)
                await call.wait_until(lambda: (
                    len(speech(call)) > before
                    and not call.created[16].get_audio_contexts()
                    and not call.created[5]._bot_speaking
                ))
                assert speech(call)[before:] == [utterance]
                messages = call.created[4].messages
                assert any(message.get("role") == "system" for message in messages)
                assert not any(message is previous_guidance for message in messages)
                assert sum(message is call.adapter._guidance for message in messages) == 1
                assert (
                    slot.instructions if reuse_config else instructions
                ) in call.adapter._guidance["content"]
                assert native_tool_names(call) == {
                    slot.function_name,
                }
                # Inspect the real native registry's capacity, not a fake
                # manager or a counter added to application code for tests.
                handlers = frozenset(call.adapter.manager._action_manager._action_handlers)
                if visit == 2:
                    registered = handlers
                elif visit > 2:
                    assert handlers == registered
            assert providers.business_requests == []
            assert not any(body.get("stream") for body in providers.requests)
            assert call.adapter.facts == {}
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())
