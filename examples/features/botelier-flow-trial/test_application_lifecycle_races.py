"""Real call lifecycle races with deterministic gates at external I/O only."""

import asyncio
from datetime import datetime
import inspect

import pytest

from lifecycle_io import (
    ANSWER, CALL_SID, CORRECTION, GREETING, REVISED_ANSWER,
)
from lifecycle_support import OfflineCall


@pytest.mark.parametrize("stage", ["before_registration", "provider_startup"])
def test_hangup_during_startup_consumes_cancel_and_disposes_the_real_worker(stage):
    """A lost early-cancel intent would leave this actual coordinator running."""
    async def scenario():
        async with OfflineCall(
            hold_greeting=stage == "before_registration",
            hold_stt=stage == "provider_startup",
        ) as call:
            boundary = (
                call.greeting_requested if stage == "before_registration"
                else call.providers.stt_connected
            )
            await call.wait_until(boundary.is_set)
            queue = call.handler.call_event_queues[CALL_SID]
            if stage == "before_registration":
                assert CALL_SID not in call.handler.call_tasks
            else:
                assert CALL_SID in call.handler.call_tasks
                assert not call.started.is_set()
            call.carrier.disconnect()
            await call.handler.cancel_call_pipeline(CALL_SID)
            if stage == "before_registration":
                assert CALL_SID in call.handler.pending_cancels
            # Complete the real provider protocol; never replace the runner or
            # use an incomplete fake handshake as evidence of an app defect.
            call.release_greeting.set()
            call.providers.release_stt.set()
            await asyncio.wait_for(asyncio.shield(call.run_task), timeout=5.0)
            call.assert_clean()
            assert queue.is_stopped and queue._task is None
            assert not call.records.call.ai_greeting_completed
            assert not any(body.get("stream") for body in call.providers.requests)
            assert len(call.records.saved) == 1
            assert not any(
                event["event_type"] == "pipeline_error" for event in call.records.events
            )
    asyncio.run(scenario())


def test_hangup_during_greeting_does_not_mark_buffered_speech_as_heard():
    """Cancellation must not classify an unfinished greeting as completed."""
    async def scenario():
        async with OfflineCall(hold_tts_turn=1) as call:
            await call.wait_until(call.started.is_set)
            await call.wait_until(lambda: call.created[5]._bot_speaking)
            assert not call.records.call.ai_greeting_completed
            await call.finish("caller_hangup")
            call.assert_clean()
            assert not call.records.call.ai_greeting_completed
            assert not any(
                event["event_type"] == "greeting_completed" for event in call.records.events
            )
    asyncio.run(scenario())


@pytest.mark.parametrize("interruptions", [True, False])
def test_real_barge_in_obeys_toggle_without_replaying_the_cancelled_reply(interruptions):
    """Wrong gating or stale TTS work would clear disabled speech or repeat a reply."""
    async def scenario():
        async with OfflineCall(
            hold_tts_turn=2, interruptions=interruptions,
        ) as call:
            await call.wait_until(lambda: call.records.call.ai_greeting_completed)
            call.carrier.start_streaming()
            await call.wait_until(
                lambda: any(isinstance(item, bytes) for item in call.providers.stt.sent)
            )
            await call.providers.user_turn()
            await call.wait_until(
                lambda: call.providers.tts.pending_metadata is not None
                and call.created[5]._bot_speaking
            )
            before = sum(
                item.get("type") == "Interrupt" for item in call.providers.tts.sent
            )
            clears = sum(
                item.get("event") == "clear" for item in call.carrier.wire_messages()
            )
            await call.providers.user_turn(CORRECTION, turn_index=1, final=False)
            if interruptions:
                await call.wait_until(
                    lambda: sum(
                        item.get("type") == "Interrupt" for item in call.providers.tts.sent
                    ) == before + 1
                    and sum(
                        item.get("event") == "clear"
                        for item in call.carrier.wire_messages()
                    ) == clears + 1
                )
                assert ANSWER in call.handler.interrupted_responses[CALL_SID]
                await call.providers.user_event("EndOfTurn", CORRECTION, turn_index=1)
                await call.wait_until(
                    lambda: any(
                        m.get("content") == REVISED_ANSWER for m in call.created[4].messages
                    )
                )
            else:
                await call.providers.tts.complete_speech()
                await call.wait_until(lambda: not call.created[5]._bot_speaking)
                assert sum(
                    item.get("type") == "Interrupt" for item in call.providers.tts.sent
                ) == before
                assert not call.handler.interrupted_responses[CALL_SID]
            await call.finish("graceful_end")
            call.assert_clean()
            if not interruptions:
                assert sum(
                    item.get("event") == "clear" for item in call.carrier.wire_messages()
                ) == clears
            spoken = "".join(
                item["text"] for item in call.providers.tts.sent
                if item.get("type") == "Speak"
            )
            assert spoken.count(GREETING) == 1
            assert spoken.count(ANSWER) == 1
            assert spoken.count(REVISED_ANSWER) == int(interruptions)
            requests = [body for body in call.providers.requests if body.get("stream")]
            assert len(requests) == (2 if interruptions else 1)
            if interruptions:
                assert requests[-1]["messages"][-1] == {
                    "role": "user", "content": CORRECTION,
                }
            assert len(call.records.saved) == 1
            assert call.records.saved[0]["llm_prompt_tokens"] == 11 * len(requests)
            assert call.records.saved[0]["llm_completion_tokens"] == 7 * len(requests)
            transcript = call.records.saved[0]["transcript"]
            replies = [
                item for item in transcript
                if item["role"] == "assistant" and item["content"] == ANSWER
            ]
            assert len(replies) == 1
            assert bool(replies[0].get("interrupted")) is interruptions
    asyncio.run(scenario())


