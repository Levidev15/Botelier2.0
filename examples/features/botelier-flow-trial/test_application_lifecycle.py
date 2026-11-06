"""Whole-call checks: real coordinator and native worker, external I/O offline."""

import asyncio
import importlib
from pathlib import Path

import pytest

from application_support import load_function_mapper
from lifecycle_io import ANSWER, CALL_SID, GREETING, PRIVATE_PROMPT, QUESTION, STREAM_SID
from lifecycle_support import OfflineCall


def test_actual_call_handler_is_importable_without_database_or_server_boot():
    load_function_mapper()
    module = importlib.import_module("botelier.voice.call_handler")
    expected = Path(importlib.import_module("botelier").__file__).parent
    assert Path(module.__file__).resolve() == expected / "voice/call_handler.py"
    handler = module.CallHandler()
    assert not handler.active_calls


@pytest.mark.parametrize("ending", ["caller_hangup", "graceful_end"])
def test_real_coordinator_worker_runs_a_turn_saves_transcript_and_cleans_up(ending):
    """Catches broken startup/turn wiring, dropped speech/save and leaked state."""
    async def scenario():
        async with OfflineCall() as call:
            await call.wait_until(lambda: call.started.is_set())
            await call.wait_until(lambda: call.records.call.ai_greeting_completed)
            assert call.handler.is_pipeline_active(CALL_SID)
            assert call.providers.stt_connected.is_set()
            assert call.providers.tts_connected.is_set()
            call.carrier.start_streaming()
            await call.wait_until(
                lambda: any(isinstance(item, bytes) for item in call.providers.stt.sent)
            )
            await call.providers.user_turn()
            await call.wait_until(
                lambda: any(
                    item.get("type") == "Speak" and ANSWER in item.get("text", "")
                    for item in call.providers.tts.sent
                )
            )
            await call.wait_until(
                lambda: any(
                    message.get("role") == "assistant"
                    and message.get("content") == ANSWER
                    for message in call.created[4].messages
                )
            )
            await call.finish(ending)

            spoken = "".join(
                item["text"] for item in call.providers.tts.sent
                if item.get("type") == "Speak"
            )
            assert GREETING in spoken
            assert spoken.count(ANSWER) == 1
            assert PRIVATE_PROMPT not in spoken
            media = [
                m for m in call.carrier.wire_messages() if m.get("event") == "media"
            ]
            assert media
            assert all(m["streamSid"] == STREAM_SID for m in media)
            requests = [
                body for body in call.providers.requests if body.get("stream")
            ]
            assert len(requests) == 1
            assert requests[0]["model"] == "gpt-4.1-mini"
            assert requests[0]["messages"][0]["role"] == "system"
            assert requests[0]["messages"][0]["content"].startswith(PRIVATE_PROMPT)
            assert requests[0]["messages"][-2:] == [
                {"role": "assistant", "content": GREETING},
                {"role": "user", "content": QUESTION},
            ]
            assert call.finished.is_set()
            assert call.created[1].has_finished()
            assert not call.handler.is_pipeline_active(CALL_SID)
            assert call.queue.is_stopped
            assert call.queue._task is None
            assert all(session.closed for session in call.records.sessions)
            assert len(call.records.saved) == 1
            assert call.records.saved[0]["call_sid"] == CALL_SID
            transcript = call.records.saved[0]["transcript"]
            assert [(item["role"], item["content"]) for item in transcript] == [
                ("assistant", GREETING), ("user", QUESTION), ("assistant", ANSWER),
            ]
            for name, state in vars(call.handler).items():
                if isinstance(state, dict):
                    assert CALL_SID not in state, f"Leaked coordinator state: {name}"
            assert not any(
                item["event_type"] == "pipeline_error" for item in call.records.events
            )
            assert call.remaining_tasks() == [], "Call left background tasks running"
    asyncio.run(scenario())
