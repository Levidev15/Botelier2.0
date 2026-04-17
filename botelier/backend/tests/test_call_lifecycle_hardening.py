"""
Tests for Task #116 — call lifecycle hardening.

End-to-end regression tests for three production-resilience fixes:

1. Webhook idempotency — two concurrent invocations of
   ``incoming_call_webhook`` for the same CallSid both return 200 TwiML
   (no IntegrityError escapes to the caller).
2. Background-task exception logging — ``log_task_exception`` actually
   writes an ``error``-level loguru record with the task name and
   exception class when a fire-and-forget task raises.
3. Graceful-shutdown finalizer — ``_finalize_active_calls_on_shutdown``
   in ``main.py`` enumerates active calls, invokes
   ``CallLogger.complete_call(forced_by="shutdown")`` for each, cancels
   the pipeline, and the resulting ``finalization_forced`` event carries
   ``details.source == "shutdown"``.
"""

import asyncio
import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from loguru import logger
from sqlalchemy.exc import IntegrityError

from botelier.api.calls import incoming_call_webhook
from botelier.services.call_logger import CallLogger, _FORCED_BY_SOURCES
from botelier.services import shutdown_finalizer
from botelier.models import CallLog, CallLeg, PhoneNumber, CallStatus, LegType
from botelier.models.call_event import CallEvent
from botelier.utils import log_task_exception


# ---------------------------------------------------------------------------
# Fix 1 — webhook idempotency under concurrent retry
# ---------------------------------------------------------------------------
class _FakeRequest:
    """Minimal starlette-Request stand-in. The webhook only calls
    ``await request.form()``, so that's the only surface we need."""

    def __init__(self, form: dict):
        self._form = form

    async def form(self):
        return self._form


def _make_phone_record():
    pr = PhoneNumber()
    pr.id = uuid.uuid4()
    pr.account_id = uuid.uuid4()
    pr.assistant_id = uuid.uuid4()
    pr.phone_number = "+15551234567"
    return pr


def _make_winner_session(phone_record, call_sid: str):
    """Session that 'wins' the race — insert + commit succeed."""
    db = MagicMock()
    inserted_log = {"obj": None}

    def _query(model):
        m = MagicMock()
        if model is PhoneNumber:
            m.filter.return_value.first.return_value = phone_record
        elif model is CallLog:
            # Pre-insert lookup → None. Post-insert lookup never happens
            # for the winner.
            m.filter.return_value.first.return_value = None
        else:
            m.filter.return_value.first.return_value = None
        return m

    def _add(obj):
        if isinstance(obj, CallLog):
            obj.id = uuid.uuid4()
            inserted_log["obj"] = obj

    db.query.side_effect = _query
    db.add.side_effect = _add
    db.flush.return_value = None
    db.commit.return_value = None
    return db


def _make_loser_session(phone_record, call_sid: str, winner_log: CallLog):
    """Session that 'loses' the race — pre-insert lookup says None, then
    commit raises IntegrityError, then re-fetch returns the winner's row."""
    db = MagicMock()
    state = {"called": 0}

    def _query(model):
        m = MagicMock()
        if model is PhoneNumber:
            m.filter.return_value.first.return_value = phone_record
        elif model is CallLog:
            state["called"] += 1
            # First lookup (pre-insert) → None; Second lookup (post-rollback) → winner.
            if state["called"] == 1:
                m.filter.return_value.first.return_value = None
            else:
                m.filter.return_value.first.return_value = winner_log
        else:
            m.filter.return_value.first.return_value = None
        return m

    db.query.side_effect = _query
    db.add.return_value = None
    db.flush.return_value = None
    # commit raises on the insert path, but the *_write_event* helper
    # also commits — so we only raise the first time.
    commit_calls = {"n": 0}

    def _commit():
        commit_calls["n"] += 1
        if commit_calls["n"] == 1:
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))
        return None

    db.commit.side_effect = _commit
    db.rollback.return_value = None
    return db


