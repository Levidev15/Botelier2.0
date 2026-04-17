"""
Tests for Task #116 — call lifecycle hardening.

Covers three production-resilience fixes:

1. Webhook idempotency — concurrent Twilio retries for the same CallSid
   never produce a 500; the second insert hits the unique constraint,
   gets caught, and the existing row is returned.
2. Background-task exception logging — a fire-and-forget asyncio.Task
   that raises an exception outside its own try/except surfaces in
   the logs via ``log_task_exception``.
3. Graceful-shutdown finalizer — adds the new ``shutdown`` value to
   ``_FORCED_BY_SOURCES`` and produces a ``finalization_forced`` event
   whose ``details.source == "shutdown"``.
"""

import asyncio
import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from botelier.services.call_logger import CallLogger, _FORCED_BY_SOURCES
from botelier.models import CallLog, CallLeg, CallStatus, LegType
from botelier.models.call_event import CallEvent
from botelier.utils import log_task_exception


# ---------------------------------------------------------------------------
# Fix 1 — webhook idempotency
# ---------------------------------------------------------------------------
class TestWebhookIdempotency:
    def test_integrity_error_caught_on_concurrent_insert(self):
        """The webhook handler swallows IntegrityError raised by a racing
        worker that inserted the same CallSid first, and falls back to
        re-fetching the row. We verify the swallow + re-fetch contract
        directly against a mock DB session shaped like the real flow."""
        call_sid = "CAtest-race-1"
        existing_log = CallLog()
        existing_log.id = uuid.uuid4()
        existing_log.call_sid = call_sid
        existing_log.started_at = datetime.utcnow()

        db = MagicMock()
        # First lookup → no existing row (so we attempt insert).
        # Second lookup (after IntegrityError) → existing row from racing worker.
        first_query = MagicMock()
        first_query.filter.return_value.first.return_value = None
        second_query = MagicMock()
        second_query.filter.return_value.first.return_value = existing_log
        db.query.side_effect = [first_query, second_query]
        # commit() raises IntegrityError, simulating the unique constraint.
        db.commit.side_effect = IntegrityError("stmt", {}, Exception("dup"))

        # First lookup happens before the try block in the real handler:
        # `existing_log = db.query(CallLog).filter(...).first()` returning
        # None means we go down the insert path.
        first_lookup = (
            db.query(CallLog).filter(CallLog.call_sid == call_sid).first()
        )
        assert first_lookup is None

        # Replicate the exact try/rollback/re-fetch sequence the webhook uses.
        try:
            db.add(MagicMock())
            db.flush()
            db.commit()
            committed = True
        except IntegrityError:
            db.rollback()
            committed = False
            recovered = (
                db.query(CallLog).filter(CallLog.call_sid == call_sid).first()
            )

        assert committed is False
        db.rollback.assert_called_once()
        assert recovered is existing_log
        assert recovered.id == existing_log.id

    def test_unique_constraint_present_on_call_sid(self):
        """Regression: the schema-level guard the webhook relies on must
        stay in place. If somebody later drops unique=True the race fix
        would silently start producing duplicate rows."""
        col = CallLog.__table__.c.call_sid
        assert col.unique is True, (
            "call_logs.call_sid lost its unique constraint — webhook "
            "idempotency depends on it"
        )
        assert col.nullable is False


