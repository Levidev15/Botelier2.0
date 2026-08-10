"""Tests for the per-turn latency telemetry additions (Task #473).

Covers:
  - TtsAudioGapTracker per-turn aggregation: gap count/worst-gap accumulate,
    caller-audible stutter (>100 ms) emits a ``tts_audio_gap`` event at the
    next turn boundary, sub-audible turns stay silent, counters reset per turn.
  - TtsPipelineLatencyTracker TTFB capture: TTFBMetricsData from MetricsFrame
    is keyed by service kind into timing_state and stamped onto the
    ``turn_latency`` event details, popped so later turns show nulls.
"""

import asyncio
import os
import time
from unittest.mock import patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from pipecat.frames.frames import (
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    MetricsFrame,
    TTSAudioRawFrame,
)
from pipecat.metrics.metrics import TTFBMetricsData
from pipecat.processors.frame_processor import FrameDirection

from botelier.voice.engine import TtsAudioGapTracker, TtsPipelineLatencyTracker


class _EventQueue:
    def __init__(self):
        self.events = []

    def log(self, event_type, event_source=None, severity=None, details=None):
        self.events.append({"type": event_type, "severity": severity, "details": details or {}})


def _audio_frame():
    return TTSAudioRawFrame(audio=b"\x00" * 320, sample_rate=8000, num_channels=1)


async def _feed(proc, frame):
    async def _noop(*a, **k):
        return None

    with (
        patch.object(type(proc).__mro__[1], "process_frame", new=_noop),
        patch.object(proc, "push_frame", new=_noop),
    ):
        await proc.process_frame(frame, FrameDirection.DOWNSTREAM)