async def invoke_retained_callback(callback, args):
    """Model a queued callback resuming late, and drain any I/O it wrongly starts."""
    baseline = set(asyncio.all_tasks())
    result = callback(*args)
    if inspect.isawaitable(result):
        await result
    created = set(asyncio.all_tasks()) - baseline
    if created:
        await asyncio.wait_for(asyncio.gather(*created), timeout=2.0)


def test_replaced_capture_owner_rejects_callbacks_before_old_scope_closes():
    """An open scope is insufficient once its capture buffer has a new owner."""
    async def scenario():
        async with OfflineCall() as call:
            await call.wait_until(lambda: call.records.call.ai_greeting_completed)
            original = call.handler.pending_responses[CALL_SID]
            replacement = []
            sessions = len(call.records.sessions)
            greeting_task = call.handler.greeting_mark_tasks.get(CALL_SID)
            call.handler.pending_responses[CALL_SID] = replacement
            try:
                for kind in ("on_llm_response", "on_user_turn", "on_interruption"):
                    args = ("unowned callback content",)
                    if kind != "on_interruption":
                        args += (datetime.utcnow(),)
                    await invoke_retained_callback(call.callbacks[kind], args)
                await invoke_retained_callback(call.created[8]._greeting_callback, ())
                await invoke_retained_callback(call.created[7]._first_speech_callback, ())
                assert original == [] and replacement == []
                assert call.handler.user_turn_timestamps[CALL_SID] == []
                assert call.handler.interrupted_responses[CALL_SID] == set()
                assert call.handler.greeting_mark_tasks.get(CALL_SID) is greeting_task
                assert len(call.records.sessions) == sessions
                assert call.records.call.caller_spoke is None
            finally:
                call.handler.pending_responses[CALL_SID] = original
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("kind", [
    "on_llm_response", "on_user_turn", "on_interruption", "greeting", "first_speech",
])
def test_retained_callback_cannot_recreate_state_or_modify_a_replacement_call(kind):
    """A SID-only callback would raise after cleanup or corrupt a later generation."""
    async def scenario():
        async with OfflineCall() as ended:
            await ended.wait_until(lambda: ended.records.call.ai_greeting_completed)
            if kind == "greeting":
                callback, args = ended.created[8]._greeting_callback, ()
            elif kind == "first_speech":
                callback, args = ended.created[7]._first_speech_callback, ()
            else:
                callback = ended.callbacks[kind]
                args = ("stale callback content",)
                if kind != "on_interruption":
                    args += (datetime.utcnow(),)
            await ended.finish("graceful_end")
            ended.assert_clean()
            sessions = len(ended.records.sessions)
            await invoke_retained_callback(callback, args)
            ended.assert_clean()
            assert len(ended.records.sessions) == sessions, "Late callback reopened storage"
            handler = ended.handler
        # A reconnect/replacement with the same SID must not accept the previous
        # generation's callback simply because dictionaries exist again.
        async with OfflineCall(handler=handler) as replacement:
            await replacement.wait_until(
                lambda: replacement.records.call.ai_greeting_completed
            )
            sessions = len(replacement.records.sessions)
            await invoke_retained_callback(callback, args)
            assert replacement.handler.pending_responses[CALL_SID] == []
            assert replacement.handler.user_turn_timestamps[CALL_SID] == []
            assert replacement.handler.interrupted_responses[CALL_SID] == set()
            assert len(replacement.records.sessions) == sessions
            await replacement.finish("graceful_end")
            replacement.assert_clean()
    asyncio.run(scenario())
