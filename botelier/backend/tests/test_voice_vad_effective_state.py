"""Tests for effective external VAD gating."""

import os
import time
from unittest.mock import AsyncMock

import pytest
from pipecat.frames.frames import AudioRawFrame
from pipecat.processors.frame_processor import FrameDirection

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from botelier.voice.agent import VoiceAgentConfig
from botelier.voice.engine import VadSuspicionTracker, is_external_vad_effectively_enabled


class _EventQueue:
    def __init__(self):
        self.events = []

    def log(self, event_type, event_source="pipecat", severity="info", details=None):
        self.events.append(
            {
                "event_type": event_type,
                "event_source": event_source,
                "severity": severity,
                "details": details or {},
            }
        )


def _voice_config(**overrides) -> VoiceAgentConfig:
    data = {
        "agent_id": "assistant-1",
        "account_id": "account-1",
        "name": "Front Desk",
        "stt_provider": "deepgram",
        "stt_model": "nova-3",
        "stt_config": {},
        "llm_provider": "openai",
        "llm_model": "gpt-4.1-mini",
        "llm_config": {},
        "tts_provider": "deepgram",
        "tts_model": "aura-2",
        "tts_voice_id": "aura-2-helena-en",
        "tts_config": {},
        "enable_vad": False,
        "vad_provider": None,
        "vad_config": {},
    }
    data.update(overrides)
    return VoiceAgentConfig(**data)


def test_external_vad_effective_state_requires_enabled_silero_non_flux():
    assert (
        is_external_vad_effectively_enabled(
            _voice_config(enable_vad=True, vad_provider="silero")
        )
        is True
    )
    assert (
        is_external_vad_effectively_enabled(
            _voice_config(enable_vad=False, vad_provider="silero")
        )
        is False
    )
    assert (
        is_external_vad_effectively_enabled(
            _voice_config(enable_vad=True, vad_provider="webrtc")
        )
        is False
    )
    assert (
        is_external_vad_effectively_enabled(
            _voice_config(
                enable_vad=True,
                vad_provider="silero",
                stt_model="flux-general-en",
            )
        )
        is False
    )


@pytest.mark.asyncio
async def test_vad_suspicion_tracker_does_not_emit_when_disabled():
    timing_state = {
        "stt_muted": False,
        "t_last_inbound": time.monotonic(),
        "vad_missed_speech_window_s": 10.0,
    }
    event_queue = _EventQueue()
    tracker = VadSuspicionTracker(
        timing_state=timing_state,
        event_queue=event_queue,
        enabled=False,
    )
    tracker.push_frame = AsyncMock()

    await tracker.process_frame(
        AudioRawFrame(audio=b"\0" * 160, sample_rate=8000, num_channels=1),
        FrameDirection.DOWNSTREAM,
    )

    assert event_queue.events == []


@pytest.mark.asyncio
async def test_vad_suspicion_tracker_can_emit_when_enabled():
    timing_state = {
        "stt_muted": False,
        "t_last_inbound": time.monotonic(),
        "vad_missed_speech_window_s": 10.0,
    }
    event_queue = _EventQueue()
    tracker = VadSuspicionTracker(
        timing_state=timing_state,
        event_queue=event_queue,
        enabled=True,
    )
    tracker.push_frame = AsyncMock()

    await tracker.process_frame(
        AudioRawFrame(audio=b"\0" * 160, sample_rate=8000, num_channels=1),
        FrameDirection.DOWNSTREAM,
    )

    assert [event["event_type"] for event in event_queue.events] == [
        "vad_missed_speech_suspected"
    ]