class TestWebhookIdempotency:
    @pytest.mark.asyncio
    async def test_concurrent_retries_both_return_200_twiml(self):
        """Two parallel webhook invocations for the same CallSid must
        both return 200 TwiML — the loser catches IntegrityError, rolls
        back, and re-fetches the winner's row."""
        call_sid = "CAtest-race-concurrent"
        phone_record = _make_phone_record()

        winner_db = _make_winner_session(phone_record, call_sid)
        # Simulate the winner having committed its row by the time the
        # loser re-fetches.
        winner_log_stub = CallLog()
        winner_log_stub.id = uuid.uuid4()
        winner_log_stub.call_sid = call_sid
        winner_log_stub.started_at = datetime.utcnow()
        loser_db = _make_loser_session(phone_record, call_sid, winner_log_stub)

        form = {
            "CallSid": call_sid,
            "From": "+15559998888",
            "To": phone_record.phone_number,
            "CallStatus": "ringing",
        }
        req_a = _FakeRequest(form)
        req_b = _FakeRequest(form)

        # The prewarm-scheduling block in incoming_call_webhook is wrapped
        # in its own try/except Exception (api/calls.py ~line 420) and
        # logs a warning on failure, then falls through to the TwiML
        # response. That means we can race the function as-is: the
        # prewarm schedule will fail in the test environment (no real
        # call_handler), be caught, and we still get a clean 200.
        # The webhook also calls request.headers — patch the FakeRequest
        # to expose an empty headers dict.
        for r in (req_a, req_b):
            r.headers = {}

        # Race them in the same event loop.
        resp_a, resp_b = await asyncio.gather(
            incoming_call_webhook(req_a, winner_db),
            incoming_call_webhook(req_b, loser_db),
        )

        # Both must succeed — no 500, no IntegrityError escaping.
        assert resp_a.status_code == 200
        assert resp_b.status_code == 200
        assert b"<Response>" in resp_a.body or b"Response" in resp_a.body
        assert b"<Response>" in resp_b.body or b"Response" in resp_b.body

        # Loser must have rolled back exactly once and re-queried for the
        # row the winner committed.
        loser_db.rollback.assert_called_once()
        # query(CallLog) called twice on loser: once pre-insert, once post-rollback.
        callog_queries = [
            c for c in loser_db.query.call_args_list if c.args and c.args[0] is CallLog
        ]
        assert len(callog_queries) >= 2, (
            f"loser session should re-query CallLog after IntegrityError, "
            f"got {len(callog_queries)} CallLog queries"
        )

    def test_unique_constraint_present_on_call_sid(self):
        """Schema-level guard the webhook fix relies on must stay in place."""
        col = CallLog.__table__.c.call_sid
        assert col.unique is True, (
            "call_logs.call_sid lost its unique constraint — webhook "
            "idempotency depends on it"
        )
        assert col.nullable is False


# ---------------------------------------------------------------------------
# Fix 2 — background-task exception logging actually emits a log record
# ---------------------------------------------------------------------------
class TestBackgroundTaskLogging:
    @pytest.mark.asyncio
    async def test_unhandled_exception_emits_error_log_with_traceback(self):
        """The done-callback must produce an ``error``-level loguru
        record carrying the task name, exception class, and a traceback."""
        captured: list[dict] = []

        sink_id = logger.add(
            lambda msg: captured.append({
                "level": msg.record["level"].name,
                "message": msg.record["message"],
                "exception": msg.record["exception"],
            }),
            level="DEBUG",
        )
        try:
            async def _boom():
                raise RuntimeError("kaboom-from-prewarm")

            task = asyncio.create_task(_boom(), name="test:prewarm:CA123")
            task.add_done_callback(log_task_exception)
            with pytest.raises(RuntimeError):
                await task
            # done-callbacks fire on the next event-loop tick.
            await asyncio.sleep(0)
        finally:
            logger.remove(sink_id)

        error_records = [r for r in captured if r["level"] == "ERROR"]
        assert len(error_records) == 1, (
            f"expected exactly one ERROR log from log_task_exception, "
            f"got {len(error_records)}: {[r['message'] for r in captured]}"
        )
        rec = error_records[0]
        assert "test:prewarm:CA123" in rec["message"], rec["message"]
        assert "RuntimeError" in rec["message"], rec["message"]
        assert "kaboom-from-prewarm" in rec["message"], rec["message"]
        # loguru attaches the traceback under record["exception"] when
        # logger.opt(exception=...).error() is used.
        assert rec["exception"] is not None, (
            "log_task_exception should attach the exception/traceback "
            "to the loguru record"
        )

    @pytest.mark.asyncio
    async def test_successful_task_logs_no_error(self):
        """No ERROR log on success — would be noisy on every call."""
        captured: list[dict] = []
        sink_id = logger.add(
            lambda msg: captured.append({
                "level": msg.record["level"].name,
                "message": msg.record["message"],
            }),
            level="DEBUG",
        )
        try:
            async def _ok():
                return 42

            task = asyncio.create_task(_ok(), name="test:ok")
            task.add_done_callback(log_task_exception)
            assert await task == 42
            await asyncio.sleep(0)
        finally:
            logger.remove(sink_id)

        assert not [r for r in captured if r["level"] == "ERROR"]

    @pytest.mark.asyncio
    async def test_cancelled_task_does_not_log_error(self):
        """Cooperative cancellation must not surface as an ERROR."""
        captured: list[dict] = []
        sink_id = logger.add(
            lambda msg: captured.append({
                "level": msg.record["level"].name,
                "message": msg.record["message"],
            }),
            level="DEBUG",
        )
        try:
            async def _slow():
                await asyncio.sleep(10)

            task = asyncio.create_task(_slow(), name="test:cancel")
            task.add_done_callback(log_task_exception)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.sleep(0)
        finally:
            logger.remove(sink_id)

        assert not [r for r in captured if r["level"] == "ERROR"]


# ---------------------------------------------------------------------------
# Fix 3 — shutdown finalizer end-to-end behavior
# ---------------------------------------------------------------------------
def _make_call_log(answered=True):
    cl = CallLog()
    cl.id = uuid.uuid4()
    cl.call_sid = f"CA-shutdown-{uuid.uuid4().hex[:8]}"
    cl.status = CallStatus.IN_PROGRESS.value
    cl.started_at = datetime.utcnow()
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


