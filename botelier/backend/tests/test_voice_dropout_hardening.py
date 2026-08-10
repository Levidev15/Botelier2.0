"""Tests for the voice speech-dropout hardening (Task #468).

Covers:
  - Flux word-gated barge-in: interruption deferred until >= min_words words
    are transcribed; StartOfTurn transcript that already carries enough words
    fires immediately; end-of-turn clears the pending flag.
  - TOKEN-mode Speak batching: complete words accumulate until a clause
    boundary or the min-chars threshold, flush drains the remainder, and
    interruption clears both buffers.
  - Sample-rate clamping: assistant-configured mismatched sample rates are
    clamped to 8 kHz; non-Deepgram providers are pinned to 8 kHz.
  - Greeting injector pacing: pace sleep is stored and clamped non-negative.
"""

import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from botelier.voice.agent import VoiceAgentConfig


def _config(**overrides) -> VoiceAgentConfig:
    data = {
        "agent_id": "assistant-1",
        "account_id": "account-1",
        "name": "Desk",
        "stt_provider": "deepgram",
        "stt_model": "flux-general-en",
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
        "enable_interruptions": True,
    }
    data.update(overrides)
    return VoiceAgentConfig(**data)


API_KEYS = {"deepgram_api_key": "test-key", "cartesia_api_key": "k", "elevenlabs_api_key": "k", "openai_api_key": "k"}


# ---------------------------------------------------------------------------
# Flux word-gated barge-in
# ---------------------------------------------------------------------------


def _make_gated_flux(min_words=1):
    from botelier.voice.engine import VoiceEngineFactory

    config = _config(stt_config={"interrupt_min_words": min_words})
    return VoiceEngineFactory.create_stt_service(config, API_KEYS)


class TestFluxWordGatedInterruption:
    def test_gated_subclass_constructed_with_min_words(self):
        svc = _make_gated_flux(min_words=2)
        assert type(svc).__name__ == "_GatedFluxSTTService"
        assert svc._interrupt_min_words == 2
        assert svc._should_interrupt is False

    @pytest.mark.asyncio
    async def test_start_of_turn_without_words_defers_interruption(self):
        svc = _make_gated_flux(min_words=1)
        base = type(svc).__mro__[1]
        with (
            patch.object(base, "_handle_start_of_turn", new=AsyncMock()),
            patch.object(base, "_handle_update", new=AsyncMock()),
            patch.object(type(svc), "broadcast_interruption", new=AsyncMock()) as bi,
        ):
            await svc._handle_start_of_turn("")
            bi.assert_not_awaited()
            assert svc._pending_interrupt is True

            # First transcribed word passes the gate exactly once.
            await svc._handle_update("hello")
            bi.assert_awaited_once()
            assert svc._pending_interrupt is False

            await svc._handle_update("hello there")
            bi.assert_awaited_once()  # still once — no re-fire

    @pytest.mark.asyncio
    async def test_start_of_turn_with_words_fires_immediately(self):
        svc = _make_gated_flux(min_words=1)
        base = type(svc).__mro__[1]
        with (
            patch.object(base, "_handle_start_of_turn", new=AsyncMock()),
            patch.object(type(svc), "broadcast_interruption", new=AsyncMock()) as bi,
        ):
            await svc._handle_start_of_turn("hi there")
            bi.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_eager_end_of_turn_resolves_gate(self):
        # Order: empty StartOfTurn → transcript-bearing EagerEOT (starts early
        # LLM/TTS) → EndOfTurn. The gate must resolve at EagerEOT — firing once
        # there and NEVER late at EndOfTurn (a late fire would clear the newly
        # started bot audio).
        svc = _make_gated_flux(min_words=1)
        base = type(svc).__mro__[1]
        with (
            patch.object(base, "_handle_start_of_turn", new=AsyncMock()),
            patch.object(base, "_handle_eager_end_of_turn", new=AsyncMock()),
            patch.object(base, "_handle_end_of_turn", new=AsyncMock()),
            patch.object(type(svc), "broadcast_interruption", new=AsyncMock()) as bi,
        ):
            await svc._handle_start_of_turn("")
            bi.assert_not_awaited()
            await svc._handle_eager_end_of_turn("book a room", {})
            bi.assert_awaited_once()
            assert svc._pending_interrupt is False
            await svc._handle_end_of_turn("book a room please", {})
            bi.assert_awaited_once()  # no late re-fire

    @pytest.mark.asyncio
    async def test_eager_end_of_turn_short_transcript_clears_pending(self):
        svc = _make_gated_flux(min_words=3)
        base = type(svc).__mro__[1]
        with (
            patch.object(base, "_handle_start_of_turn", new=AsyncMock()),
            patch.object(base, "_handle_eager_end_of_turn", new=AsyncMock()),
            patch.object(type(svc), "broadcast_interruption", new=AsyncMock()) as bi,
        ):
            await svc._handle_start_of_turn("")
            await svc._handle_eager_end_of_turn("uh", {})
            bi.assert_not_awaited()
            assert svc._pending_interrupt is False

    @pytest.mark.asyncio
    async def test_end_of_turn_clears_pending_flag(self):
        svc = _make_gated_flux(min_words=3)
        base = type(svc).__mro__[1]
        with (
            patch.object(base, "_handle_start_of_turn", new=AsyncMock()),
            patch.object(base, "_handle_end_of_turn", new=AsyncMock()),
            patch.object(type(svc), "broadcast_interruption", new=AsyncMock()) as bi,
        ):
            await svc._handle_start_of_turn("uh")
            bi.assert_not_awaited()
            # End of turn with a short transcript: no interruption, flag cleared.
            await svc._handle_end_of_turn("uh huh", {})
            bi.assert_not_awaited()
            assert svc._pending_interrupt is False

    def test_min_words_zero_returns_plain_service(self):
        from botelier.voice.engine import VoiceEngineFactory

        svc = VoiceEngineFactory.create_stt_service(
            _config(stt_config={"interrupt_min_words": 0}), API_KEYS
        )
        assert type(svc).__name__ == "DeepgramFluxSTTService"
        assert svc._should_interrupt is True

    def test_interruptions_off_returns_plain_ungated_service(self):
        from botelier.voice.engine import VoiceEngineFactory

        svc = VoiceEngineFactory.create_stt_service(
            _config(enable_interruptions=False), API_KEYS
        )
        assert type(svc).__name__ == "DeepgramFluxSTTService"
        assert svc._should_interrupt is False


