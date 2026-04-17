"""
Regression test for GreetingAudioInjector (Task #110).

Verifies that the cached greeting bytes pushed via the injector are NEVER
seen by a processor placed UPSTREAM of the injector (i.e., where the STT
service lives in the production pipeline), and ARE seen — in the correct
TTSStartedFrame → TTSAudioRawFrame… → TTSStoppedFrame sequence — by a
processor placed DOWNSTREAM (where the transport sink lives).

This locks in the architectural fix that broke the cached-greeting STT
loopback: previously ``task.queue_frames(...)`` injected at the pipeline
source so the bot's own greeting flowed through STT and was transcribed by
Deepgram.
"""

import asyncio
from typing import List

import pytest

from pipecat.frames.frames import (
    Frame,
    AudioRawFrame,
    EndFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from botelier.voice.engine import GreetingAudioInjector


class _RecordingProcessor(FrameProcessor):
    """Records every frame that flows through it (in order, with direction)."""

    def __init__(self, label: str, **kwargs):
        super().__init__(**kwargs)
        self.label = label
        self.received: List[Frame] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        self.received.append(frame)
        await self.push_frame(frame, direction)

    @property
    def audio_frames(self) -> List[AudioRawFrame]:
        return [f for f in self.received if isinstance(f, AudioRawFrame)]


@pytest.mark.asyncio
async def test_cached_greeting_bypasses_upstream_processors():
    """Audio pushed via injector.set_pending_greeting must:
    - never reach a processor upstream of the injector (STT's position)
    - reach a processor downstream of the injector (transport sink's position)
    - arrive as TTSStartedFrame → N×TTSAudioRawFrame → TTSStoppedFrame
    """
    upstream_stt_stub = _RecordingProcessor("upstream_stt_stub")
    injector = GreetingAudioInjector()
    downstream_sink_stub = _RecordingProcessor("downstream_sink_stub")

    # Mirrors the production pipeline shape (simplified):
    #   transport.input() → … → stt → … → injector → tts → … → transport.output()
    # We collapse everything except the three points of interest.
    pipeline = Pipeline([upstream_stt_stub, injector, downstream_sink_stub])

    # 320 bytes = 1 chunk @ 20ms; using 3200 bytes = 10 chunks (200 ms greeting).
    fake_audio = b"\x00\x01" * 1600  # 3200 bytes of int16-LE PCM
    injector.set_pending_greeting(fake_audio)

    task = PipelineTask(pipeline)
    runner = PipelineRunner()

    # Stop the pipeline shortly after greeting injection completes.
    async def _stopper():
        await asyncio.sleep(0.5)
        await task.queue_frames([EndFrame()])

    asyncio.create_task(_stopper())
    await runner.run(task)

    # Upstream processor (STT's position) MUST NOT see any AudioRawFrame.
    # This is the regression assertion — previously the STT processor
    # received the cached greeting via task.queue_frames at the source.
    assert upstream_stt_stub.audio_frames == [], (
        f"Cached greeting leaked upstream of injector — STT would transcribe it. "
        f"Upstream received {len(upstream_stt_stub.audio_frames)} AudioRawFrames."
    )

    # Downstream processor (transport's position) MUST receive the lifecycle frames.
    types_downstream = [type(f).__name__ for f in downstream_sink_stub.received]
    assert "TTSStartedFrame" in types_downstream, types_downstream
    assert "TTSStoppedFrame" in types_downstream, types_downstream

    started_idx = types_downstream.index("TTSStartedFrame")
    stopped_idx = types_downstream.index("TTSStoppedFrame")
    assert started_idx < stopped_idx, "TTSStartedFrame must precede TTSStoppedFrame"

    audio_between = [
        f
        for i, f in enumerate(downstream_sink_stub.received)
        if started_idx < i < stopped_idx and isinstance(f, TTSAudioRawFrame)
    ]
    expected_chunks = (len(fake_audio) + 319) // 320
    assert len(audio_between) == expected_chunks, (
        f"Expected {expected_chunks} TTSAudioRawFrame chunks downstream, "
        f"got {len(audio_between)}"
    )

    # Recombined audio must equal the input bytes — chunking is lossless.
    recombined = b"".join(f.audio for f in audio_between)
    assert recombined == fake_audio, "Chunked audio did not roundtrip cleanly"


@pytest.mark.asyncio
async def test_injector_passes_unrelated_frames_through_unchanged():
    """Frames other than the one-shot greeting must flow through untouched in
    both directions, and the injector must not fabricate any audio when
    ``set_pending_greeting`` was never called.
    """
    upstream = _RecordingProcessor("upstream")
    injector = GreetingAudioInjector()
    downstream = _RecordingProcessor("downstream")

    pipeline = Pipeline([upstream, injector, downstream])

    # Do NOT set_pending_greeting — only flush an EndFrame to drain the pipeline.
    task = PipelineTask(pipeline)
    runner = PipelineRunner()

    async def _stopper():
        await asyncio.sleep(0.2)
        await task.queue_frames([EndFrame()])

    asyncio.create_task(_stopper())
    await runner.run(task)

    # No greeting was set → no TTSAudioRawFrame must appear anywhere.
    assert all(
        not isinstance(f, TTSAudioRawFrame) for f in downstream.received
    ), "Injector emitted TTSAudioRawFrame without set_pending_greeting"
    assert all(
        not isinstance(f, TTSAudioRawFrame) for f in upstream.received
    )

    # Sentinel pass-through: every frame the downstream observer received
    # without an active greeting must be an *infrastructure* frame
    # (StartFrame/EndFrame/etc.) — never a TTS lifecycle frame synthesized
    # by the injector. If the injector ever spuriously emits
    # TTSStartedFrame/TTSStoppedFrame in the no-greeting case, downstream
    # bot-speaking bookkeeping would flip incorrectly.
    spurious = [
        type(f).__name__
        for f in downstream.received
        if isinstance(f, (TTSStartedFrame, TTSStoppedFrame, TTSAudioRawFrame))
    ]
    assert spurious == [], (
        f"Injector emitted spurious TTS lifecycle frames with no pending "
        f"greeting: {spurious}"
    )


@pytest.mark.asyncio
async def test_set_pending_greeting_is_idempotent_after_inject():
    """Calling set_pending_greeting after the one-shot has fired must be a
    no-op (no re-greeting on long-lived pipelines)."""
    upstream = _RecordingProcessor("upstream")
    injector = GreetingAudioInjector()
    downstream = _RecordingProcessor("downstream")

    pipeline = Pipeline([upstream, injector, downstream])
    injector.set_pending_greeting(b"\x00\x01" * 160)  # 320 bytes = 1 chunk

    task = PipelineTask(pipeline)
    runner = PipelineRunner()

    async def _drive():
        await asyncio.sleep(0.3)
        # Try to inject AGAIN after the first injection has fired — must be ignored.
        injector.set_pending_greeting(b"\xff\xff" * 160)
        await asyncio.sleep(0.2)
        await task.queue_frames([EndFrame()])

    asyncio.create_task(_drive())
    await runner.run(task)

    audio_chunks = [f for f in downstream.received if isinstance(f, TTSAudioRawFrame)]
    assert len(audio_chunks) == 1, (
        f"Expected exactly 1 TTSAudioRawFrame chunk (one-shot), got {len(audio_chunks)}"
    )
    # Confirms it kept the FIRST audio (\x00\x01) and ignored the re-set (\xff\xff).
    assert audio_chunks[0].audio == b"\x00\x01" * 160
