"""Limits, failed acknowledgments and usable new-node speech for host entry."""

import asyncio
from dataclasses import replace
from unittest.mock import patch

import pytest
from pipecat.frames.frames import InterruptionFrame

from node_contract_io import PRESENTATION, speech, tool_delta, tool_result, wait_for_speech
from pilot_io import PilotCall, PilotProviders, native_schema
from pilot_speech_io import CURRENT_INSTRUCTIONS, CURRENT_PROMPT, CURRENT_REPLY, wait_for_text
from test_pilot_replacement import assert_not_replaced, replace_visit


@pytest.mark.parametrize("invalid", [
    "foreign_shape", "new_node", "new_binding", "new_saved_prompt",
    "nontext_instructions", "long_instructions", "empty_speech",
    "nontext_speech", "long_speech",
])
def test_invalid_replacement_is_rejected_before_any_native_cancellation(invalid):
    """Scope or payload validation must precede all state and provider effects."""
    async def scenario():
        async with PilotCall(providers=PilotProviders([])) as call:
            await call.activate()
            visit, guidance, issued = call.adapter._visit, call.adapter._guidance, speech(call)
            interruptions = []

            @call.created[16].event_handler("on_after_process_frame")
            async def cancelled(processor, frame):
                if isinstance(frame, InterruptionFrame):
                    interruptions.append(frame)

            slot, utterance = call.compiled.query, CURRENT_PROMPT
            if invalid == "foreign_shape":
                slot = {"node_id": "query", "variable": "query"}
            elif invalid == "new_node":
                slot = replace(slot, node_id="unadmitted")
            elif invalid == "new_binding":
                slot = replace(slot, variable="rooms")
            elif invalid == "new_saved_prompt":
                slot = replace(slot, prompt="An unadmitted saved question?")
            elif invalid == "nontext_instructions":
                slot = replace(slot, instructions=None)
            elif invalid == "long_instructions":
                slot = replace(slot, instructions="x" * 8001)
            elif invalid == "empty_speech":
                utterance = " "
            elif invalid == "nontext_speech":
                utterance = {"text": CURRENT_PROMPT}
            elif invalid == "long_speech":
                utterance = "x" * 8001
            with pytest.raises(ValueError, match="^pilot_replacement_config$"):
                await call.adapter.replace_node(slot, utterance)
            assert_not_replaced(call, visit, guidance, issued)
            assert interruptions == []
            assert call.providers.business_requests == []
            assert call.adapter.facts == {}
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("when", ["before_start", "after_close"])
def test_replacement_cannot_start_or_reopen_the_pilot(when):
    async def scenario():
        async with PilotCall(providers=PilotProviders([])) as call:
            await call.wait_until(call.started.is_set)
            if when == "after_close":
                await call.activate()
                await call.finish("caller_hangup")
            before = tuple(speech(call))
            reason = "pilot_not_startable" if when == "before_start" else "pilot_closed"
            with pytest.raises(RuntimeError, match=f"^{reason}$"):
                await replace_visit(call)
            assert tuple(speech(call)) == before
            if when == "before_start":
                await call.activate()
                await call.finish("graceful_end")
            assert CURRENT_PROMPT not in "".join(speech(call))
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("abort", ["deadline", "cancel_request"])
def test_unacknowledged_replacement_fails_closed_instead_of_reopening_tool_admission(abort):
    """Late native frames must not run against a falsely reopened handoff."""
    async def scenario():
        import botelier.voice.flows.pilot_replacement as module

        async with PilotCall(providers=PilotProviders([])) as call:
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
            with (
                patch.object(tts, "process_frame", held),
                patch.object(module, "HANDOFF_TIMEOUT_SECONDS", .1 if abort == "deadline" else 5),
            ):
                request = asyncio.create_task(replace_visit(call))
                try:
                    await call.wait_until(pending.is_set)
                    if abort == "cancel_request":
                        request.cancel()
                    with pytest.raises(
                        TimeoutError if abort == "deadline" else asyncio.CancelledError,
                    ):
                        await asyncio.wait_for(request, 2)
                    assert_not_replaced(call, visit, guidance, issued)
                    with pytest.raises(RuntimeError, match="^pilot_replacement_failed$"):
                        await replace_visit(call)
                    assert call.adapter._replacement.blocked
                    assert call.adapter.facts == {}
                    assert call.providers.business_requests == []
                finally:
                    release.set()
                    if not request.done():
                        await asyncio.gather(request, return_exceptions=True)
            # A late real ack must not release new prompt/tool work.
            await call.finish("caller_hangup")
            assert CURRENT_PROMPT not in "".join(speech(call))
            call.assert_clean()
    asyncio.run(scenario())


def test_new_node_is_usable_while_its_replacement_prompt_is_still_playing():
    """Waiting for new audio completion would strand a valid current answer."""
    async def scenario():
        providers = PilotProviders([
            tool_delta("collect_query", {"query": "standard"}, call_id="current-answer"),
        ], hold_tts_turn=3)
        async with PilotCall(providers=providers) as call:
            await call.activate()
            before = native_schema(call, "query").name
            await replace_visit(call)
            await call.wait_until(lambda: (
                providers.tts.pending_metadata is not None
                and CURRENT_PROMPT in speech(call) and call.created[5]._bot_speaking
            ))
            assert native_schema(call, "query").name != before
            assert not call.adapter._replacement.blocked
            await providers.user_turn("Check the standard fixture.")
            await wait_for_speech(call, PRESENTATION)
            assert tool_result(call, "current-answer")["outcome"] == "has_results"
            assert call.adapter.manager.current_node == "choice"
            assert call.adapter.facts["query"] == "standard"
            assert len(providers.business_requests) == 1
            assert speech(call).count(CURRENT_PROMPT) == 1
            assert CURRENT_INSTRUCTIONS not in "".join(speech(call))
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_repeated_completed_replacements_keep_native_handlers_and_call_hooks_bounded():
    async def scenario():
        providers = PilotProviders([CURRENT_REPLY] * 3)
        async with PilotCall(providers=providers) as call:
            await call.activate()
            owners = [
                (call.created[2], "on_before_push_frame"),
                (call.created[2], "on_before_process_frame"),
                (call.created[3].assistant(), "on_after_process_frame"),
                (call.created[1], "on_frame_reached_downstream"),
            ]
            before = [len(owner._event_handlers[event].handlers) for owner, event in owners]
            names = set()
            for index in range(3):
                prompt = f"Which current fixture for controlled visit {index + 1}?"
                await call.adapter.replace_node(
                    replace(call.compiled.query, instructions=CURRENT_INSTRUCTIONS), prompt,
                )
                await wait_for_text(call, prompt)
                name = native_schema(call, "query").name
                assert name not in names
                names.add(name)
                await providers.user_turn("Clarify the current fixture.", turn_index=index)
                await call.wait_until(lambda: (
                    "".join(speech(call)).count(CURRENT_REPLY) == index + 1
                    and not call.created[16].get_audio_contexts()
                    and not call.created[5]._bot_speaking
                ))
                assert {key for key in call.created[2]._functions
                        if isinstance(key, str) and key.startswith("pilot_collect_")} == {name}
                assert call.adapter._replacement._waiting is None
                assert call.adapter._replacement._calls == set()
                assert call.adapter._replacement._owner is None
                assert speech(call).count(prompt) == 1
            assert before == [len(owner._event_handlers[event].handlers) for owner, event in owners]
            assert providers.business_requests == []
            assert call.adapter.facts == {}
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())