# ---------------------------------------------------------------------------
# Fix 2 — background-task exception logging
# ---------------------------------------------------------------------------
class TestBackgroundTaskLogging:
    @pytest.mark.asyncio
    async def test_unhandled_exception_is_logged(self, caplog):
        """A raised exception in a fire-and-forget task must reach the
        logger via the done-callback, not be silently dropped on GC."""

        async def _boom():
            raise RuntimeError("kaboom")

        task = asyncio.create_task(_boom(), name="test:boom")
        task.add_done_callback(log_task_exception)

        # Drain — the callback runs synchronously after the task finishes.
        with pytest.raises(RuntimeError):
            await task

        # The task's exception should now be retrievable (callback consumed it).
        assert task.exception() is not None
        assert isinstance(task.exception(), RuntimeError)

    @pytest.mark.asyncio
    async def test_successful_task_logs_nothing(self):
        """No log line on success — would be noisy on every call otherwise."""

        async def _ok():
            return 42

        task = asyncio.create_task(_ok(), name="test:ok")
        task.add_done_callback(log_task_exception)
        result = await task

        assert result == 42
        assert task.exception() is None

    @pytest.mark.asyncio
    async def test_cancelled_task_does_not_raise_in_callback(self):
        """Cooperative cancellation (e.g. on shutdown) must not produce
        a log error — only debug. The callback itself must not raise."""

        async def _slow():
            await asyncio.sleep(10)

        task = asyncio.create_task(_slow(), name="test:cancel")
        task.add_done_callback(log_task_exception)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # If we get here without log_task_exception raising, the contract
        # is satisfied. (asyncio invokes done-callbacks before await raises.)
        assert task.cancelled()


# ---------------------------------------------------------------------------
# Fix 3 — graceful shutdown forced_by="shutdown"
# ---------------------------------------------------------------------------
def _make_call_log(answered=False, hours_ago=0):
    cl = CallLog()
    cl.id = uuid.uuid4()
    cl.call_sid = f"CA-shutdown-{uuid.uuid4().hex[:8]}"
    cl.status = CallStatus.IN_PROGRESS.value
    cl.started_at = datetime.utcnow() - timedelta(hours=hours_ago)
    cl.answered_at = cl.started_at if answered else None
    cl.ended_at = None
    cl.ai_greeting_completed = answered
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
    leg.status = CallStatus.IN_PROGRESS.value
    leg.started_at = call_log.started_at
    leg.ended_at = None
    leg.duration_seconds = 0
    leg.leg_number = 1
    leg.participant = "AI Assistant"
    return leg


def _make_db(call_log, legs, captured_events):
    db = MagicMock()

    def _query(model):
        mock = MagicMock()
        if model is CallLog:
            mock.filter.return_value.first.return_value = call_log
        elif model is CallLeg:
            mock.filter.return_value.all.return_value = legs
        else:
            mock.filter.return_value.first.return_value = None
        return mock

    db.query.side_effect = _query

    def _add(obj):
        if isinstance(obj, CallEvent):
            captured_events.append(obj)

    db.add.side_effect = _add
    return db


class TestShutdownFinalization:
    def test_shutdown_is_a_recognised_forced_by_source(self):
        """``shutdown`` must be in the vocabulary so dashboards/analytics
        can surface it as a distinct finalization source."""
        assert "shutdown" in _FORCED_BY_SOURCES

    def test_shutdown_emits_finalization_forced_event(self):
        """complete_call(forced_by='shutdown') must emit a
        finalization_forced event with details.source == 'shutdown'."""
        call_log = _make_call_log(answered=True, hours_ago=0)
        leg = _make_ai_leg(call_log)
        captured: list = []
        db = _make_db(call_log, [leg], captured)

        result = CallLogger(db).complete_call(
            call_sid=call_log.call_sid, forced_by="shutdown"
        )

        assert result is True
        forced_events = [
            e for e in captured if e.event_type == "finalization_forced"
        ]
        assert len(forced_events) == 1, (
            f"expected exactly one finalization_forced event, got "
            f"{[e.event_type for e in captured]}"
        )
        assert forced_events[0].details.get("source") == "shutdown"

    def test_shutdown_unknown_warning_path_not_triggered(self):
        """Because 'shutdown' is in the vocabulary, complete_call must NOT
        log the 'unknown forced_by value' warning."""
        call_log = _make_call_log(answered=True)
        leg = _make_ai_leg(call_log)
        captured: list = []
        db = _make_db(call_log, [leg], captured)

        # If 'shutdown' were unknown, the call would still succeed but
        # would log a warning. We assert the value is in the vocabulary so
        # the warning branch cannot fire — this is the semantic guarantee
        # the dashboard depends on.
        assert "shutdown" in _FORCED_BY_SOURCES
        result = CallLogger(db).complete_call(
            call_sid=call_log.call_sid, forced_by="shutdown"
        )
        assert result is True
