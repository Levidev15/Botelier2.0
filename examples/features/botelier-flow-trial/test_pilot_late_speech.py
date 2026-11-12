"""Desired speech authority across host-driven node changes, not edit enablement.

Negative cases must never turn into assertions accepting stale output. A
failing assertion is evidence that the candidate cannot yet enable corrections.
"""

import asyncio
from unittest.mock import patch

import pytest
from pipecat.frames.frames import LLMTextFrame

from node_contract_io import speech
from pilot_io import PilotCall, PilotProviders, native_schema
from pilot_speech_io import (
    CURRENT_INSTRUCTIONS, CURRENT_PROMPT, CURRENT_REPLY, OLD_PREFIX, OLD_SUFFIX,
    SpeechProviders, interrupt_assistant, queue_changed_visit, wait_for_text,
)


@pytest.mark.parametrize("prefix", [False, True])
def test_an_unchanged_visit_keeps_its_held_model_reply(prefix):
    """Positive control: the gated transport really emits ordinary model speech."""
    async def scenario():
        providers = SpeechProviders(prefix=prefix)
        async with PilotCall(providers=providers) as call:
            await call.activate()
            await providers.user_turn("Please clarify this question.")
            await call.wait_until(lambda: (
                providers.delayed is not None and providers.delayed.blocked.is_set()
            ))
            if prefix:
                await call.wait_until(lambda: OLD_PREFIX.strip() in "".join(speech(call)))
            providers.delayed.gate.set()
            await wait_for_text(call, OLD_SUFFIX)
            assert providers.delayed.tail_yielded and providers.delayed.closed
            assert len([body for body in providers.requests if body.get("stream")]) == 1
            assert call.adapter.facts == {}
            assert providers.business_requests == []
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("target,prefix", [("query", False), ("choice", True)])
@pytest.mark.parametrize("cancel_first", [False, True])
def test_a_changed_visit_does_not_issue_the_previous_models_late_text(
    target, prefix, cancel_first,
):
    """A late old-model chunk must not become a new provider Speak after re-entry."""
    async def scenario():
        providers = SpeechProviders(prefix=prefix)
        async with PilotCall(providers=providers) as call:
            await call.activate()
            old_name = native_schema(call, "query").name
            await providers.user_turn("Please clarify the earlier question.")
            await call.wait_until(lambda: (
                providers.delayed is not None and providers.delayed.blocked.is_set()
            ))
            if prefix:
                # This prefix was legitimately issued BEFORE the visit changed;
                # the test does not demand retraction of already-issued audio.
                await call.wait_until(lambda: OLD_PREFIX.strip() in "".join(speech(call)))
            assert OLD_SUFFIX not in "".join(speech(call))
            if cancel_first:
                # Retain the native-only control as a double-interruption
                # regression once the application performs cancellation too.
                await interrupt_assistant(call)
                assert providers.delayed.cancelled and providers.delayed.closed
            speech_boundary = len(speech(call))
            settled = await queue_changed_visit(call, target)
            providers.delayed.gate.set()
            await call.wait_until(settled.is_set)
            await wait_for_text(call, CURRENT_PROMPT)
            after_change = tuple(speech(call)[speech_boundary:])
            current_name = native_schema(call, target).name
            assert current_name != old_name
            assert call.adapter.manager.current_node == target
            assert CURRENT_INSTRUCTIONS in call.adapter._guidance["content"]
            assert CURRENT_INSTRUCTIONS not in "".join(speech(call))

            # Rejecting stale work must not strand the current conversation.
            await providers.user_turn("Please clarify the current question.", turn_index=1)
            await wait_for_text(call, CURRENT_REPLY)
            requests = [body for body in providers.requests if body.get("stream")]
            assert len(requests) == 2
            assert old_name in {item["function"]["name"] for item in requests[0]["tools"]}
            assert current_name in {item["function"]["name"] for item in requests[1]["tools"]}
            assert providers.delayed.closed
            assert call.adapter.facts == {}
            assert providers.business_requests == []
            await call.finish("graceful_end")
            call.assert_clean()
            assert OLD_SUFFIX not in "".join(after_change), {
                "target": target, "valid_prefix_issued_before_change": prefix,
                "newly_issued_speech_after_change": after_change,
                "old_stream_tail_yielded": providers.delayed.tail_yielded,
                "old_stream_cancelled": providers.delayed.cancelled,
                "native_cancel_requested_before_entry": cancel_first,
            }
    asyncio.run(scenario())


@pytest.mark.parametrize("cancel_first", [False, True])
def test_a_queued_model_text_cannot_start_synthesis_for_a_superseded_visit(cancel_first):
    """Hold a REAL received model text at TTS, then delegate to the real receiver."""
    async def scenario():
        providers = PilotProviders([OLD_SUFFIX, CURRENT_REPLY])
        async with PilotCall(providers=providers) as call:
            await call.activate()
            pending, release = asyncio.Event(), asyncio.Event()
            tts = call.created[16]
            process = tts.process_frame

            async def held(frame, direction):
                if isinstance(frame, LLMTextFrame) and frame.text == OLD_SUFFIX:
                    pending.set()
                    await release.wait()
                return await process(frame, direction)

            with patch.object(tts, "process_frame", held):
                await providers.user_turn("Please clarify the earlier question.")
                await call.wait_until(pending.is_set)
                assert OLD_SUFFIX not in "".join(speech(call))
                if cancel_first:
                    await interrupt_assistant(call)
                speech_boundary = len(speech(call))
                settled = await queue_changed_visit(call, "query")
                release.set()
                await call.wait_until(settled.is_set)
                await wait_for_text(call, CURRENT_PROMPT)
                after_change = tuple(speech(call)[speech_boundary:])
            await providers.user_turn("Please clarify the current question.", turn_index=1)
            await wait_for_text(call, CURRENT_REPLY)
            assert len([body for body in providers.requests if body.get("stream")]) == 2
            assert call.adapter.facts == {}
            assert providers.business_requests == []
            await call.finish("graceful_end")
            call.assert_clean()
            assert OLD_SUFFIX not in "".join(after_change), {
                "newly_issued_speech_after_change": after_change,
                "native_cancel_requested_before_entry": cancel_first,
            }
    asyncio.run(scenario())


@pytest.mark.parametrize("prefix", [False, True])
def test_hangup_closes_the_model_stream_before_held_late_speech_can_be_issued(prefix):
    """Call teardown is different from a node change, and must still cancel I/O."""
    async def scenario():
        providers = SpeechProviders(prefix=prefix)
        async with PilotCall(providers=providers) as call:
            await call.activate()
            await providers.user_turn("Please clarify this question.")
            await call.wait_until(lambda: (
                providers.delayed is not None and providers.delayed.blocked.is_set()
            ))
            if prefix:
                await call.wait_until(lambda: OLD_PREFIX.strip() in "".join(speech(call)))
            await call.finish("caller_hangup")
            assert providers.delayed.cancelled and providers.delayed.closed
            assert not providers.delayed.gate.is_set()
            before_release = tuple(speech(call))
            providers.delayed.gate.set()
            call.assert_clean()
            assert tuple(speech(call)) == before_release
            assert OLD_SUFFIX not in "".join(speech(call))
            assert providers.business_requests == []
    asyncio.run(scenario())