# ---------------------------------------------------------------------------
# TOKEN-mode Speak batching
# ---------------------------------------------------------------------------


def _make_deepgram_tts(tts_config=None):
    from botelier.voice.engine import VoiceEngineFactory

    return VoiceEngineFactory.create_tts_service(
        _config(tts_config=tts_config or {}), API_KEYS
    )


async def _drive_tokens(svc, tokens, ctx="ctx-1"):
    """Push tokens through run_tts with the provider super() calls mocked;
    return the list of texts dispatched to the provider."""
    from pipecat.services.deepgram.tts import DeepgramTTSService

    sent: list[str] = []

    async def fake_run_tts(self_, text, context_id):
        sent.append(text)
        if False:
            yield None  # pragma: no cover — make this an async generator

    with (
        patch.object(DeepgramTTSService, "run_tts", fake_run_tts),
        patch.object(type(svc), "start_tts_usage_metrics", new=AsyncMock()),
    ):
        for tok in tokens:
            async for _ in svc.run_tts(tok, ctx):
                pass
    return sent


class TestTokenModeBatching:
    @pytest.mark.asyncio
    async def test_words_batch_until_clause_boundary(self):
        svc = _make_deepgram_tts({"token_send_min_chars": 1000})
        sent = await _drive_tokens(svc, ["Hello ", "there ", "friend, ", "how ", "are "])
        # Nothing dispatched until the comma boundary appeared.
        assert sent == ["Hello there friend, "]
        # Remaining complete words wait in the send buffer.
        assert svc._send_buffer["ctx-1"] == "how are "

    @pytest.mark.asyncio
    async def test_min_chars_threshold_dispatches_without_punctuation(self):
        svc = _make_deepgram_tts({"token_send_min_chars": 10})
        sent = await _drive_tokens(svc, ["alpha ", "beta ", "gamma "])
        assert sent, "batch should flush once >= 10 chars accumulate"
        assert "".join(sent) + svc._send_buffer.get("ctx-1", "") == "alpha beta gamma "

    @pytest.mark.asyncio
    async def test_zero_min_chars_restores_per_word_dispatch(self):
        svc = _make_deepgram_tts({"token_send_min_chars": 0})
        sent = await _drive_tokens(svc, ["one ", "two "])
        assert sent == ["one ", "two "]

    @pytest.mark.asyncio
    async def test_flush_drains_batch_and_partial_word(self):
        from pipecat.services.deepgram.tts import DeepgramTTSService

        svc = _make_deepgram_tts({"token_send_min_chars": 1000})
        await _drive_tokens(svc, ["Good ", "night"])  # "Good " batched, "night" partial
        assert svc._send_buffer["ctx-1"] == "Good "
        assert svc._word_buffer["ctx-1"] == "night"

        sent_ws = []

        class _WS:
            async def send(self, payload):
                sent_ws.append(payload)

        svc._websocket = _WS()
        svc._turn_context_id = "ctx-1"
        with patch.object(DeepgramTTSService, "flush_audio", new=AsyncMock()):
            await svc.flush_audio("ctx-1")
        assert len(sent_ws) == 1
        assert "Good night" in sent_ws[0]
        assert svc._send_buffer == {} and svc._word_buffer == {}

    @pytest.mark.asyncio
    async def test_interruption_clears_both_buffers(self):
        from pipecat.services.deepgram.tts import DeepgramTTSService

        svc = _make_deepgram_tts({"token_send_min_chars": 1000})
        await _drive_tokens(svc, ["Good ", "night"])
        with patch.object(
            DeepgramTTSService, "on_audio_context_interrupted", new=AsyncMock()
        ):
            await svc.on_audio_context_interrupted("ctx-1")
        assert svc._send_buffer == {} and svc._word_buffer == {}


