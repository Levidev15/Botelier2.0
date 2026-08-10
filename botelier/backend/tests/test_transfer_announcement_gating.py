"""Regression tests for transfer-announcement gating fallback paths.

Locks the ordering guarantees that prevent transfer/goodbye announcements from
being cut off:

- estimate_playback_secs bounds (degraded-path wait scaling)
- _await_twilio_playback_mark degraded paths wait a length-scaled estimate
  instead of proceeding immediately (no watcher, or mark-ack timeout)
- TtsCompletionWatcher's silent-grace watchdog does NOT fire while TTS frames
  are flowing (announcement queued/starting but not yet audible)
- the hard cap still fires as last resort
- _run_after_speech's no-watcher fallback delay scales with announcement length
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

_VOICE_DIR = Path(__file__).resolve().parents[1] / "botelier" / "voice"
_voice_pkg = sys.modules.get("botelier.voice")
if _voice_pkg is not None:
    _voice_pkg.__path__ = [str(_VOICE_DIR)]

from botelier.voice.engine import TtsCompletionWatcher
from botelier.voice.function_mapper import (
    _PLAYBACK_MAX_SECS,
    _PLAYBACK_MIN_SECS,
    FunctionMapper,
    estimate_playback_secs,
)
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    TTSAudioRawFrame,
)
from pipecat.processors.frame_processor import FrameDirection


# ── estimate_playback_secs ──────────────────────────────────────────────────


def test_estimate_bounds():
    assert estimate_playback_secs(None) == _PLAYBACK_MIN_SECS
    assert estimate_playback_secs("") == _PLAYBACK_MIN_SECS
    assert estimate_playback_secs("x" * 10000) == _PLAYBACK_MAX_SECS


def test_estimate_scales_with_length():
    short = estimate_playback_secs("One moment please...")
    long = estimate_playback_secs(
        "Please hold while I connect you to our front desk team, "
        "they will be able to help you with your booking right away."
    )
    assert long > short
    assert _PLAYBACK_MIN_SECS <= short < long <= _PLAYBACK_MAX_SECS


# ── _await_twilio_playback_mark degraded paths ──────────────────────────────


def _bare_mapper() -> FunctionMapper:
    m = FunctionMapper.__new__(FunctionMapper)
    m.call_sid = "CAtest"
    m._twilio_mark_watcher = None
    m._tts_service = None
    m._tts_completion_watcher = None
    return m


@pytest.mark.asyncio
async def test_mark_wait_without_watcher_waits_estimate(monkeypatch):
    """No mark watcher → degraded path must sleep the playback estimate, not
    proceed immediately."""
    m = _bare_mapper()
    slept: list[float] = []

    async def fake_sleep(secs):
        slept.append(secs)

    monkeypatch.setattr(
        "botelier.voice.function_mapper.asyncio.sleep", fake_sleep
    )
    text = "Please hold while I connect you to the front desk."
    ok = await m._await_twilio_playback_mark("transfer", expected_speech_text=text)
    assert ok is False
    assert slept == [pytest.approx(estimate_playback_secs(text))]


@pytest.mark.asyncio
async def test_mark_wait_timeout_waits_additional_estimate(monkeypatch):
    """Mark ack timeout → degraded path sleeps the estimate before returning."""
    m = _bare_mapper()

    class _StubWatcher:
        async def send_mark_and_wait(self, name, timeout):
            return False  # ack never arrived

    m._twilio_mark_watcher = _StubWatcher()
    slept: list[float] = []

    async def fake_sleep(secs):
        slept.append(secs)

    monkeypatch.setattr(
        "botelier.voice.function_mapper.asyncio.sleep", fake_sleep
    )
    text = "One moment please, connecting you now."
    ok = await m._await_twilio_playback_mark("transfer", expected_speech_text=text)
    assert ok is False
    assert slept == [pytest.approx(estimate_playback_secs(text))]


@pytest.mark.asyncio
async def test_mark_send_exception_waits_estimate(monkeypatch):
    """A mark send/wait EXCEPTION is an unconfirmed outcome — must wait the
    estimate, never proceed immediately (was the clipped-goodbye path)."""
    m = _bare_mapper()

    class _StubWatcher:
        async def send_mark_and_wait(self, name, timeout):
            raise RuntimeError("websocket closed")

    m._twilio_mark_watcher = _StubWatcher()
    slept: list[float] = []

    async def fake_sleep(secs):
        slept.append(secs)

    monkeypatch.setattr(
        "botelier.voice.function_mapper.asyncio.sleep", fake_sleep
    )
    text = "Thank you for calling, goodbye!"
    ok = await m._await_twilio_playback_mark("end_call", expected_speech_text=text)
    assert ok is False
    assert slept == [pytest.approx(estimate_playback_secs(text))]


def test_long_announcement_not_undercut_by_cap():
    """A ~400-char announcement (~30 s at the assumed rate) must get its full
    estimated duration — the cap only bounds absurd inputs."""
    text = "x" * 400
    est = estimate_playback_secs(text)
    assert est == pytest.approx(400 / 14.0 + 1.5)
    assert est < _PLAYBACK_MAX_SECS


@pytest.mark.asyncio
async def test_mark_ack_skips_degraded_wait(monkeypatch):
    m = _bare_mapper()

    class _StubWatcher:
        async def send_mark_and_wait(self, name, timeout):
            return True

    m._twilio_mark_watcher = _StubWatcher()
    slept: list[float] = []

    async def fake_sleep(secs):
        slept.append(secs)

    monkeypatch.setattr(
        "botelier.voice.function_mapper.asyncio.sleep", fake_sleep
    )
    ok = await m._await_twilio_playback_mark("transfer", expected_speech_text="hi")
    assert ok is True
    assert slept == []


# ── TtsCompletionWatcher watchdog behaviour ─────────────────────────────────


def _make_watcher() -> TtsCompletionWatcher:
    w = TtsCompletionWatcher.__new__(TtsCompletionWatcher)
    # Initialize only the state our methods use (skip FrameProcessor.__init__
    # which requires a running pipeline).
    w._speaking_done = asyncio.Event()
    w._speaking_done.set()
    w._on_done_callback = None
    w._bot_speaking = False
    w._guard_task = None
    w._last_tts_activity = None
    return w


@pytest.mark.asyncio
async def test_silent_grace_does_not_fire_while_tts_active():
    """Silent-grace watchdog must NOT fire while TTS frames are flowing, even
    though the bot is not yet audibly speaking (pre-speech clipping case)."""
    w = _make_watcher()
    w.reset()
    fired = asyncio.Event()

    async def cb():
        fired.set()

    w.schedule_after_speech(cb, timeout=0.5, max_wait=10.0, label="test")
    loop = asyncio.get_event_loop()
    # Simulate ongoing TTS synthesis for 1.2 s (> silent grace of 0.5 s).
    end = loop.time() + 1.2
    while loop.time() < end:
        w._last_tts_activity = loop.time()
        await asyncio.sleep(0.1)
    assert not fired.is_set(), "watchdog fired while TTS was still active"
    # Now speech "completes" — callback fires via the done event path.
    w._speaking_done.set()
    cb2 = w._on_done_callback
    w._on_done_callback = None
    if cb2 is not None:
        await cb2()
    await asyncio.wait_for(fired.wait(), timeout=2.0)
    w.clear_callback()


@pytest.mark.asyncio
async def test_silent_grace_fires_when_truly_silent():
    """With no TTS activity and no speech, the grace timeout fires the callback
    so the action is never lost."""
    w = _make_watcher()
    w.reset()
    fired = asyncio.Event()

    async def cb():
        fired.set()

    t0 = time.monotonic()
    w.schedule_after_speech(cb, timeout=0.4, max_wait=10.0, label="test")
    await asyncio.wait_for(fired.wait(), timeout=3.0)
    assert time.monotonic() - t0 >= 0.35


@pytest.mark.asyncio
async def test_stale_tts_activity_does_not_starve_guard():
    """TTS activity recorded BEFORE scheduling (an earlier utterance) must not
    re-arm the guard — only activity at/after scheduling counts."""
    w = _make_watcher()
    loop = asyncio.get_event_loop()
    w._last_tts_activity = loop.time()  # stale: pre-scheduling activity
    await asyncio.sleep(0.05)
    w.reset()
    fired = asyncio.Event()

    async def cb():
        fired.set()

    w.schedule_after_speech(cb, timeout=0.4, max_wait=10.0, label="test")
    # No new activity after scheduling → grace timeout fires, well before max_wait.
    await asyncio.wait_for(fired.wait(), timeout=3.0)


@pytest.mark.asyncio
async def test_hard_cap_fires_even_with_constant_tts_activity():
    """max_wait is the absolute ceiling regardless of activity — a stuck
    pipeline can never strand the caller."""
    w = _make_watcher()
    w.reset()
    w._bot_speaking = True  # never stops "speaking"
    fired = asyncio.Event()

    async def cb():
        fired.set()

    w.schedule_after_speech(cb, timeout=0.3, max_wait=1.0, label="test")
    await asyncio.wait_for(fired.wait(), timeout=4.0)


@pytest.mark.asyncio
async def test_process_frame_tracks_tts_activity():
    w = TtsCompletionWatcher()
    assert w._last_tts_activity is None
    frame = TTSAudioRawFrame(audio=b"\x00\x00", sample_rate=8000, num_channels=1)
    # Bypass FrameProcessor plumbing: only exercise our state tracking.
    w.push_frame = AsyncMock()
    import pipecat.processors.frame_processor as _fp

    orig = _fp.FrameProcessor.process_frame

    async def _noop_super(self, frame, direction):
        return None

    _fp.FrameProcessor.process_frame = _noop_super
    try:
        await TtsCompletionWatcher.process_frame(w, frame, FrameDirection.DOWNSTREAM)
        assert w._last_tts_activity is not None
        w._bot_speaking = True
        await TtsCompletionWatcher.process_frame(
            w, BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM
        )
        assert w._bot_speaking is False
        await TtsCompletionWatcher.process_frame(
            w, BotStartedSpeakingFrame(), FrameDirection.DOWNSTREAM
        )
        assert w._bot_speaking is True
    finally:
        _fp.FrameProcessor.process_frame = orig


@pytest.mark.asyncio
async def test_context_bound_without_watcher_defers_by_estimate(monkeypatch):
    """Context-completion with NO TtsCompletionWatcher is a degraded path: the
    terminal callback must be deferred by the length-scaled estimate, never run
    immediately (context completion ≠ audio reached Twilio)."""
    m = _bare_mapper()

    class _StubTts:
        def __init__(self):
            self.cbs = {}

        def register_context_done_callback(self, ctx_id, cb):
            self.cbs[ctx_id] = cb

    m._tts_service = _StubTts()
    m._tts_completion_watcher = None  # no watcher → degraded branch

    delays: list[float] = []
    order: list[str] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(secs):
        delays.append(secs)
        order.append("sleep")
        await real_sleep(0)

    monkeypatch.setattr(
        "botelier.voice.function_mapper.asyncio.sleep", fake_sleep
    )

    async def cb():
        order.append("terminal")

    text = "x" * 400  # ~30 s estimate
    m._run_after_speech(cb, label="Transfer", context_id="ctx-1", speech_text=text)
    assert "ctx-1" in m._tts_service.cbs
    await m._tts_service.cbs["ctx-1"]()  # simulate on_audio_context_completed
    assert order == ["sleep", "terminal"], "callback ran before the degraded wait"
    assert delays == [pytest.approx(max(3.0, estimate_playback_secs(text)))]


# ── _run_after_speech no-watcher fallback scaling ───────────────────────────


@pytest.mark.asyncio
async def test_fallback_delay_scales_with_announcement(monkeypatch):
    m = _bare_mapper()
    delays: list[float] = []
    ran = asyncio.Event()

    real_sleep = asyncio.sleep

    async def fake_sleep(secs):
        delays.append(secs)
        await real_sleep(0)

    monkeypatch.setattr(
        "botelier.voice.function_mapper.asyncio.sleep", fake_sleep
    )

    async def cb():
        ran.set()

    long_text = "x" * 400  # ~30 s estimate — well above the 3 s floor
    m._run_after_speech(cb, label="Transfer", speech_text=long_text)
    await asyncio.wait_for(ran.wait(), timeout=2.0)
    assert delays == [pytest.approx(max(3.0, estimate_playback_secs(long_text)))]
    assert delays[0] > 3.0

    # Unknown text keeps the legacy 3 s floor.
    delays.clear()
    ran.clear()
    m._run_after_speech(cb, label="Transfer")
    await asyncio.wait_for(ran.wait(), timeout=2.0)
    assert delays == [3.0]
