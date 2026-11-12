"""Guarded application entry: business work must not be cancelled or replayed.

The existing raw-manager probes deliberately bypass this host API to exercise
the independent visit fences. These cases use real native dispatch, actual
pending transitions and the real cancellation path, with external I/O held.
"""

import asyncio
from dataclasses import replace
from unittest.mock import patch

import pytest
from pipecat.frames.frames import CancelFrame, FunctionCallsStartedFrame, InterruptionFrame

from node_contract_io import (
    PRESENTATION, speech, tool_delta, tool_result, wait_for_speech,
)
from pilot_io import PilotCall, PilotProviders, native_schema
from pilot_speech_io import (
    CURRENT_INSTRUCTIONS, CURRENT_PROMPT, CURRENT_REPLY, wait_for_text,
)

PROTECTED_MCP_RESULT = {
    "content": [{"type": "text", "text": "private-protected-MCP-result"}],
    "structuredContent": {"available": False, "count": 0},
    "isError": False,
}


async def replace_visit(call, target="query"):
    return await call.adapter.replace_node(
        replace(getattr(call.compiled, target), instructions=CURRENT_INSTRUCTIONS),
        CURRENT_PROMPT,
    )


def assert_not_replaced(call, visit, guidance, issued):
    assert call.adapter._visit is visit
    assert call.adapter._guidance is guidance
    assert call.adapter.manager.current_node == "query"
    assert speech(call) == issued
    assert CURRENT_PROMPT not in "".join(speech(call))


