"""
Tests for Task #115 — sweeper-path complete_call fixes,
plus Task #123 — call_events schema invariant + decoupled finalization commit.

Covers:
  1. Unanswered calls swept by the sweeper do not get fabricated durations.
  2. Task #123 — offset_ms is no longer clamped (column is BIGINT).
  3. Answered sweeper calls still compute duration correctly (not regressed).
  4. Task #123 — event INSERT failure during complete_call still leaves the
     CallLog terminal and ended_at set ("observability never blocks
     disposition" contract honored).

All tests use mock DB sessions so no real database connection is required.
"""

import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from botelier.services.call_logger import CallLogger
from botelier.models import CallLog, CallLeg, CallStatus, CallOutcome, LegType
from botelier.models.call_event import CallEvent

# Task #123 — kept locally for legibility in the bigint-not-clamped assertion;
# the production constant has been removed from call_logger.py.
_INT4_MAX = 2_147_483_647


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


class TestOffsetMsBigint:
    """Task #123 — offset_ms is BIGINT and is no longer clamped.

    The startup invariant in
    ``botelier.database._assert_call_events_offset_ms_bigint`` guarantees
    the column type, so writers compute the true offset via
    ``services._event_offset.compute_offset_ms``. We assert that a 25-day-old
    finalization writes the TRUE offset (which exceeds int4 max), proving
    the legacy clamp is gone.
    """

    def test_offset_ms_for_25_day_call_exceeds_int4_max(self):
        """The decoupled-isolated event writer must record the true offset_ms,
        not a saturated int4 value.

        We patch ``_write_event_isolated`` to capture what would be written
        without touching a real DB session.
        """
        call_log = _make_call_log(answered_at=None, days_ago=25)
        leg = _make_ai_leg(call_log)
        db = _make_db(call_log, [leg])

        captured: list[dict] = []

        def _capture_isolated(
            *, call_log_id, event_type, event_source, severity, details,
            call_started_at,
        ):
            from botelier.services._event_offset import compute_offset_ms
            captured.append({
                "event_type": event_type,
                "offset_ms": compute_offset_ms(datetime.utcnow(), call_started_at),
            })

        with patch.object(
            CallLogger, "_write_event_isolated",
            side_effect=_capture_isolated, autospec=False,
        ):
            result = CallLogger(db).complete_call(
                call_log.call_sid,
                forced_by="sweeper",
                sweeper_age_seconds=int(timedelta(days=25).total_seconds()),
            )

        assert result is True
        assert captured, "finalization_forced + call_ended events must be emitted"
        for ev in captured:
            assert ev["offset_ms"] is not None
            # Proves no clamping: 25 days = 2.16e9 ms, larger than int4 max.
            assert ev["offset_ms"] > _INT4_MAX, (
                f"offset_ms {ev['offset_ms']} for {ev['event_type']} was "
                f"clamped to int4 max {_INT4_MAX} — the Task #123 BIGINT "
                f"invariant means clamping must be gone"
            )


class TestEventWriteFailureDoesNotBlockDisposition:
    """Task #123 — observability never blocks a disposition.

    Simulates the inline event writer raising at commit time and asserts the
    CallLog is still in a terminal state with ended_at set. Before Task #123
    the event writes shared the same session as the CallLog mutation, so a
    raise here would have rolled back the entire transaction.
    """

    def test_event_write_exception_leaves_calllog_terminal(self):
        call_log = _make_call_log(answered_at=None, hours_ago=2)
        leg = _make_ai_leg(call_log)
        db = _make_db(call_log, [leg])

        # Patch the isolated event writer to raise — _write_event_isolated
        # must swallow the exception (its contract is "never raises").
        def _explode(**kwargs):
            raise RuntimeError(
                "simulated FK race / schema mismatch on CallEvent INSERT"
            )

        with patch.object(
            CallLogger, "_write_event_isolated",
            side_effect=_explode, autospec=False,
        ):
            # If decoupling is wrong (event INSERT inside the main txn),
            # complete_call would catch the RuntimeError, rollback, return
            # False, and leave the CallLog in its pre-finalize state.
            result = CallLogger(db).complete_call(
                call_log.call_sid,
                forced_by="sweeper",
                sweeper_age_seconds=7200,
            )

        # The disposition must have been committed even though the event
        # write blew up. _write_event_isolated is contracted to never raise,
        # but even if it did, complete_call's commit happens BEFORE event
        # writes — so the row state must be terminal either way.
        assert call_log.status == CallStatus.ENDED_EARLY.value
        assert call_log.ended_at is not None
        # complete_call should still report success — finalization happened.
        # (The fact that observability emission failed is logged, not raised.)
        assert result is True

    def test_isolated_writer_swallows_exceptions(self):
        """``_write_event_isolated`` must never propagate exceptions, so a
        broken DB session in the helper cannot crash the sweeper loop."""
        from botelier.services import call_logger as cl_mod

        # Patch SessionLocal so any access raises.
        with patch.object(
            cl_mod, "logger"  # capture warnings without spamming pytest
        ):
            with patch(
                "botelier.database.SessionLocal",
                side_effect=RuntimeError("DB unreachable"),
            ):
                # Must return None (no exception)
                CallLogger._write_event_isolated(
                    call_log_id=uuid.uuid4(),
                    event_type="test_evt",
                    event_source="app",
                    severity="warning",
                    details={"k": "v"},
                    call_started_at=datetime.utcnow(),
                )
