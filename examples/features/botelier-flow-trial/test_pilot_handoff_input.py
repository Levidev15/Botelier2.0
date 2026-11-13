"""Caller/model ingress across the actual guarded node-change boundaries."""

import asyncio
from copy import deepcopy

import pytest

from handoff_input_io import (
    HandoffProviders, ReceiverHold, observe_while_held, replacement_outcome,
    wait_for_user_message, wire_guidance, wire_tools,
)
from node_contract_io import PRESENTATION, speech, tool_delta, wait_for_speech
from pilot_io import PilotCall, native_schema
from pilot_speech_io import (
    CURRENT_INSTRUCTIONS, CURRENT_PROMPT, CURRENT_REPLY, OLD_SUFFIX, wait_for_text,
)
from test_pilot_replacement import PROTECTED_MCP_RESULT, replace_visit


def test_a_new_caller_model_stream_cannot_strand_an_already_requested_replacement():
    """Missing ingress ownership lets new old-context inference block cleanup."""
    async def scenario():
        providers = HandoffProviders([OLD_SUFFIX, CURRENT_REPLY], delay_first=True)
        async with PilotCall(providers=providers) as call:
            await call.activate()
            providers.observe(call)
            before = native_schema(call, "query").name
            with ReceiverHold(call, "cancel") as hold:
                request = asyncio.create_task(replace_visit(call))
                try:
                    await call.wait_until(hold.entered.is_set)
                    await providers.user_turn("A fixture answer arrived during the change.")
                    if await observe_while_held(providers.model_seen):
                        await call.wait_until(lambda: (
                            providers.delayed is not None and providers.delayed.blocked.is_set()
                        ))
                finally:
                    hold.release.set()
                outcome = await replacement_outcome(request)
                await call.wait_until(lambda: providers.delayed is not None)
                during = deepcopy(providers.wire[0])
                state = providers.state()
                stream_at_completion = {
                    "blocked": providers.delayed.blocked.is_set(),
                    "cancelled": providers.delayed.cancelled,
                    "closed": providers.delayed.closed,
                }
                providers.delayed.gate.set()
            await call.finish("caller_hangup")
            call.assert_clean()
            print("handoff_model_ingress", {
                "outcome": outcome, "state": state,
                "request_during_handoff": during["handoff"],
                "request_has_current_guidance": CURRENT_INSTRUCTIONS in wire_guidance(during),
                "request_has_old_tool": before in wire_tools(during),
                "stream_at_completion": stream_at_completion,
                "business_requests": len(providers.business_requests),
            })
            assert outcome is None, "New caller inference stranded the node change"
            assert state["current_guidance"] and not state["failed"]
            assert CURRENT_INSTRUCTIONS in wire_guidance(during)
            assert before not in wire_tools(during)
            assert len(providers.wire) == 1
            assert providers.business_requests == []
    asyncio.run(scenario())


def test_a_fast_caller_reply_from_old_context_is_not_spoken_during_replacement():
    """A new stream after the one interruption must not bypass speech ownership."""
    async def scenario():
        providers = HandoffProviders([OLD_SUFFIX, CURRENT_REPLY])
        async with PilotCall(providers=providers) as call:
            await call.activate()
            providers.observe(call)
            with ReceiverHold(call, "cancel") as hold:
                request = asyncio.create_task(replace_visit(call))
                try:
                    await call.wait_until(hold.entered.is_set)
                    await providers.user_turn("Clarify the question during this change.")
                    await observe_while_held(providers.model_finished)
                finally:
                    hold.release.set()
                outcome = await replacement_outcome(request)
            if outcome is None:
                await wait_for_text(call, CURRENT_PROMPT)
                await call.wait_until(providers.model_finished.is_set)
            issued = deepcopy(providers.issued)
            from_old_context = bool(
                providers.wire
                and CURRENT_INSTRUCTIONS not in wire_guidance(providers.wire[0])
            )
            await call.finish("caller_hangup")
            call.assert_clean()
            print("handoff_old_context_speech", {
                "outcome": outcome, "old_model_context": from_old_context, "issued": issued,
            })
            assert outcome is None
            # This tests source authority, not whether a scripted fake model
            # understands its phrase. Deferring inference to the new context
            # or cancelling obsolete inference are both valid implementations.
            assert not (
                from_old_context and OLD_SUFFIX in "".join(item["text"] for item in issued)
            ), "Old-context inference issued speech after replacement was requested"
            assert [item["text"] for item in issued].count(CURRENT_PROMPT) == 1
            assert providers.business_requests == []
    asyncio.run(scenario())


