"""SMS Notification Broadcaster — PostgreSQL LISTEN/NOTIFY backed, SSE pub/sub.

Architecture:
    - Each server worker opens ONE asyncpg connection and LISTENs on the
      shared 'sms_events' channel (started at FastAPI startup).
    - broadcast() sends pg_notify('sms_events', json_payload) on that same
      connection; Postgres delivers the notification to EVERY worker process
      simultaneously, regardless of which one received the inbound webhook.
    - Each worker then fans the event out to its own in-memory SSE client
      queues (one queue per connected browser tab).

Multi-worker correctness:
    The previous in-memory-only implementation was invisible to other workers,
    so an SSE client connected to worker B would miss events published on
    worker A. The Postgres NOTIFY layer fixes this at zero additional infra cost.

Graceful degradation:
    If the asyncpg connection cannot be established (e.g. Neon pgBouncer
    pooler endpoint, which does not support LISTEN/NOTIFY), broadcast() falls
    back silently to in-process fanout — preserving the single-worker
    behaviour that existed before this change.

Payload limit:
    Postgres NOTIFY payloads are capped at ~8 000 bytes. Typical SMS event
    payloads are well under 1 000 bytes.

Future scaling note:
    For deployments with very high event rates the single 'sms_events' channel
    can be split into per-account channels. The public interface (subscribe /
    unsubscribe / broadcast / event_generator) is identical either way.
"""

import asyncio
import json
import os
import re
from collections import defaultdict
from typing import AsyncGenerator, Dict, Optional, Set

import asyncpg
from loguru import logger

MAX_QUEUE_SIZE = 50
PG_NOTIFY_CHANNEL = "sms_events"