class TestGapTrackerAggregation:
    @pytest.mark.asyncio
    async def test_audible_gap_emits_event_at_turn_boundary(self, monkeypatch):
        q = _EventQueue()
        ts = {"turn_index": 3}
        t = TtsAudioGapTracker(timing_state=ts, event_queue=q)
        await _feed(t, LLMFullResponseStartFrame())
        clock = [100.0]
        monkeypatch.setattr(time, "monotonic", lambda: clock[0])
        await _feed(t, _audio_frame())
        clock[0] += 0.020  # 20 ms — under threshold
        await _feed(t, _audio_frame())
        clock[0] += 0.150  # 150 ms — audible gap
        await _feed(t, _audio_frame())
        assert q.events == []  # nothing until turn boundary
        await _feed(t, LLMFullResponseStartFrame())
        assert len(q.events) == 1
        ev = q.events[0]
        assert ev["type"] == "tts_audio_gap" and ev["severity"] == "warning"
        assert ev["details"]["turn_index"] == 3
        assert ev["details"]["gap_count"] == 1
        assert ev["details"]["max_gap_ms"] == pytest.approx(150, abs=2)
        # Counters reset for the new turn.
        assert t._gap_count == 0 and t._max_gap_s == 0.0

    @pytest.mark.asyncio
    async def test_gap_attributed_to_originating_response_turn(self, monkeypatch):
        """A stutter in turn N must be reported as turn N even when the NEXT
        user turn has already advanced timing_state['turn_index'] before the
        flush fires at the next LLMFullResponseStartFrame."""
        q = _EventQueue()
        ts = {"turn_index": 5}
        t = TtsAudioGapTracker(timing_state=ts, event_queue=q)
        await _feed(t, LLMFullResponseStartFrame())  # response for turn 5
        clock = [200.0]
        monkeypatch.setattr(time, "monotonic", lambda: clock[0])
        await _feed(t, _audio_frame())
        clock[0] += 0.200  # audible gap during turn 5's response
        await _feed(t, _audio_frame())
        # Next user turn finalizes before the flush — index advances.
        ts["turn_index"] = 6
        await _feed(t, LLMFullResponseStartFrame())
        assert q.events[0]["details"]["turn_index"] == 5
        # And the new aggregation window is bound to turn 6.
        assert t._resp_turn_index == 6

    @pytest.mark.asyncio
    async def test_sub_audible_gaps_do_not_emit_event(self, monkeypatch):
        q = _EventQueue()
        t = TtsAudioGapTracker(timing_state={}, event_queue=q)
        clock = [50.0]
        monkeypatch.setattr(time, "monotonic", lambda: clock[0])
        await _feed(t, _audio_frame())
        clock[0] += 0.050  # 50 ms — measured but not audible
        await _feed(t, _audio_frame())
        assert t._gap_count == 1
        await _feed(t, LLMFullResponseStartFrame())
        assert q.events == []
        assert t._gap_count == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("terminal_frame_name", ["end", "cancel"])
    async def test_terminal_frame_flushes_final_turn_gap(self, monkeypatch, terminal_frame_name):
        """An audible stutter in the LAST response of a call must still emit —
        End/Cancel flush the aggregation (no next response start exists),
        keeping the originating response's turn index."""
        from pipecat.frames.frames import CancelFrame, EndFrame

        q = _EventQueue()
        ts = {"turn_index": 7}
        t = TtsAudioGapTracker(timing_state=ts, event_queue=q)
        await _feed(t, LLMFullResponseStartFrame())  # final response, turn 7
        clock = [300.0]
        monkeypatch.setattr(time, "monotonic", lambda: clock[0])
        await _feed(t, _audio_frame())
        clock[0] += 0.180  # audible gap
        await _feed(t, _audio_frame())
        ts["turn_index"] = 8  # a stray user turn finalizes before teardown
        terminal = EndFrame() if terminal_frame_name == "end" else CancelFrame()
        await _feed(t, terminal)
        assert len(q.events) == 1
        assert q.events[0]["type"] == "tts_audio_gap"
        assert q.events[0]["details"]["turn_index"] == 7
        assert q.events[0]["details"]["max_gap_ms"] == pytest.approx(180, abs=2)

    @pytest.mark.asyncio
    async def test_inter_turn_silence_not_counted(self, monkeypatch):
        t = TtsAudioGapTracker(timing_state={})
        clock = [10.0]
        monkeypatch.setattr(time, "monotonic", lambda: clock[0])
        await _feed(t, _audio_frame())
        await _feed(t, LLMFullResponseStartFrame())  # resets _last_audio_t
        clock[0] += 5.0  # long inter-turn silence
        await _feed(t, _audio_frame())
        assert t._gap_count == 0