class TestShutdownFinalizer:
    def test_shutdown_is_a_recognised_forced_by_source(self):
        assert "shutdown" in _FORCED_BY_SOURCES

    @pytest.mark.asyncio
    async def test_finalizer_completes_active_call_with_shutdown_source(self):
        """End-to-end: stub call_handler.active_calls + cancel_call_pipeline,
        run the real finalize_active_calls_on_shutdown, verify the SID
        gets a complete_call(forced_by='shutdown') with a finalization_forced
        event whose details.source == 'shutdown', and the pipeline cancel
        is awaited."""
        target_sid = "CA-sd-active"
        call_log = _make_call_log()
        call_log.call_sid = target_sid
        leg = _make_ai_leg(call_log)

        captured_events: list[CallEvent] = []
        cancelled_sids: list[str] = []

        def _make_db():
            db = MagicMock()

            def _query(model):
                m = MagicMock()
                if model is CallLog:
                    m.filter.return_value.first.return_value = call_log
                elif model is CallLeg:
                    m.filter.return_value.all.return_value = [leg]
                else:
                    m.filter.return_value.first.return_value = None
                return m

            db.query.side_effect = _query

            def _add(obj):
                if isinstance(obj, CallEvent):
                    captured_events.append(obj)

            db.add.side_effect = _add
            db.close.return_value = None
            return db

        fake_handler = MagicMock()
        fake_handler.active_calls = {target_sid: MagicMock()}
        fake_handler.call_tasks = {}

        async def _fake_cancel(sid):
            cancelled_sids.append(sid)

        fake_handler.cancel_call_pipeline = _fake_cancel

        # Pure dependency injection — no monkeypatching of imports
        # needed. The finalizer accepts both the session factory and the
        # call_handler as explicit arguments precisely so this test runs
        # in any environment, including ones where the websockets module
        # is unimportable due to missing pipecat.
        await shutdown_finalizer.finalize_active_calls_on_shutdown(
            session_factory=_make_db,
            call_handler=fake_handler,
        )

        # Pipeline must be cancelled.
        assert cancelled_sids == [target_sid], (
            f"expected pipeline cancelled for {target_sid}, got {cancelled_sids}"
        )

        # finalization_forced event must carry source='shutdown'.
        forced = [e for e in captured_events if e.event_type == "finalization_forced"]
        assert len(forced) == 1, (
            f"expected exactly one finalization_forced event, got "
            f"{len(forced)}: {[(e.event_type, e.details) for e in captured_events]}"
        )
        assert forced[0].details.get("source") == "shutdown", (
            f"finalization_forced must carry source='shutdown', got "
            f"{forced[0].details}"
        )

        # The CallLog row must reach a terminal state.
        assert call_log.status != CallStatus.IN_PROGRESS.value
        assert call_log.ended_at is not None

    @pytest.mark.asyncio
    async def test_finalizer_no_op_when_no_active_calls(self):
        """No active calls → finalizer must be a fast no-op (no DB hit)."""
        fake_handler = MagicMock()
        fake_handler.active_calls = {}
        fake_handler.call_tasks = {}
        fake_factory = MagicMock()

        await shutdown_finalizer.finalize_active_calls_on_shutdown(
            session_factory=fake_factory,
            call_handler=fake_handler,
        )

        fake_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_finalizer_bounded_by_total_timeout(self, monkeypatch):
        """If a single call's complete_call hangs, the total finalizer
        wall-clock must stay below the total budget."""
        # Tighten budgets so the test runs in <2s.
        monkeypatch.setattr(shutdown_finalizer, "SHUTDOWN_PER_CALL_TIMEOUT", 0.2)
        monkeypatch.setattr(shutdown_finalizer, "SHUTDOWN_TOTAL_TIMEOUT", 0.5)

        fake_handler = MagicMock()
        fake_handler.active_calls = {"CA-hang": MagicMock()}
        fake_handler.call_tasks = {}

        async def _never_cancel(sid):
            await asyncio.sleep(10)

        fake_handler.cancel_call_pipeline = _never_cancel

        # session_factory returns a session whose CallLogger.complete_call
        # blocks via a slow query inside the to_thread call.
        def _make_slow_db():
            slow_db = MagicMock()

            def _query(model):
                m = MagicMock()
                # Block in the .first() lookup to simulate a stalled DB.
                import time as _time

                def _slow_first():
                    _time.sleep(2.0)
                    return None
                m.filter.return_value.first.side_effect = _slow_first
                return m

            slow_db.query.side_effect = _query
            slow_db.close.return_value = None
            return slow_db

        loop = asyncio.get_event_loop()
        start = loop.time()
        await shutdown_finalizer.finalize_active_calls_on_shutdown(
            session_factory=_make_slow_db,
            call_handler=fake_handler,
        )
        elapsed = loop.time() - start

        # Coroutine-level bound: must return within total + small margin.
        # (The to_thread-bound query keeps running in its thread, but the
        # awaiter must unblock by the total timeout.)
        assert elapsed < 1.5, (
            f"shutdown finalizer overran its total timeout: {elapsed:.2f}s"
        )
