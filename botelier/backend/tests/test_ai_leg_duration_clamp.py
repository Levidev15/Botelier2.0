"""Regression tests for the AI-conversation leg duration clamp in CallLogger.

Production bug: a call Twilio reported as ~30s showed ~5 minutes in Call Logs.
When a caller hung up mid-LLM request, the Pipecat pipeline lingered until its
300s SSE read timeout, then stamped the AI leg with its inflated wall-clock
duration (``duration_source="pipecat"``). ``_ensure_ai_leg_duration`` now clamps
the AI leg to the authoritative timestamp span
(``ai_leg.ended_at - call_log.answered_at``), which Twilio status webhooks set
at the real call boundaries, while tolerating sub-second clock skew so a
normally-finalized call is never shaved by a second.

All tests exercise ``_ensure_ai_leg_duration`` directly with a mock DB session;
the clamp path performs no database I/O.
"""

import uuid
from datetime import datetime
from unittest.mock import MagicMock

from botelier.models import CallLeg, CallLog, LegType
from botelier.services.call_logger import CallLogger


def _call_log(answered_at, ended_at):
    cl = CallLog()
    cl.id = uuid.uuid4()
    cl.answered_at = answered_at
    cl.ended_at = ended_at
    return cl


def _ai_leg(duration_seconds, duration_source, ended_at):
    leg = CallLeg()
    leg.id = uuid.uuid4()
    leg.leg_type = LegType.AI_CONVERSATION.value
    leg.duration_seconds = duration_seconds
    leg.duration_source = duration_source
    leg.ended_at = ended_at
    return leg


def _logger():
    return CallLogger(MagicMock())


class TestAiLegDurationClamp:
    def test_lingering_pipeline_duration_is_clamped_to_span(self):
        """The core bug: 300s SSE-timeout inflation is clamped to the real span."""
        answered = datetime(2026, 6, 24, 16, 58, 2)
        ended = datetime(2026, 6, 24, 16, 58, 30)  # 28s real call
        cl = _call_log(answered, ended)
        leg = _ai_leg(341, "pipecat", ended)  # 28s + ~313s linger
        _logger()._ensure_ai_leg_duration(cl, leg)
        assert leg.duration_seconds == 28
        assert leg.duration_source == "pipecat"

    def test_clean_pipeline_duration_within_span_is_kept(self):
        """A normally-finalized call's pipeline duration is left untouched."""
        answered = datetime(2026, 6, 24, 21, 45, 5)
        ended = datetime(2026, 6, 24, 21, 45, 18)  # 13s span
        cl = _call_log(answered, ended)
        leg = _ai_leg(12, "pipecat", ended)
        _logger()._ensure_ai_leg_duration(cl, leg)
        assert leg.duration_seconds == 12

    def test_one_second_skew_is_tolerated_not_clamped(self):
        """Sub-second clock/floor skew (<=2s over span) must not shave a second."""
        answered = datetime(2026, 6, 24, 12, 0, 0)
        ended = datetime(2026, 6, 24, 12, 0, 30)  # span 30s
        cl = _call_log(answered, ended)
        leg = _ai_leg(31, "pipecat", ended)  # 1s over span, within tolerance
        _logger()._ensure_ai_leg_duration(cl, leg)
        assert leg.duration_seconds == 31

    def test_recovers_duration_when_pipeline_supplied_none(self):
        """Terminal webhook before pipeline finalize: recover span from timestamps."""
        answered = datetime(2026, 6, 24, 12, 0, 0)
        ended = datetime(2026, 6, 24, 12, 1, 0)  # span 60s
        cl = _call_log(answered, ended)
        leg = _ai_leg(0, "unknown", ended)
        _logger()._ensure_ai_leg_duration(cl, leg)
        assert leg.duration_seconds == 60
        assert leg.duration_source == "pipecat"

    def test_transfer_span_excludes_bridged_time(self):
        """AI leg ended_at is stamped before the transfer leg, so span is AI-only."""
        answered = datetime(2026, 6, 24, 22, 46, 56)
        ai_ended = datetime(2026, 6, 24, 22, 47, 33)  # 37s AI-only
        # Parent call ran longer (bridged transfer), but the AI leg span is AI-only.
        cl = _call_log(answered, ended_at=datetime(2026, 6, 24, 22, 48, 50))
        leg = _ai_leg(334, "pipecat", ai_ended)
        _logger()._ensure_ai_leg_duration(cl, leg)
        assert leg.duration_seconds == 37

    def test_falls_back_to_call_log_ended_at_when_leg_end_missing(self):
        """When the AI leg has no ended_at, the call_log end is the anchor."""
        answered = datetime(2026, 6, 24, 12, 0, 0)
        cl = _call_log(answered, ended_at=datetime(2026, 6, 24, 12, 0, 45))  # 45s
        leg = _ai_leg(300, "pipecat", ended_at=None)
        _logger()._ensure_ai_leg_duration(cl, leg)
        assert leg.duration_seconds == 45

    def test_no_answer_time_leaves_duration_untouched(self):
        """Without an answer timestamp there is no authoritative span to clamp to."""
        cl = _call_log(answered_at=None, ended_at=datetime(2026, 6, 24, 12, 0, 0))
        leg = _ai_leg(999, "pipecat", datetime(2026, 6, 24, 12, 0, 0))
        _logger()._ensure_ai_leg_duration(cl, leg)
        assert leg.duration_seconds == 999