class TestTtfbCapture:
    def _tracker(self):
        q = _EventQueue()
        ts = {"turn_index": 1, "t_stt": 1.0, "t_llm_start": 1.2, "t_last_inbound": 0.9}
        tr = TtsPipelineLatencyTracker(call_start_mono=0.5, timing_state=ts, event_queue=q)
        return tr, ts, q

    @pytest.mark.asyncio
    async def test_ttfb_metrics_keyed_by_service_kind(self):
        tr, ts, _ = self._tracker()
        frame = MetricsFrame(
            data=[
                TTFBMetricsData(processor="DeepgramTTSService#0", value=0.21),
                TTFBMetricsData(processor="OpenAILLMService#0", value=0.63),
                TTFBMetricsData(processor="DeepgramFluxSTTService#0", value=0.09),
            ]
        )
        await _feed(tr, frame)
        assert ts["tts_ttfb_ms"] == 210
        assert ts["llm_ttfb_ms"] == 630
        assert ts["stt_ttfb_ms"] == 90

    @pytest.mark.asyncio
    async def test_ttfb_stamped_on_turn_latency_and_popped(self):
        tr, ts, q = self._tracker()
        ts["tts_ttfb_ms"] = 200
        ts["llm_ttfb_ms"] = 600
        tr._t_first_audio = 2.0
        tr._emit_turn_latency(t_llm_end=1.9)
        # TTS TTFB was already staged (pipecat pushes it before first audio),
        # so the event flushes immediately.
        assert len(q.events) == 1
        assert tr._pending_turn_event is None
        d = q.events[0]["details"]
        assert d["tts_ttfb_ms"] == 200 and d["llm_ttfb_ms"] == 600
        assert "stt_ttfb_ms" not in d  # absent metric stays absent
        # Popped — a later turn without fresh metrics carries no stale TTFB.
        assert "tts_ttfb_ms" not in ts and "llm_ttfb_ms" not in ts

    @pytest.mark.asyncio
    async def test_pipecat_ordering_ttfb_metric_before_first_audio(self):
        """Installed pipecat ordering: the TTS base calls stop_ttfb_metrics()
        on the first TTSAudioRawFrame of the context and pushes the
        MetricsFrame BEFORE forwarding that audio frame downstream
        (tts_service.py tts_process_generator). Sequence at this tracker:
        LLM start → LLM TTFB metric → LLM end → TTS TTFB metric → first audio
        (emission). The event must flush immediately at emission with both
        TTFBs attached to the correct turn, and nothing may leak into the
        next turn (whose index advances before its response starts)."""
        tr, ts, q = self._tracker()
        await _feed(tr, LLMFullResponseStartFrame())
        await _feed(
            tr,
            MetricsFrame(data=[TTFBMetricsData(processor="OpenAILLMService#0", value=0.5)]),
        )
        ts["t_llm_end"] = 1.8
        await _feed(tr, LLMFullResponseEndFrame())
        # TTS TTFB metric arrives BEFORE the first audio frame.
        await _feed(
            tr,
            MetricsFrame(data=[TTFBMetricsData(processor="DeepgramTTSService#0", value=0.25)]),
        )
        assert q.events == []
        # First audio triggers emission — flushed immediately (TTFB present).
        await _feed(tr, _audio_frame())
        assert len(q.events) == 1 and tr._pending_turn_event is None
        d1 = q.events[0]["details"]
        assert d1["llm_ttfb_ms"] == 500 and d1["tts_ttfb_ms"] == 250
        assert d1["turn_index"] == 1

        # ── Next user turn advances the index BEFORE its response starts;
        #    that turn emits with NO metrics: nothing may leak. ──
        ts["turn_index"] = 2
        await _feed(tr, LLMFullResponseStartFrame())
        ts["t_llm_end"] = 3.0
        tr._t_first_audio = 3.1
        tr._emit_turn_latency(t_llm_end=3.0)
        tr._flush_pending_turn_event()
        d2 = q.events[1]["details"]
        assert d2["turn_index"] == 2
        assert "tts_ttfb_ms" not in d2 and "llm_ttfb_ms" not in d2

    @pytest.mark.asyncio
    async def test_missing_tts_ttfb_holds_event_without_misattribution(self):
        """When no TTS TTFB is seen (e.g. cached greeting audio), the event is
        held and flushed at the next response start — still carrying its own
        turn_index, even though timing_state has advanced meanwhile."""
        tr, ts, q = self._tracker()
        await _feed(tr, LLMFullResponseStartFrame())
        ts["t_llm_end"] = 1.8
        await _feed(tr, LLMFullResponseEndFrame())
        await _feed(tr, _audio_frame())  # emission — no TTS TTFB staged
        assert q.events == [] and tr._pending_turn_event is not None
        ts["turn_index"] = 2  # next user turn already finalized
        await _feed(tr, LLMFullResponseStartFrame())
        assert len(q.events) == 1
        assert q.events[0]["details"]["turn_index"] == 1  # not misattributed

    @pytest.mark.asyncio
    async def test_pending_event_flushed_at_next_turn_and_at_end(self):
        from pipecat.frames.frames import CancelFrame

        tr, ts, q = self._tracker()
        tr._t_first_audio = 2.0
        tr._emit_turn_latency(t_llm_end=1.9)
        assert q.events == []
        # Next response start flushes the held event (TTS TTFB never arrived).
        await _feed(tr, LLMFullResponseStartFrame())
        assert len(q.events) == 1 and "tts_ttfb_ms" not in q.events[0]["details"]

        # Last turn of the call: held event flushed by Cancel/End.
        tr._turn_emitted = False
        tr._t_first_audio = 4.0
        tr._emit_turn_latency(t_llm_end=3.9)
        assert len(q.events) == 1
        await _feed(tr, CancelFrame())
        assert len(q.events) == 2