@pytest.mark.parametrize("mcp", [False, True])
def test_replacement_refuses_active_business_work_without_cancelling_or_replaying_it(mcp):
    """Removing the protected-work preflight would cancel an actual request."""
    async def scenario():
        name = "mcp_lookup" if mcp else "collect_query"
        replies = [tool_delta(name, {"query": "standard"}, call_id="protected")]
        if mcp:
            replies.append("The connected fixture is ready.")
        providers = PilotProviders(
            replies + [CURRENT_REPLY], status="hold" if not mcp else 200,
            mcp_fault="hold" if mcp else None,
            mcp_result=PROTECTED_MCP_RESULT,
        )
        async with PilotCall(providers=providers, mcp=mcp) as call:
            await call.activate()
            await providers.user_turn("Check the standard fixture.")
            started = providers.mcp_started if mcp else providers.business_started
            await call.wait_until(started.is_set)
            # Thinking speech can independently finish; snapshot after it.
            await call.wait_until(lambda: (
                not call.created[16].get_audio_contexts()
                and not call.created[5]._bot_speaking
            ))
            visit, guidance, issued = call.adapter._visit, call.adapter._guidance, speech(call)
            facts = call.adapter.facts
            with pytest.raises(RuntimeError, match="^pilot_replacement_busy$"):
                await replace_visit(call)
            assert_not_replaced(call, visit, guidance, issued)
            assert call.adapter.facts == facts
            assert not providers.business_cancelled and not providers.mcp_cancelled
            (providers.release_mcp if mcp else providers.release_business).set()
            await wait_for_speech(
                call, "The connected fixture is ready." if mcp else PRESENTATION,
            )
            if mcp:
                assert tool_result(call, "protected") == PROTECTED_MCP_RESULT
            else:
                assert tool_result(call, "protected")["outcome"] == "has_results"
            # Refusal must not leave a stuck gate once native work settles.
            await replace_visit(call, "query" if mcp else "choice")
            await wait_for_text(call, CURRENT_PROMPT)
            await providers.user_turn("Clarify the current question.", turn_index=1)
            await wait_for_text(call, CURRENT_REPLY)
            assert len(providers.business_requests) == (0 if mcp else 1)
            assert len([message for message in providers.mcp_messages
                        if message["method"] == "tools/call"]) == (1 if mcp else 0)
            assert not providers.business_cancelled and not providers.mcp_cancelled
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("mcp", [False, True])
def test_a_native_queued_call_is_protected_before_assistant_bookkeeping_exists(mcp):
    """Checking only assistant.has_function_calls_in_progress misses this window."""
    async def scenario():
        name = "mcp_lookup" if mcp else "collect_query"
        replies = [tool_delta(name, {"query": "standard"}, call_id="queued-protected")]
        if mcp:
            replies.append("The connected fixture is ready.")
        providers = PilotProviders(replies, mcp_result=PROTECTED_MCP_RESULT)
        async with PilotCall(providers=providers, mcp=mcp) as call:
            await call.activate()
            queued, release, release_bookkeeping = (
                asyncio.Event(), asyncio.Event(), asyncio.Event(),
            )
            llm = call.created[2]
            execute = llm._run_function_call
            assistant = call.created[3].assistant()
            process = assistant.process_frame

            async def held_bookkeeping(frame, direction):
                if isinstance(frame, FunctionCallsStartedFrame):
                    await release_bookkeeping.wait()
                return await process(frame, direction)

            async def held(item):
                if item.tool_call_id == "queued-protected":
                    queued.set()
                    await release.wait()
                return await execute(item)

            with (
                patch.object(llm, "_run_function_call", held),
                patch.object(assistant, "process_frame", held_bookkeeping),
            ):
                try:
                    await providers.user_turn("Check the standard fixture.")
                    await call.wait_until(queued.is_set)
                    assert not call.created[3].assistant().has_function_calls_in_progress
                    before = native_schema(call, "query").name
                    visit, guidance, issued = (
                        call.adapter._visit, call.adapter._guidance, speech(call)
                    )
                    with pytest.raises(RuntimeError, match="^pilot_replacement_busy$"):
                        await replace_visit(call)
                    assert_not_replaced(call, visit, guidance, issued)
                    assert native_schema(call, "query").name == before
                    assert providers.business_requests == []
                    assert not any(message["method"] == "tools/call"
                                   for message in providers.mcp_messages)
                finally:
                    release_bookkeeping.set()
                    release.set()
                await wait_for_speech(
                    call, "The connected fixture is ready." if mcp else PRESENTATION,
                )
            if mcp:
                assert tool_result(call, "queued-protected") == PROTECTED_MCP_RESULT
            else:
                assert tool_result(call, "queued-protected")["outcome"] == "has_results"
            assert len(providers.business_requests) == (0 if mcp else 1)
            assert len([message for message in providers.mcp_messages
                        if message["method"] == "tools/call"]) == (1 if mcp else 0)
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_replacement_cannot_discard_a_committed_results_deferred_native_entry():
    """The native callback owns its entry even after function bookkeeping clears."""
    async def scenario():
        providers = PilotProviders([
            tool_delta("collect_query", {"query": "standard"}, call_id="pending-entry"),
        ])
        async with PilotCall(providers=providers) as call:
            await call.activate()
            pending, release = asyncio.Event(), asyncio.Event()
            manager = call.adapter.manager
            execute = manager._execute_transition

            async def held(info):
                pending.set()
                await release.wait()
                return await execute(info)

            with patch.object(manager, "_execute_transition", held):
                try:
                    await providers.user_turn("Check the standard fixture.")
                    await call.wait_until(pending.is_set)
                    await call.wait_until(lambda: (
                        not call.created[3].assistant().has_function_calls_in_progress
                    ))
                    assert tool_result(call, "pending-entry")["outcome"] == "has_results"
                    visit, guidance, issued = (
                        call.adapter._visit, call.adapter._guidance, speech(call)
                    )
                    with pytest.raises(RuntimeError, match="^pilot_replacement_busy$"):
                        await replace_visit(call)
                    assert_not_replaced(call, visit, guidance, issued)
                finally:
                    release.set()
                await wait_for_speech(call, PRESENTATION)
                await call.wait_for_node("choice")
            await replace_visit(call, "choice")
            await wait_for_text(call, CURRENT_PROMPT)
            assert len(providers.business_requests) == 1
            assert speech(call).count(PRESENTATION) == 1
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_replacement_waits_for_real_cancellation_ack_and_refuses_a_second_replacement():
    """An enqueue-only cancellation could publish new instructions too early."""
    async def scenario():
        providers = PilotProviders([CURRENT_REPLY])
        async with PilotCall(providers=providers) as call:
            await call.activate()
            pending, release = asyncio.Event(), asyncio.Event()
            tts = call.created[16]
            process = tts.process_frame

            async def held(frame, direction):
                if isinstance(frame, InterruptionFrame):
                    pending.set()
                    await release.wait()
                return await process(frame, direction)

            visit, guidance, issued = call.adapter._visit, call.adapter._guidance, speech(call)
            with patch.object(tts, "process_frame", held):
                request = asyncio.create_task(replace_visit(call))
                try:
                    await call.wait_until(pending.is_set)
                    assert not request.done()
                    assert_not_replaced(call, visit, guidance, issued)
                    with pytest.raises(RuntimeError, match="^pilot_replacement_busy$"):
                        await replace_visit(call, "choice")
                    assert_not_replaced(call, visit, guidance, issued)
                finally:
                    release.set()
                await asyncio.wait_for(request, 4)
            await wait_for_text(call, CURRENT_PROMPT)
            assert call.adapter._visit is not visit
            assert CURRENT_INSTRUCTIONS in call.adapter._guidance["content"]
            assert speech(call).count(CURRENT_PROMPT) == 1
            await providers.user_turn("Clarify the current question.")
            await wait_for_text(call, CURRENT_REPLY)
            assert providers.business_requests == []
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_actual_hangup_during_replacement_cannot_publish_new_node_output():
    """A late cancellation acknowledgment must not reopen an ending call."""
    async def scenario():
        async with PilotCall(providers=PilotProviders([])) as call:
            await call.activate()
            pending, release, cancel_seen = (
                asyncio.Event(), asyncio.Event(), asyncio.Event(),
            )
            tts = call.created[16]
            process = tts.process_frame

            @call.created[2].event_handler("on_before_process_frame")
            async def terminating(processor, frame):
                if isinstance(frame, CancelFrame):
                    cancel_seen.set()

            async def held(frame, direction):
                if isinstance(frame, InterruptionFrame):
                    pending.set()
                    await release.wait()
                return await process(frame, direction)

            visit = call.adapter._visit
            with patch.object(tts, "process_frame", held):
                request = asyncio.create_task(replace_visit(call))
                hangup = None
                try:
                    await call.wait_until(pending.is_set)
                    hangup = asyncio.create_task(call.finish("caller_hangup"))
                    await call.wait_until(cancel_seen.is_set)
                    results = await asyncio.wait_for(
                        asyncio.gather(request, return_exceptions=True), 2,
                    )
                    assert isinstance(results[0], (RuntimeError, asyncio.CancelledError))
                    assert call.adapter._visit is visit
                    assert CURRENT_PROMPT not in "".join(speech(call))
                finally:
                    release.set()
                    if hangup is not None:
                        await hangup
                    if not request.done():
                        await asyncio.gather(request, return_exceptions=True)
            assert CURRENT_PROMPT not in "".join(speech(call))
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("mcp", [False, True])
def test_a_retained_native_wrapper_cannot_start_business_io_during_handoff(mcp):
    """The preflight is insufficient without last-mile handler admission."""
    async def scenario():
        providers = PilotProviders([], mcp_result=PROTECTED_MCP_RESULT)
        async with PilotCall(providers=providers, mcp=mcp) as call:
            await call.activate()
            retained = (
                next(schema for schema in call.created[4].tools.standard_tools
                     if schema.name == "mcp_lookup")
                if mcp else native_schema(call, "query")
            )
            pending, release = asyncio.Event(), asyncio.Event()
            tts = call.created[16]
            process = tts.process_frame

            async def held(frame, direction):
                if isinstance(frame, InterruptionFrame):
                    pending.set()
                    await release.wait()
                return await process(frame, direction)

            with patch.object(tts, "process_frame", held):
                request = asyncio.create_task(replace_visit(call))
                try:
                    await call.wait_until(pending.is_set)
                    assert await asyncio.wait_for(
                        call.invoke_retained(retained, {"query": "standard"}), 2,
                    ) == {"status": "rejected", "reason": "busy_or_stale"}
                    assert call.adapter.facts == {}
                    assert providers.business_requests == []
                    assert not any(message["method"] == "tools/call"
                                   for message in providers.mcp_messages)
                finally:
                    release.set()
                await asyncio.wait_for(request, 4)
            await wait_for_text(call, CURRENT_PROMPT)
            assert providers.business_requests == []
            assert not any(message["method"] == "tools/call" for message in providers.mcp_messages)
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_a_running_retained_global_wrapper_keeps_its_business_lease_until_completion():
    """A native handler invoked outside the runner still owns its pending I/O."""
    async def scenario():
        providers = PilotProviders([], mcp_fault="hold", mcp_result=PROTECTED_MCP_RESULT)
        async with PilotCall(providers=providers, mcp=True) as call:
            await call.activate()
            retained = next(schema for schema in call.created[4].tools.standard_tools
                            if schema.name == "mcp_lookup")
            lookup = asyncio.create_task(call.invoke_retained(retained, {"query": "standard"}))
            try:
                await call.wait_until(providers.mcp_started.is_set)
                assert not call.created[3].assistant().has_function_calls_in_progress
                visit, guidance, issued = call.adapter._visit, call.adapter._guidance, speech(call)
                with pytest.raises(RuntimeError, match="^pilot_replacement_busy$"):
                    await replace_visit(call)
                assert_not_replaced(call, visit, guidance, issued)
                assert not providers.mcp_cancelled
            finally:
                providers.release_mcp.set()
                result = await lookup
            assert result == PROTECTED_MCP_RESULT
            await replace_visit(call)
            await wait_for_text(call, CURRENT_PROMPT)
            assert len([message for message in providers.mcp_messages
                        if message["method"] == "tools/call"]) == 1
            assert providers.business_requests == []
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())
