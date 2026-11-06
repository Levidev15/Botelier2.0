"""Actual end-call handler -> native TTS -> speech watcher -> carrier mark."""

import asyncio
from types import SimpleNamespace

import pytest
from pipecat.frames.frames import (
    BotStoppedSpeakingFrame, EndFrame, InputTransportMessageFrame, TTSSpeakFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import FunctionCallParams

from application_support import (
    API_KEYS, RecordingSocket, eventually, load_function_mapper, load_voice_engine,
    make_config, no_customer_records, started_tts,
)


@pytest.mark.parametrize("interrupt_goodbye", [False, True])
def test_real_terminal_path_never_hangs_up_before_audio_and_matching_mark(interrupt_goodbye):
    async def scenario():
        engine = load_voice_engine()
        module = load_function_mapper()
        config = make_config()
        tts = engine.VoiceEngineFactory.create_tts_service(config, API_KEYS)
        tts._websocket = RecordingSocket()
        llm = engine.VoiceEngineFactory.create_llm_service(config, API_KEYS)
        watcher = engine.TtsCompletionWatcher()
        marks = engine.TwilioMarkWatcher(stream_sid="offline-stream")
        carrier_updates = []
        wire_marks = []
        llm_frames = []

        async def watcher_output(frame, direction=FrameDirection.DOWNSTREAM):
            pass

        async def mark_output(frame, direction=FrameDirection.DOWNSTREAM):
            if hasattr(frame, "message") and frame.message.get("event") == "mark":
                wire_marks.append(frame.message)

        watcher.push_frame = watcher_output
        marks.push_frame = mark_output
        mapper = module.FunctionMapper(call_sid="offline-call", account_id="offline-account")
        mapper.set_tts_completion_watcher(watcher)
        mapper.set_twilio_mark_watcher(marks)
        mapper.set_tts_service(tts)

        def update(**kwargs):
            carrier_updates.append(kwargs)

        mapper.twilio_client = SimpleNamespace(
            calls=lambda sid: SimpleNamespace(update=update)
        )

        async def forbidden_result(*args, **kwargs):
            raise AssertionError("A terminal action started another LLM generation")

        try:
            async with started_tts(tts) as (tts_frames, worker):
                async def llm_output(frame, direction=FrameDirection.DOWNSTREAM):
                    llm_frames.append(frame)
                    if isinstance(frame, TTSSpeakFrame):
                        # Real direct-speech SDK dispatch; do not manually
                        # complete the context registered by the handler.
                        await tts.process_frame(frame, direction)

                llm.push_frame = llm_output
                tool = module.Tool(
                    name="offline_end", description="End the synthetic fixture.",
                    config={"goodbye_message": "Goodbye fixture."},
                )
                _, handler = mapper._map_end_call(tool)
                with no_customer_records():
                    await handler(FunctionCallParams(
                        function_name="offline_end", tool_call_id="offline-tool-call",
                        arguments={}, llm=llm, pipeline_worker=worker,
                        context=LLMContext([]), result_callback=forbidden_result,
                    ))
                assert len([f for f in llm_frames if isinstance(f, TTSSpeakFrame)]) == 1
                assert carrier_updates == [] and wire_marks == []

                # A transport stop before the bound synthesis context ends
                # must not bypass the first stage of the gate.
                await watcher.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
                await asyncio.sleep(0)
                assert carrier_updates == [] and wire_marks == []

                if interrupt_goodbye:
                    # Actual service interruption invalidates the callback;
                    # subsequent provider completion must not end the call.
                    from pipecat.frames.frames import InterruptionFrame

                    await tts.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
                    await watcher.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
                    await asyncio.sleep(0)
                    assert carrier_updates == [] and wire_marks == []
                    return

                await tts._websocket.deliver(
                    b"\0" * 320,
                    {"type": "SpeechMetadata", "audio_duration_ms": 20},
                )
                await eventually(lambda: watcher._on_done_callback is not None)
                assert carrier_updates == [] and wire_marks == []
                await watcher.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
                await eventually(lambda: len(wire_marks) == 1)
                assert carrier_updates == []
                await marks.process_frame(InputTransportMessageFrame(message={
                    "event": "mark", "mark": {"name": "wrong-fixture-mark"},
                }), FrameDirection.UPSTREAM)
                await asyncio.sleep(0)
                assert carrier_updates == []
                await marks.process_frame(InputTransportMessageFrame(message={
                    "event": "mark", "mark": wire_marks[0]["mark"],
                }), FrameDirection.UPSTREAM)
                await eventually(lambda: any(isinstance(f, EndFrame) for f in llm_frames))
                assert carrier_updates == [{"status": "completed"}]
        finally:
            watcher.clear_callback()
            marks.clear_pending()
            await llm._client.close()
    asyncio.run(scenario())


def test_unacknowledged_carrier_mark_times_out_and_cleans_its_waiter():
    async def scenario():
        engine = load_voice_engine()
        marks = engine.TwilioMarkWatcher(stream_sid="offline-stream")
        messages = []

        async def output(frame, direction=FrameDirection.DOWNSTREAM):
            messages.append(frame)

        marks.push_frame = output
        assert await marks.send_mark_and_wait("fixture", timeout=0.01) is False
        assert len(messages) == 1
        assert marks._pending == {}
    asyncio.run(scenario())
