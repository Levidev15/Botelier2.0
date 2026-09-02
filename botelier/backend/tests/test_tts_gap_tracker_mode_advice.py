"""Tests for TtsAudioGapTracker mode-aware diagnostic advice.

Bug: _flush_turn_summary() and the per-frame debug log always emitted
"consider switching text_aggregation_mode to 'token'" regardless of the
current aggregation mode — misleading developers debugging calls that
were already correctly in token mode.

Fix: the tracker now accepts text_aggregation_mode at construction time
and emits mode-specific advice in the caller-audible INFO summary:
  - SENTENCE mode → "consider switching text_aggregation_mode to 'token'"
  - TOKEN mode    → "consider increasing tts_config.token_send_min_chars"

These tests confirm the correct message appears (or is absent) in each mode.
"""

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

import botelier.voice.engine as _engine_mod
from botelier.voice.engine import TtsAudioGapTracker


def _make_audible_tracker(mode):
    """Return a tracker pre-loaded with an audible gap summary for the given mode."""
    tracker = TtsAudioGapTracker(text_aggregation_mode=mode)
    # Simulate five gaps, worst = 150 ms (above the 100 ms audible threshold).
    tracker._gap_count = 5
    tracker._max_gap_s = 0.150
    return tracker


def _flush_and_capture(tracker):
    """Call _flush_turn_summary() and return the INFO messages it logged.

    pytest's caplog and capfd don't intercept loguru (which manages its own
    sink registry).  Patching engine.logger.info is the reliable approach.
    """
    captured = []
    with patch.object(_engine_mod.logger, "info", side_effect=captured.append):
        tracker._flush_turn_summary()
    return " ".join(captured)


class TestSentenceModeAdvice:
    def test_audible_summary_suggests_switching_to_token(self):
        """In SENTENCE mode the INFO summary must advise switching to token."""
        from pipecat.services.tts_service import TextAggregationMode

        tracker = _make_audible_tracker(TextAggregationMode.SENTENCE)
        output = _flush_and_capture(tracker)

        assert "token" in output.lower(), (
            f"Expected 'token' in sentence-mode summary. Got: {output!r}"
        )
        assert "consider switching" in output.lower(), (
            f"Expected switch-to-token advice. Got: {output!r}"
        )

    def test_sentence_mode_does_not_mention_token_send_min_chars(self):
        """Sentence mode should not give the token batching hint (wrong advice)."""
        from pipecat.services.tts_service import TextAggregationMode

        tracker = _make_audible_tracker(TextAggregationMode.SENTENCE)
        output = _flush_and_capture(tracker)

        assert "token_send_min_chars" not in output, (
            f"Sentence-mode summary wrongly mentioned token_send_min_chars. Got: {output!r}"
        )


class TestTokenModeAdvice:
    def test_audible_summary_does_not_advise_switching_to_token(self):
        """In TOKEN mode the summary must NOT say 'consider switching to token'."""
        from pipecat.services.tts_service import TextAggregationMode

        tracker = _make_audible_tracker(TextAggregationMode.TOKEN)
        output = _flush_and_capture(tracker)

        assert "consider switching text_aggregation_mode to 'token'" not in output, (
            f"Token-mode tracker emitted wrong switch-to-token advice: {output!r}"
        )

    def test_audible_summary_suggests_token_send_min_chars(self):
        """In TOKEN mode the summary must mention token_send_min_chars as the lever."""
        from pipecat.services.tts_service import TextAggregationMode

        tracker = _make_audible_tracker(TextAggregationMode.TOKEN)
        output = _flush_and_capture(tracker)

        assert "token_send_min_chars" in output, (
            f"Expected token_send_min_chars hint in token-mode audible summary. Got: {output!r}"
        )


class TestUnknownModeAdvice:
    def test_unknown_mode_falls_back_to_switch_advice(self):
        """No-mode (None) tracker falls back to the original switch-to-token advice."""
        tracker = TtsAudioGapTracker(text_aggregation_mode=None)
        tracker._gap_count = 3
        tracker._max_gap_s = 0.120
        output = _flush_and_capture(tracker)

        assert "token" in output.lower(), (
            f"Expected 'token' in unknown-mode fallback summary. Got: {output!r}"
        )

    def test_no_info_log_when_gaps_are_below_audible_threshold(self):
        """Gaps below the 100 ms audible threshold log at DEBUG only —
        the INFO path (with mode advice) must not fire."""
        from pipecat.services.tts_service import TextAggregationMode

        tracker = _make_audible_tracker(TextAggregationMode.TOKEN)
        tracker._max_gap_s = 0.050  # 50 ms — below the 100 ms audible threshold
        output = _flush_and_capture(tracker)

        # _flush_turn_summary calls logger.debug (not logger.info) for sub-audible
        # gaps; our patch only intercepts logger.info, so output must be empty.
        assert output == "", (
            f"Sub-audible gaps must not produce an INFO log. Got: {output!r}"
        )