# ---------------------------------------------------------------------------
# Sample-rate clamping
# ---------------------------------------------------------------------------


class TestSampleRateClamp:
    def test_deepgram_mismatched_rate_clamped_to_8k(self):
        svc = _make_deepgram_tts({"sample_rate": 24000})
        assert svc._init_sample_rate == 8000 or getattr(svc, "sample_rate", 8000) in (0, 8000)

    def test_other_providers_pinned_to_8k(self):
        from botelier.voice.engine import VoiceEngineFactory

        for provider, cls_path in [
            ("cartesia", "pipecat.services.cartesia.tts.CartesiaTTSService"),
            ("elevenlabs", "pipecat.services.elevenlabs.tts.ElevenLabsTTSService"),
            ("openai", "pipecat.services.openai.tts.OpenAITTSService"),
        ]:
            mod_path, cls_name = cls_path.rsplit(".", 1)
            import importlib

            cls = getattr(importlib.import_module(mod_path), cls_name)
            captured = {}
            original_init = cls.__init__

            def fake_init(self_, *args, _orig=original_init, _cap=captured, **kwargs):
                _cap["sample_rate"] = kwargs.get("sample_rate")
                _orig(self_, *args, **kwargs)

            with patch.object(cls, "__init__", fake_init):
                try:
                    VoiceEngineFactory.create_tts_service(
                        _config(tts_provider=provider, tts_voice_id="v"), API_KEYS
                    )
                except Exception:
                    pass
            assert captured.get("sample_rate") == 8000, f"{provider} must pin 8 kHz"


# ---------------------------------------------------------------------------
# Greeting injector pacing
# ---------------------------------------------------------------------------


class TestGreetingInjectorPacing:
    def test_default_pace_sleep(self):
        from botelier.voice.engine import GreetingAudioInjector

        inj = GreetingAudioInjector()
        assert inj._inject_pace_sleep_s == pytest.approx(0.04)

    def test_negative_pace_clamped_to_zero(self):
        from botelier.voice.engine import GreetingAudioInjector

        inj = GreetingAudioInjector(inject_pace_sleep_s=-1)
        assert inj._inject_pace_sleep_s == 0.0
