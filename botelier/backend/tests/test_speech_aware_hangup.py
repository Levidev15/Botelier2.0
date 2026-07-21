"""Tests for Task #410 — end-call & transfer message cutoff fixes.

Covers:
1. TtsCompletionWatcher.schedule_after_speech is speech-aware: the safety
   timeout must NOT fire while the bot is audibly speaking (long pre-transfer
   messages are no longer clipped at 5s), but still fires when speech never
   starts, and a hard max_wait cap bounds a stuck pipeline.
2. The end_call / flow END handlers defer the Twilio REST hangup + EndFrame
   to a post-speech callback (same caller-heard boundary transfers use)
   instead of hanging up immediately after pushing the goodbye TTSSpeakFrame.
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

_VOICE_DIR = Path(__file__).resolve().parents[1] / "botelier" / "voice"
_voice_pkg = sys.modules.get("botelier.voice")
if _voice_pkg is not None:
    _voice_pkg.__path__ = [str(_VOICE_DIR)]

from botelier.voice.engine import TtsCompletionWatcher
from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame
from pipecat.processors.frame_processor import FrameDirection

_FUNCTION_MAPPER_SRC = (
    Path(__file__).resolve().parents[1] / "botelier" / "voice" / "function_mapper.py"
).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_watchdog_does_not_fire_while_bot_is_speaking():
    """A message longer than the safety timeout must not be clipped."""
    watcher = TtsCompletionWatcher()
    fired = asyncio.Event()

    async def callback():
        fired.set()

    watcher.reset()
    watcher.schedule_after_speech(callback, timeout=0.3, max_wait=5.0)

    # Bot starts speaking — simulates a long configured message.
    await watcher.process_frame(BotStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)

    # Wait well past the 0.3s safety timeout — must NOT fire mid-speech.
    await asyncio.sleep(0.9)
    assert not fired.is_set(), "watchdog fired while the bot was still speaking"

    # Speech ends — callback fires via BotStoppedSpeakingFrame.
    await watcher.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await asyncio.wait_for(fired.wait(), timeout=1.0)


@pytest.mark.asyncio
async def test_watchdog_fires_when_speech_never_starts():
    """The TTS-context-wipe failure case: no audio ever plays → timeout fires."""
    watcher = TtsCompletionWatcher()
    fired = asyncio.Event()

    async def callback():
        fired.set()

    watcher.reset()
    watcher.schedule_after_speech(callback, timeout=0.3, max_wait=5.0)

    # No BotStartedSpeakingFrame ever arrives.
    await asyncio.wait_for(fired.wait(), timeout=2.0)


@pytest.mark.asyncio
async def test_watchdog_hard_cap_bounds_stuck_pipeline():
    """If BotStoppedSpeakingFrame is lost while speaking flag stays set,
    max_wait guarantees the callback still fires (caller never stranded)."""
    watcher = TtsCompletionWatcher()
    fired = asyncio.Event()

    async def callback():
        fired.set()

    watcher.reset()
    watcher.schedule_after_speech(callback, timeout=0.2, max_wait=0.8)

    await watcher.process_frame(BotStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    # Bot "never stops speaking" — hard cap must fire the callback.
    await asyncio.wait_for(fired.wait(), timeout=3.0)


@pytest.mark.asyncio
async def test_watchdog_post_speech_grace_rearms_after_speech():
    """Silence AFTER speech (lost BotStoppedSpeakingFrame but flag cleared)
    still has a bounded wait: the grace deadline re-arms from end of speech."""
    watcher = TtsCompletionWatcher()
    fired = asyncio.Event()

    async def callback():
        fired.set()

    watcher.reset()
    watcher.schedule_after_speech(callback, timeout=0.3, max_wait=5.0)

    await watcher.process_frame(BotStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await asyncio.sleep(0.5)  # speaking past original grace deadline
    # Clear the flag WITHOUT setting the done event (simulates flag-only drift).
    watcher._bot_speaking = False
    # Callback must fire within the re-armed grace window, not wait for max_wait.
    await asyncio.wait_for(fired.wait(), timeout=1.5)


@pytest.mark.asyncio
async def test_callback_not_double_fired():
    """Timeout guard and BotStoppedSpeakingFrame must not both fire the callback."""
    watcher = TtsCompletionWatcher()
    fire_count = 0

    async def callback():
        nonlocal fire_count
        fire_count += 1

    watcher.reset()
    watcher.schedule_after_speech(callback, timeout=0.2, max_wait=1.0)

    await watcher.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await asyncio.sleep(1.5)  # let any stale timeout guard run to completion

    assert fire_count == 1


def test_end_call_hangup_is_deferred_to_post_speech_callback():
    """end_call and flow END must NOT issue the REST hangup inline after the
    goodbye TTSSpeakFrame — the hangup lives in _finalize_call_end, which runs
    only after speech completes and the Twilio playback mark is awaited."""
    src = _FUNCTION_MAPPER_SRC

    # The shared finalizer exists and awaits the playback mark before hangup.
    assert "async def _finalize_call_end" in src
    assert "async def _rest_hangup" in src
    finalizer = src.split("async def _finalize_call_end", 1)[1].split("def _run_after_speech")[0]
    assert "_await_twilio_playback_mark" in finalizer
    assert "_rest_hangup" in finalizer
    assert "EndFrame()" in finalizer

    # Both end paths route through the post-speech scheduler.
    assert 'self._finalize_call_end(params.llm, "end_call")' in src
    assert 'self._finalize_call_end(params.llm, "flow_end")' in src

    # The old inline-hangup markers are gone from the end paths.
    assert "REST hangup issued for call {self.call_sid} (end_call tool)" not in src
    assert "REST hangup issued for call {self.call_sid} (flow END node)" not in src


def test_twilio_mark_budget_raised():
    """2s clipped buffered tail audio; budget must be comfortably larger."""
    from botelier.voice.function_mapper import TWILIO_MARK_TIMEOUT_SECS

    assert TWILIO_MARK_TIMEOUT_SECS >= 8.0


@pytest.mark.asyncio
async def test_ctx_id_chains_to_bot_stopped_not_immediate():
    """context-ID path must NOT fire the callback when on_audio_context_completed
    fires — audio frames are still in pipeline queues at that point and have not
    reached transport.output().  The callback must only fire after
    BotStoppedSpeakingFrame arrives (audio confirmed written to WebSocket)."""
    watcher = TtsCompletionWatcher()
    fired = asyncio.Event()

    async def real_callback():
        fired.set()

    # Replicate what _run_after_speech does in the context-ID path.
    async def ctx_done_wrapper():
        watcher.reset()
        watcher.schedule_after_speech(real_callback, timeout=5.0)

    # Stage 1: on_audio_context_completed fires (audio still in pipeline).
    await ctx_done_wrapper()

    # Callback must NOT have fired yet.
    await asyncio.sleep(0)
    assert not fired.is_set(), "callback fired before BotStoppedSpeakingFrame"

    # Stage 2: BotStoppedSpeakingFrame arrives upstream from transport.output()
    # (audio bytes written to WebSocket).
    await watcher.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
    await asyncio.wait_for(fired.wait(), timeout=1.0)


@pytest.mark.asyncio
async def test_ctx_id_chain_survives_bot_already_speaking():
    """If BotStartedSpeakingFrame has already arrived (audio partially in transit)
    when the context-ID wrapper runs, the callback must still fire on BotStopped
    and must not be triggered prematurely by the silence timeout."""
    watcher = TtsCompletionWatcher()
    fired = asyncio.Event()

    async def real_callback():
        fired.set()

    # Simulate audio already flowing: BotStarted has reached the watcher.
    await watcher.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)

    # context-ID wrapper runs (on_audio_context_completed fired).
    async def ctx_done_wrapper():
        watcher.reset()
        watcher.schedule_after_speech(real_callback, timeout=0.3)

    await ctx_done_wrapper()

    # The watcher's _bot_speaking flag was set before reset(), so the timeout
    # guard must NOT fire within 0.3 s of silence — it should wait for BotStopped.
    await asyncio.sleep(0.5)
    assert not fired.is_set(), "callback fired via timeout while bot was speaking"

    # BotStopped arrives — callback fires.
    await watcher.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
    await asyncio.wait_for(fired.wait(), timeout=1.0)
