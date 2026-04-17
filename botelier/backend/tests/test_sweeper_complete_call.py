"""
Tests for Task #115 — sweeper-path complete_call fixes.

Covers:
  1. Unanswered calls swept by the sweeper do not get fabricated durations.
  2. offset_ms cap prevents int4 overflow for calls stuck >24.8 days.
  3. Answered sweeper calls still compute duration correctly (not regressed).

All tests use mock DB sessions so no real database connection is required.
"""

import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from botelier.services.call_logger import CallLogger, _INT4_MAX
from botelier.models import CallLog, CallLeg, CallStatus, CallOutcome, LegType
from botelier.models.call_event import CallEvent


def _make_call_log(answered_at=None, days_ago=0, hours_ago=0):
    cl = CallLog()
    cl.id = uuid.uuid4()
    cl.call_sid = f"CA-test-{uuid.uuid4().hex[:8]}"
    cl.status = CallStatus.INITIATED.value
    cl.started_at = datetime.utcnow() - timedelta(days=days_ago, hours=hours_ago)
    cl.answered_at = answered_at
    cl.ended_at = None
    cl.ai_greeting_completed = False
    cl.caller_spoke = None
    cl.duration_seconds = 0
    cl.transcript = None
    cl.outcome = None
    cl.ended_early = False
    cl.tool_name = None
    cl.account_id = uuid.uuid4()
    cl.assistant_id = uuid.uuid4()
    return cl


def _make_ai_leg(call_log):
    leg = CallLeg()
    leg.id = uuid.uuid4()
    leg.call_log_id = call_log.id
    leg.leg_type = LegType.AI_CONVERSATION.value
    leg.status = CallStatus.INITIATED.value
    leg.started_at = call_log.started_at
    leg.ended_at = None
    leg.duration_seconds = 0
    leg.leg_number = 1
    leg.participant = "AI Assistant"
    return leg


def _make_db(call_log, legs):
    """Return a mock Session that routes query() results by model type."""
    db = MagicMock()

    def _query(model):
        mock = MagicMock()
        if model is CallLog:
            mock.filter.return_value.first.return_value = call_log
        elif model is CallLeg:
            mock.filter.return_value.all.return_value = legs
        else:
            # CallEvent.id (column attr) for has_call_ended check → not found
            mock.filter.return_value.first.return_value = None
        return mock

    db.query.side_effect = _query
    return db


class TestSweeperUnansweredDuration:
    def test_unanswered_call_duration_stays_zero(self):
        """Sweeper must not fabricate duration for a call that never answered."""
        call_log = _make_call_log(answered_at=None, hours_ago=14)
        leg = _make_ai_leg(call_log)
        db = _make_db(call_log, [leg])

        result = CallLogger(db).complete_call(
            call_log.call_sid,
            forced_by="sweeper",
            sweeper_age_seconds=14 * 3600,
        )

        assert result is True
        assert call_log.duration_seconds == 0, (
            f"fabricated duration on call_log: {call_log.duration_seconds}s "
            f"(expected 0)"
        )
        assert leg.duration_seconds == 0, (
            f"fabricated duration on leg: {leg.duration_seconds}s (expected 0)"
        )

    def test_unanswered_call_leg_still_gets_ended_at(self):
        """leg.ended_at must be stamped to close the record even when duration is skipped."""
        call_log = _make_call_log(answered_at=None, hours_ago=3)
        leg = _make_ai_leg(call_log)
        db = _make_db(call_log, [leg])

        CallLogger(db).complete_call(
            call_log.call_sid,
            forced_by="sweeper",
            sweeper_age_seconds=10800,
        )

        assert leg.ended_at is not None, "leg.ended_at must be set to close the record"
        assert call_log.ended_at is not None, "call_log.ended_at must be set"

    def test_unanswered_call_25_days_old_does_not_overflow(self):
        """A 25-day-old unanswered call must finalize successfully (no overflow)."""
        call_log = _make_call_log(answered_at=None, days_ago=25)
        leg = _make_ai_leg(call_log)
        db = _make_db(call_log, [leg])

        result = CallLogger(db).complete_call(
            call_log.call_sid,
            forced_by="sweeper",
            sweeper_age_seconds=int(timedelta(days=25).total_seconds()),
        )

        assert result is True, "complete_call must return True (not roll back)"
        # Duration must NOT be the fabricated value (~2.16 M seconds)
        assert call_log.duration_seconds == 0, (
            f"fabricated duration leaked: {call_log.duration_seconds}s"
        )

    def test_unanswered_call_gets_ended_early_status(self):
        """Unanswered sweeper call must be classified as ended_early."""
        call_log = _make_call_log(answered_at=None, hours_ago=2)
        leg = _make_ai_leg(call_log)
        db = _make_db(call_log, [leg])

        CallLogger(db).complete_call(
            call_log.call_sid, forced_by="sweeper", sweeper_age_seconds=7200
        )

        assert call_log.status == CallStatus.ENDED_EARLY.value
        assert call_log.ended_early is True


class TestSweeperAnsweredDuration:
    def test_answered_sweeper_call_computes_duration(self):
        """Sweeper on a call that DID answer must still record a non-zero duration."""
        answered_at = datetime.utcnow() - timedelta(hours=1)
        call_log = _make_call_log(answered_at=answered_at)
        call_log.started_at = answered_at - timedelta(minutes=5)
        call_log.ai_greeting_completed = True
        leg = _make_ai_leg(call_log)
        leg.started_at = answered_at
        db = _make_db(call_log, [leg])

        result = CallLogger(db).complete_call(
            call_log.call_sid,
            forced_by="sweeper",
            sweeper_age_seconds=3900,
        )

        assert result is True
        # Duration should be roughly 1 h (3 600 s) from answered_at to now
        assert call_log.duration_seconds > 3500, (
            f"expected ~3600s, got {call_log.duration_seconds}"
        )


class TestOffsetMsCap:
    def test_offset_ms_never_exceeds_int4_max(self):
        """_write_event_inline must cap offset_ms so old int4 deployments don't overflow."""
        call_log = _make_call_log(answered_at=None, days_ago=25)
        leg = _make_ai_leg(call_log)
        db = _make_db(call_log, [leg])

        added_events: list = []
        original_add = db.add.side_effect

        def _capture(obj):
            added_events.append(obj)
            if original_add:
                original_add(obj)

        db.add.side_effect = _capture

        CallLogger(db).complete_call(
            call_log.call_sid,
            forced_by="sweeper",
            sweeper_age_seconds=int(timedelta(days=25).total_seconds()),
        )

        call_events = [e for e in added_events if isinstance(e, CallEvent)]
        assert call_events, "at least one CallEvent must be written (finalization_forced)"
        for evt in call_events:
            if evt.offset_ms is not None:
                assert evt.offset_ms <= _INT4_MAX, (
                    f"offset_ms {evt.offset_ms} exceeds int4 max {_INT4_MAX} "
                    f"for event '{evt.event_type}'"
                )

    def test_int4_max_constant_value(self):
        """Sanity check: _INT4_MAX must equal 2^31 - 1."""
        assert _INT4_MAX == 2_147_483_647