class TestDeepgramWsTtsTtfbEmission:
    @pytest.mark.asyncio
    async def test_first_received_audio_chunk_stops_ttfb_once(self):
        """The configured websocket Deepgram TTS never calls stop_ttfb_metrics
        in pipecat (audio arrives via _receive_messages → append_to_audio_context,
        bypassing tts_process_generator). Our subclass must stop TTFB on the
        first received audio chunk — exactly once per synthesis — and push the
        TTFBMetricsData frame downstream."""
        from unittest.mock import AsyncMock, PropertyMock

        from botelier.voice.agent import VoiceAgentConfig
        from botelier.voice.engine import VoiceEngineFactory
        from pipecat.frames.frames import TTSAudioRawFrame as _TTSAudio

        config = VoiceAgentConfig(
            agent_id="a1", account_id="ac1", name="Desk",
            stt_provider="deepgram", stt_model="flux-general-en", stt_config={},
            llm_provider="openai", llm_model="gpt-4.1-mini", llm_config={},
            tts_provider="deepgram", tts_model="aura-2",
            tts_voice_id="aura-2-helena-en", tts_config={},
            enable_vad=False, vad_provider=None, vad_config={},
            enable_interruptions=True,
        )
        svc = VoiceEngineFactory.create_tts_service(config, {"deepgram_api_key": "k"})
        assert svc.can_generate_metrics()

        pushed = []

        async def _capture(frame, *a, **k):
            pushed.append(frame)

        with (
            patch.object(type(svc), "metrics_enabled", new=PropertyMock(return_value=True)),
            patch.object(svc, "push_frame", new=_capture),
            patch.object(
                type(svc).__mro__[1], "append_to_audio_context", new=AsyncMock()
            ),
        ):
            await svc.start_ttfb_metrics()  # armed when synthesis begins
            audio = _TTSAudio(audio=b"\x00" * 320, sample_rate=8000, num_channels=1)
            await svc.append_to_audio_context("ctx-1", audio)
            ttfb_frames = [
                f
                for f in pushed
                if isinstance(f, MetricsFrame)
                and any(isinstance(d, TTFBMetricsData) for d in f.data)
            ]
            assert len(ttfb_frames) == 1, "first audio chunk must emit TTFB"
            # Second chunk: stop is a no-op (not re-armed) — no duplicate.
            await svc.append_to_audio_context("ctx-1", audio)
            ttfb_frames = [
                f
                for f in pushed
                if isinstance(f, MetricsFrame)
                and any(isinstance(d, TTFBMetricsData) for d in f.data)
            ]
            assert len(ttfb_frames) == 1


class TestFluxTtfbAbsence:
    def test_flux_stt_does_not_emit_ttfb_metrics(self):
        """The pipecat fork deliberately disables TTFB start/stop for Deepgram
        Flux (see services/deepgram/flux/base.py), so `stt_ttfb_ms` must be
        documented as absent on the deployed Flux pipeline. This test locks the
        assumption the audit doc relies on — if a fork upgrade re-enables Flux
        TTFB, this fails and the doc/telemetry contract should be revisited."""
        import inspect

        from pipecat.services.deepgram.flux import base as flux_base

        src = inspect.getsource(flux_base)
        # TTFB metric calls are either absent or commented out in the Flux base.
        active_lines = [
            line
            for line in src.splitlines()
            if ("start_ttfb_metrics" in line or "stop_ttfb_metrics" in line)
            and not line.strip().startswith("#")
        ]
        assert active_lines == [], f"Flux now emits TTFB: {active_lines}"