@pytest.mark.parametrize("mcp", [False, True])
@pytest.mark.parametrize("timing", ["during", "after"])
def test_a_current_node_answer_is_not_lost_at_the_last_readiness_boundary(mcp, timing):
    """A blanket handoff rejection must not discard valid new-node input."""
    async def scenario():
        function = "mcp_lookup" if mcp else "collect_query"
        providers = HandoffProviders([
            tool_delta(function, {"query": "standard"}, call_id="handoff-valid"),
            CURRENT_REPLY,
        ], mcp_result=PROTECTED_MCP_RESULT)
        async with PilotCall(providers=providers, mcp=mcp) as call:
            await call.activate()
            providers.observe(call)
            before = native_schema(call, "query").name
            with ReceiverHold(call, "ready") as hold:
                request = asyncio.create_task(replace_visit(call))
                try:
                    await call.wait_until(hold.entered.is_set)
                    current = native_schema(call, "query").name
                    assert current != before
                    assert CURRENT_INSTRUCTIONS in call.adapter._guidance["content"]
                    assert CURRENT_PROMPT not in speech(call)
                    if timing == "during":
                        await providers.user_turn("Check the standard fixture during handoff.")
                        # Observe either a native decision or no inference while
                        # ingress is deferred. This does not require a future
                        # correct input gate to run the model before readiness.
                        await observe_while_held(providers.result_seen)
                finally:
                    hold.release.set()
                outcome = await replacement_outcome(request)
            if timing == "after" and outcome is None:
                await wait_for_text(call, CURRENT_PROMPT)
                await providers.user_turn("Check the standard fixture after handoff.")
            await call.wait_until(lambda: "handoff-valid" in providers.results)
            await call.wait_until(lambda: (
                not call.created[3].assistant().has_function_calls_in_progress
            ))
            if not mcp and providers.results["handoff-valid"]["result"].get("outcome") == "has_results":
                await wait_for_speech(call, PRESENTATION)
            actual = deepcopy(providers.results["handoff-valid"])
            facts = deepcopy(call.adapter.facts)
            wire = deepcopy(providers.wire)
            calls = [item for item in providers.mcp_messages if item["method"] == "tools/call"]
            await call.finish("caller_hangup")
            call.assert_clean()
            print("handoff_current_answer", {
                "mcp": mcp, "timing": timing, "outcome": outcome,
                "decision": actual, "facts": facts,
                "business_requests": len(providers.business_requests),
                "mcp_calls": len(calls), "model_requests": len(wire),
                "current_guidance_in_request": CURRENT_INSTRUCTIONS in wire_guidance(wire[0]),
                "current_tool_in_request": current in wire_tools(wire[0]),
            })
            assert outcome is None
            assert CURRENT_INSTRUCTIONS in wire_guidance(wire[0])
            assert current in wire_tools(wire[0]) and before not in wire_tools(wire[0])
            assert CURRENT_INSTRUCTIONS not in "".join(speech(call))
            assert "private-protected-MCP-result" not in "".join(speech(call))
            if mcp:
                assert actual["result"] == PROTECTED_MCP_RESULT
                assert len(calls) == 1 and providers.business_requests == []
            else:
                assert actual["result"].get("outcome") == "has_results", (
                    "A valid current-node answer was rejected instead of preserved",
                    actual["result"],
                )
                assert facts["query"] == "standard"
                assert len(providers.business_requests) == 1 and calls == []
    asyncio.run(scenario())


def test_hangup_discards_retained_input_while_the_replacement_ack_is_held():
    """Deferred caller input must never start inference after real teardown.

    Active-stream cancellation remains covered by the existing speech and
    lifecycle suites. Requiring a stream to start inside this held window
    would require precisely the unsafe admission this change must prevent.
    """
    async def scenario():
        providers = HandoffProviders([CURRENT_REPLY], delay_first=True)
        async with PilotCall(providers=providers) as call:
            await call.activate()
            providers.observe(call)
            with ReceiverHold(call, "cancel") as hold:
                request = asyncio.create_task(replace_visit(call))
                finishing = None
                try:
                    await call.wait_until(hold.entered.is_set)
                    await providers.user_turn("This fixture caller is about to hang up.")
                    await wait_for_user_message(
                        call, "This fixture caller is about to hang up.",
                    )
                    finishing = asyncio.create_task(call.finish("caller_hangup"))
                    outcome = await replacement_outcome(request)
                finally:
                    hold.release.set()
                await asyncio.wait_for(finishing, 5)
            call.assert_clean()
            assert outcome == {"error": "RuntimeError", "message": "pilot_closed"}
            assert providers.wire == [] and providers.delayed is None
            assert CURRENT_PROMPT not in speech(call)
            assert providers.business_requests == []
    asyncio.run(scenario())


def test_a_current_context_model_reply_can_finish_after_handoff_acknowledgment():
    """A slow valid current reply must not be confused with obsolete inference."""
    async def scenario():
        providers = HandoffProviders([CURRENT_REPLY], delay_first=True)
        async with PilotCall(providers=providers) as call:
            await call.activate()
            providers.observe(call)
            with ReceiverHold(call, "ready") as hold:
                request = asyncio.create_task(replace_visit(call))
                try:
                    await call.wait_until(hold.entered.is_set)
                    await providers.user_turn("Clarify the new current fixture question.")
                    await wait_for_user_message(
                        call, "Clarify the new current fixture question.",
                    )
                finally:
                    hold.release.set()
                outcome = await replacement_outcome(request)
            # Current inference may start only after readiness. Hold the real
            # provider stream independently of the acknowledgment, then prove
            # the completed handoff does not cancel that valid response.
            await call.wait_until(lambda: (
                providers.delayed is not None and providers.delayed.blocked.is_set()
            ))
            during = deepcopy(providers.wire[0])
            # The question itself traverses the same streaming LLM processor.
            # A deliberately held CURRENT inference may delay its delivery;
            # handoff completion, not audible prompt completion, releases I/O.
            providers.delayed.gate.set()
            if outcome is None:
                await wait_for_text(call, CURRENT_PROMPT)
            await wait_for_text(call, CURRENT_REPLY)
            issued = deepcopy(providers.issued)
            await call.finish("caller_hangup")
            call.assert_clean()
            assert outcome is None
            assert CURRENT_INSTRUCTIONS in wire_guidance(during)
            assert [item["text"] for item in issued].count(CURRENT_PROMPT) == 1
            assert [item["text"] for item in issued].count(CURRENT_REPLY) == 1
            assert not providers.delayed.cancelled and providers.delayed.closed
            assert providers.business_requests == []
    asyncio.run(scenario())