class NotificationBroadcaster:
    """Cross-worker SMS pub/sub hub backed by PostgreSQL LISTEN/NOTIFY.

    Usage:
        await broadcaster.start()               # FastAPI startup
        await broadcaster.broadcast(...)        # webhook / API call
        queue = broadcaster.subscribe(acct_id) # SSE endpoint
        broadcaster.unsubscribe(acct_id, q)    # on SSE disconnect
        await broadcaster.stop()               # FastAPI shutdown
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, Set[asyncio.Queue]] = defaultdict(set)
        self._pg_conn: Optional[asyncpg.Connection] = None
        self._listener_task: Optional[asyncio.Task] = None
        self._pg_available: bool = False  # True once LISTEN is confirmed

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    async def start(self) -> None:
        """Connect to Postgres and begin listening. Called at app startup."""
        raw_url = os.environ.get("DATABASE_URL") or os.environ.get("NEON_DATABASE_URL", "")
        if not raw_url:
            logger.warning("Broadcaster: DATABASE_URL not set — in-process fanout only")
            return

        # asyncpg requires postgresql:// scheme
        dsn = raw_url.replace("postgres://", "postgresql://", 1)

        # asyncpg reads ssl from the connection string differently from psycopg2.
        # Strip ?sslmode=... and pass it as the ssl= kwarg instead.
        ssl_required = bool(re.search(r"sslmode=(require|verify)", dsn))
        dsn = re.sub(r"[?&]sslmode=[^&]*", "", dsn).rstrip("?")

        try:
            self._pg_conn = await asyncpg.connect(
                dsn,
                ssl="require" if ssl_required else None,
            )
            logger.info("Broadcaster: Postgres LISTEN connection established")
        except Exception as exc:
            logger.warning(
                f"Broadcaster: could not connect to Postgres ({exc}); "
                "falling back to in-process fanout only"
            )
            self._pg_conn = None
            return

        self._pg_available = True
        self._listener_task = asyncio.create_task(self._listen_loop())
        self._listener_task.add_done_callback(self._on_listener_done)

    async def stop(self) -> None:
        """Cancel the listener task and close the connection. Called at app shutdown."""
        self._pg_available = False

        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except (asyncio.CancelledError, Exception):
                pass

        if self._pg_conn and not self._pg_conn.is_closed():
            try:
                await self._pg_conn.close()
            except Exception:
                pass
            self._pg_conn = None
            logger.info("Broadcaster: Postgres connection closed")

    def _on_listener_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error(f"Broadcaster: listener task exited unexpectedly — {exc}")

    # -------------------------------------------------------------------------
    # Postgres LISTEN loop (one per worker)
    # -------------------------------------------------------------------------

    async def _listen_loop(self) -> None:
        """Register an asyncpg notification handler and idle until cancelled.

        asyncpg calls _on_pg_notify() in the event loop whenever any worker
        sends pg_notify('sms_events', ...) — no polling, negligible CPU.
        """
        if not self._pg_conn:
            return

        await self._pg_conn.add_listener(PG_NOTIFY_CHANNEL, self._on_pg_notify)
        logger.info(
            f"Broadcaster: listening on Postgres channel '{PG_NOTIFY_CHANNEL}'"
        )

        try:
            # asyncpg delivers notifications asynchronously via the event loop.
            # This coroutine just needs to stay alive; the idle sleep is cheap.
            while True:
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            if self._pg_conn and not self._pg_conn.is_closed():
                try:
                    await self._pg_conn.remove_listener(
                        PG_NOTIFY_CHANNEL, self._on_pg_notify
                    )
                except Exception:
                    pass
            raise

    def _on_pg_notify(
        self,
        conn: asyncpg.Connection,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        """Called synchronously by asyncpg in the event loop on each NOTIFY.

        Decodes the payload and fans it out to all in-memory SSE queues for
        the target account.  put_nowait() is safe here because we are already
        running inside the asyncio event loop thread.
        """
        try:
            msg = json.loads(payload)
            account_id: Optional[str] = msg.pop("_account_id", None)
            event_type: Optional[str] = msg.pop("_event_type", None)
            if not account_id or not event_type:
                return

            subscribers = self._subscribers.get(account_id, set())
            if not subscribers:
                return

            data_str = json.dumps({"type": event_type, **msg})
            dropped = 0
            for q in list(subscribers):
                try:
                    q.put_nowait(data_str)
                except asyncio.QueueFull:
                    dropped += 1

            logger.debug(
                f"Broadcaster: '{event_type}' → account {account_id} "
                f"({len(subscribers)} clients, {dropped} dropped)"
            )
        except Exception as exc:
            logger.warning(f"Broadcaster: error in notification handler — {exc}")

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def broadcast(self, account_id: str, event_type: str, data: dict) -> None:
        """Push an event to all SSE clients for account_id — across all workers.

        Sends pg_notify so that every worker receives the event and can deliver
        it to its connected SSE clients.  Falls back to in-process fanout when
        the Postgres connection is unavailable (development, pgBouncer, etc.).
        """
        payload = json.dumps(
            {"_account_id": account_id, "_event_type": event_type, **data}
        )

        if self._pg_available and self._pg_conn and not self._pg_conn.is_closed():
            try:
                await self._pg_conn.execute(
                    "SELECT pg_notify($1, $2)",
                    PG_NOTIFY_CHANNEL,
                    payload,
                )
                return
            except Exception as exc:
                logger.warning(
                    f"Broadcaster: pg_notify failed ({exc}); falling back to in-process"
                )

        # ── In-process fallback (single-worker or degraded mode) ─────────────
        subscribers = self._subscribers.get(account_id, set())
        if not subscribers:
            return

        data_str = json.dumps({"type": event_type, **data})
        dropped = 0
        for q in list(subscribers):
            try:
                q.put_nowait(data_str)
            except asyncio.QueueFull:
                dropped += 1

        logger.debug(
            f"Broadcaster [in-process]: '{event_type}' → account {account_id} "
            f"({len(subscribers)} clients, {dropped} dropped)"
        )

    def subscribe(self, account_id: str) -> asyncio.Queue:
        """Register a new SSE client for account_id. Returns its event queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
        self._subscribers[account_id].add(q)
        logger.debug(
            f"SSE client subscribed — account {account_id} "
            f"({len(self._subscribers[account_id])} connected)"
        )
        return q

    def unsubscribe(self, account_id: str, queue: asyncio.Queue) -> None:
        """Remove a client queue. Called when the SSE connection closes."""
        self._subscribers[account_id].discard(queue)
        if not self._subscribers[account_id]:
            del self._subscribers[account_id]
        logger.debug(
            f"SSE client disconnected — account {account_id} "
            f"({len(self._subscribers.get(account_id, set()))} remaining)"
        )

    async def event_generator(
        self, account_id: str, keepalive_seconds: int = 15
    ) -> AsyncGenerator[dict, None]:
        """Async generator consumed by EventSourceResponse.

        Yields SSE-formatted dicts with 'event' and 'data' keys.
        Sends a keepalive comment every keepalive_seconds to prevent
        proxies (nginx, Cloudflare, etc.) from closing idle connections.
        """
        queue = self.subscribe(account_id)
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(
                        queue.get(), timeout=keepalive_seconds
                    )
                    msg = json.loads(payload)
                    event_type = msg.pop("type", "message")
                    yield {"event": event_type, "data": json.dumps(msg)}
                except asyncio.TimeoutError:
                    yield {"event": "keepalive", "data": ""}
        except asyncio.CancelledError:
            pass
        finally:
            self.unsubscribe(account_id, queue)


# ---------------------------------------------------------------------------
# Module-level singleton — import this everywhere
# ---------------------------------------------------------------------------
broadcaster = NotificationBroadcaster()
