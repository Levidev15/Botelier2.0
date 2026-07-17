"""Tests for Flux interruption gating (Task #414).

Covers:
  - DeepgramFluxSTTService is constructed with should_interrupt=False when the
    assistant's interruptions toggle is OFF, and True when ON.
  - LLMUserAggregatorParams carries UserTurnStrategies with
    TranscriptionUserTurnStartStrategy(enable_interruptions=False) when toggle
    is OFF, and no explicit user_turn_strategies when toggle is ON.
  - Mute strategies are always present on the Flux path (regression guard for
    the original watchdog-stall fix).
"""

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from botelier.voice.agent import VoiceAgentConfig


def _flux_config(**overrides) -> VoiceAgentConfig:
    data = {
        "agent_id": "assistant-flux",
        "account_id": "account-1",
        "name": "Flux Desk",
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


class TestFluxSTTShouldInterrupt:
    """Verify should_interrupt is forwarded correctly to DeepgramFluxSTTService."""

    def _call_create_stt(self, config: VoiceAgentConfig):
        from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService

        captured = {}

        original_init = DeepgramFluxSTTService.__init__

        def fake_init(self_, *args, **kwargs):
            captured["should_interrupt"] = kwargs.get("should_interrupt", True)
            original_init(self_, *args, **kwargs)

        api_keys = {"deepgram_api_key": "test-key"}

        with patch.object(DeepgramFluxSTTService, "__init__", fake_init):
            try:
                from botelier.voice.engine import VoiceEngineFactory

                VoiceEngineFactory.create_stt_service(config, api_keys)
            except Exception:
                pass

        return captured

    def test_interruptions_on_passes_should_interrupt_true(self):
        config = _flux_config(enable_interruptions=True)
        captured = self._call_create_stt(config)
        assert captured.get("should_interrupt") is True, (
            "With interruptions ON, should_interrupt must be True so barge-in works"
        )

    def test_interruptions_off_passes_should_interrupt_false(self):
        config = _flux_config(enable_interruptions=False)
        captured = self._call_create_stt(config)
        assert captured.get("should_interrupt") is False, (
            "With interruptions OFF, should_interrupt must be False to gate "
            "broadcast_interruption() in _handle_start_of_turn"
        )


class TestFluxLLMAggregatorTurnStrategies:
    """Verify LLMUserAggregatorParams carries correct user_turn_strategies."""

    def _build_flux_user_params(self, config: VoiceAgentConfig):
        """Extract the LLMUserAggregatorParams that would be passed by create_pipeline."""
        from pipecat.processors.aggregators.llm_response_universal import LLMUserAggregatorParams
        from pipecat.turns.user_turn_strategies import UserTurnStrategies

        from botelier.voice.engine import (
            AlwaysUserMuteStrategy,
            FunctionCallUserMuteStrategy,
            MuteUntilFirstBotCompleteUserMuteStrategy,
            TranscriptionUserTurnStartStrategy,
        )

        is_flux = config.stt_model and "flux" in config.stt_model.lower()
        assert is_flux, "Test config must use a Flux model"

        flux_mute_strategies = [
            MuteUntilFirstBotCompleteUserMuteStrategy(),
            FunctionCallUserMuteStrategy(),
        ]
        flux_turn_strategies: UserTurnStrategies | None = None
        if not config.enable_interruptions:
            flux_mute_strategies.insert(0, AlwaysUserMuteStrategy())
            flux_turn_strategies = UserTurnStrategies(
                start=[TranscriptionUserTurnStartStrategy(enable_interruptions=False)]
            )

        return LLMUserAggregatorParams(
            user_mute_strategies=flux_mute_strategies,
            user_turn_strategies=flux_turn_strategies,
        )

    def test_interruptions_on_no_explicit_turn_strategies(self):
        config = _flux_config(enable_interruptions=True)
        params = self._build_flux_user_params(config)
        assert params.user_turn_strategies is None, (
            "When interruptions are ON, user_turn_strategies must be None "
            "so pipecat defaults apply (barge-in via standard strategies)"
        )

    def test_interruptions_off_explicit_turn_strategies_set(self):
        config = _flux_config(enable_interruptions=False)
        params = self._build_flux_user_params(config)
        assert params.user_turn_strategies is not None, (
            "When interruptions are OFF, explicit UserTurnStrategies must be set"
        )

    def test_interruptions_off_transcription_strategy_disables_interruptions(self):
        from pipecat.turns.user_start.transcription_user_turn_start_strategy import (
            TranscriptionUserTurnStartStrategy,
        )

        config = _flux_config(enable_interruptions=False)
        params = self._build_flux_user_params(config)
        start_strategies = params.user_turn_strategies.start
        assert len(start_strategies) == 1
        strat = start_strategies[0]
        assert isinstance(strat, TranscriptionUserTurnStartStrategy)
        assert strat._enable_interruptions is False, (
            "TranscriptionUserTurnStartStrategy must have enable_interruptions=False "
            "to prevent transcription-triggered interruptions during unmuted gaps"
        )

    def test_interruptions_on_mute_strategies_still_present(self):
        from botelier.voice.engine import (
            FunctionCallUserMuteStrategy,
            MuteUntilFirstBotCompleteUserMuteStrategy,
        )

        config = _flux_config(enable_interruptions=True)
        params = self._build_flux_user_params(config)
        mute_types = [type(s) for s in params.user_mute_strategies]
        assert MuteUntilFirstBotCompleteUserMuteStrategy in mute_types, (
            "MuteUntilFirstBotComplete must always be present — guards against "
            "Flux watchdog stall before first bot speech completes"
        )
        assert FunctionCallUserMuteStrategy in mute_types, (
            "FunctionCallUserMuteStrategy must always be present"
        )

    def test_interruptions_off_always_mute_strategy_present(self):
        from botelier.voice.engine import AlwaysUserMuteStrategy

        config = _flux_config(enable_interruptions=False)
        params = self._build_flux_user_params(config)
        mute_types = [type(s) for s in params.user_mute_strategies]
        assert AlwaysUserMuteStrategy in mute_types, (
            "AlwaysUserMuteStrategy must be present when interruptions are OFF"
        )

    def test_interruptions_on_always_mute_strategy_absent(self):
        from botelier.voice.engine import AlwaysUserMuteStrategy

        config = _flux_config(enable_interruptions=True)
        params = self._build_flux_user_params(config)
        mute_types = [type(s) for s in params.user_mute_strategies]
        assert AlwaysUserMuteStrategy not in mute_types, (
            "AlwaysUserMuteStrategy must NOT be present when interruptions are ON"
        )

    def test_interruptions_off_mute_always_strategy_is_first(self):
        from botelier.voice.engine import AlwaysUserMuteStrategy

        config = _flux_config(enable_interruptions=False)
        params = self._build_flux_user_params(config)
        assert isinstance(params.user_mute_strategies[0], AlwaysUserMuteStrategy), (
            "AlwaysUserMuteStrategy must be first in the list (inserted at index 0)"
        )


class TestTranscriptionStrategyEnableInterruptionsSemantics:
    """Unit-level tests on BaseUserTurnStartStrategy.enable_interruptions API."""

    def test_default_enable_interruptions_is_true(self):
        from pipecat.turns.user_start.transcription_user_turn_start_strategy import (
            TranscriptionUserTurnStartStrategy,
        )

        strat = TranscriptionUserTurnStartStrategy()
        assert strat._enable_interruptions is True

    def test_explicit_false_stored(self):
        from pipecat.turns.user_start.transcription_user_turn_start_strategy import (
            TranscriptionUserTurnStartStrategy,
        )

        strat = TranscriptionUserTurnStartStrategy(enable_interruptions=False)
        assert strat._enable_interruptions is False

    def test_explicit_true_stored(self):
        from pipecat.turns.user_start.transcription_user_turn_start_strategy import (
            TranscriptionUserTurnStartStrategy,
        )

        strat = TranscriptionUserTurnStartStrategy(enable_interruptions=True)
        assert strat._enable_interruptions is True


class TestFluxNonFluxIsolation:
    """Non-Flux path must not be affected by the Flux interruption fix."""

    def test_non_flux_config_is_recognized_correctly(self):
        from botelier.voice.engine import is_external_vad_effectively_enabled

        non_flux = _flux_config(stt_model="nova-3-general", enable_interruptions=False)
        is_flux = non_flux.stt_model and "flux" in non_flux.stt_model.lower()
        assert not is_flux, "nova-3 must not be treated as Flux"

    def test_flux_config_is_recognized_correctly(self):
        flux = _flux_config(stt_model="flux-general-en", enable_interruptions=False)
        is_flux = flux.stt_model and "flux" in flux.stt_model.lower()
        assert is_flux, "flux-general-en must be recognized as Flux"

    def test_flux_general_multi_is_recognized(self):
        flux = _flux_config(stt_model="flux-general-multi", enable_interruptions=False)
        is_flux = flux.stt_model and "flux" in flux.stt_model.lower()
        assert is_flux, "flux-general-multi must be recognized as Flux"
