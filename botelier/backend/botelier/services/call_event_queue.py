"""
CallEventQueue - Non-blocking pipeline event logger.

Pipecat pipeline events (websocket_connected, greeting_started, etc.) happen
inside the asyncio event loop driving the WebSocket audio pipeline.  Any DB
write that awaits inside that loop adds latency to audio processing.

Design:
  Hot path  : event_queue.log(...)  — synchronous put_nowait, never blocks
  Background: single asyncio.Task drains the queue and does batch inserts

Each call gets its own CallEventQueue instance.  The queue is bounded at 50
events; if full, the event is silently dropped — audio latency is never
sacrificed for logging.

Usage (inside call_handler / function_mapper):
    queue = CallEventQueue(call_log_id=..., call_started_at=...)
    await queue.start()                     # kick off background writer
    queue.log("websocket_connected", "pipecat")
    ...
    await queue.flush_and_stop()            # drain remaining events on call end
"""

import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from loguru import logger


_BATCH_SIZE = 10
_QUEUE_MAXSIZE = 50
_DRAIN_INTERVAL = 0.5  # seconds between drain cycles


class CallEventQueue:
    """
    Bounded asyncio queue + background writer for call pipeline events.

    Args:
        call_log_id: UUID of the CallLog row (str or UUID).
        call_started_at: When the call started, used to compute offset_ms.
    """

    def __init__(self, call_log_id, call_started_at: Optional[datetime] = None):
        self.call_log_id = str(call_log_id)
        self.call_started_at = call_started_at or datetime.utcnow()
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    @property
    def is_stopped(self) -> bool:
        """True once flush_and_stop() has been called."""
        return self._stop_event.is_set()

    def log(
        self,
        event_type: str,
        event_source: str = "pipecat",
        severity: str = "info",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Enqueue an event.  Synchronous — never blocks the caller.

        If the queue is full (50 pending events), or if the queue has already
        been stopped (flush_and_stop called), the event is silently dropped.

        The stop-event guard here is the canonical fix for the idle-timeout race
        condition: engine.py's IdleTimeoutTracker._on_idle() fires a callback that
        calls event_queue.log("idle_timeout", ...) — this can race with pipeline
        teardown and flush_and_stop().  Guarding in log() is preferred over
        adding a guard in every caller: a single check here protects all code
        paths (idle_timeout, greeting_started, user_speech_detected, etc.) that
        might fire after teardown.

        Args:
            event_type:   e.g. "websocket_connected", "greeting_started"
            event_source: "twilio" | "pipecat" | "app"
            severity:     "info" | "warning" | "error"
            details:      optional JSONB payload dict
        """
        if self._stop_event.is_set():
            logger.debug(
                f"CallEventQueue already stopped for call_log {self.call_log_id} — "
                f"dropping late event: {event_type}"
            )
            return
        now = datetime.utcnow()
        offset_ms = int((now - self.call_started_at).total_seconds() * 1000)
        event = {
            "call_log_id": self.call_log_id,
            "event_type": event_type,
            "event_source": event_source,
            "severity": severity,
            "occurred_at": now,
            "offset_ms": offset_ms,
            "details": details,
        }
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(
                f"CallEventQueue full for call_log {self.call_log_id} — "
                f"dropping event: {event_type}"
            )

    async def start(self) -> None:
        """Start the background writer task."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._background_writer())
        logger.debug(f"CallEventQueue background writer started for call_log {self.call_log_id}")

    async def flush_and_stop(self) -> None:
        """
        Gracefully stop the background writer and flush any remaining events.

        Signals the writer loop to exit after its current batch, waits for it
        to finish (so no in-progress insert is interrupted), then drains any
        events that arrived after the last batch cycle.
        """
        self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            self._task = None

        remaining = []
        while not self._queue.empty():
            try:
                remaining.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        if remaining:
            await self._insert_batch(remaining)
            logger.debug(
                f"CallEventQueue flushed {len(remaining)} remaining events "
                f"for call_log {self.call_log_id}"
            )

    async def _background_writer(self) -> None:
        """Drain the queue in batches until stop is signalled."""
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._stop_event.wait()),
                    timeout=_DRAIN_INTERVAL,
                )
            except asyncio.TimeoutError:
                pass
            batch = []
            while len(batch) < _BATCH_SIZE:
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            if batch:
                await self._insert_batch(batch)

    async def _insert_batch(self, events: list) -> None:
        """
        Insert a batch of events into the database.

        Runs the synchronous DB call in the default executor to avoid
        blocking the event loop during I/O.
        """
        try:
            await asyncio.to_thread(self._sync_insert_batch, events)
        except Exception as e:
            logger.error(
                f"CallEventQueue batch insert failed for call_log {self.call_log_id}: {e}"
            )

    @staticmethod
    def _sync_insert_batch(events: list) -> None:
        """Synchronous batch insert executed in a thread pool."""
        from ..database import SessionLocal
        from ..models.call_event import CallEvent

        db = SessionLocal()
        try:
            db.bulk_insert_mappings(
                CallEvent,
                [
                    {
                        "id": uuid.uuid4(),
                        "call_log_id": e["call_log_id"],
                        "event_type": e["event_type"],
                        "event_source": e["event_source"],
                        "severity": e["severity"],
                        "occurred_at": e["occurred_at"],
                        "offset_ms": e["offset_ms"],
                        "details": e["details"],
                    }
                    for e in events
                ],
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            raise exc
        finally:
            db.close()
