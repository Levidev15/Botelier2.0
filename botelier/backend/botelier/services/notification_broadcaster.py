"""
SMS Notification Broadcaster — Server-Sent Events (SSE) pub/sub.

Architecture:
    - Module-level singleton, one per server process.
    - Each connected browser tab registers an asyncio.Queue via subscribe().
    - When a new SMS arrives, the webhook calls broadcast() which puts an event
      into every registered queue for that account — zero HTTP requests, instant delivery.
    - Queues are capped at MAX_QUEUE_SIZE; overflow events are dropped (non-blocking
      put_nowait) so a slow client never blocks the webhook handler.

Future scaling note:
    - For multi-process / multi-worker deployments, replace the in-memory dict
      with a Redis pub/sub channel (one channel per account_id). The interface
      (subscribe / unsubscribe / broadcast) stays identical — only the backend changes.
"""

import asyncio
import json
from collections import defaultdict
from typing import AsyncGenerator, Dict, Set
from loguru import logger

MAX_QUEUE_SIZE = 50


class NotificationBroadcaster:
    """
    In-process pub/sub hub for SMS notifications.

    Usage:
        broadcaster = NotificationBroadcaster()          # singleton below
        queue = broadcaster.subscribe(account_id)           # SSE endpoint
        await broadcaster.broadcast(account_id, "new_message", {...})  # webhook
        broadcaster.unsubscribe(account_id, queue)          # on disconnect
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, Set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, account_id: str) -> asyncio.Queue:
        """Register a new SSE client for account_id. Returns its event queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
        self._subscribers[account_id].add(q)
        logger.debug(f"SSE client subscribed — account {account_id} "
                     f"({len(self._subscribers[account_id])} connected)")
        return q

    def unsubscribe(self, account_id: str, queue: asyncio.Queue) -> None:
        """Remove a client queue. Called when the SSE connection closes."""
        self._subscribers[account_id].discard(queue)
        if not self._subscribers[account_id]:
            del self._subscribers[account_id]
        logger.debug(f"SSE client disconnected — account {account_id} "
                     f"({len(self._subscribers.get(account_id, set()))} remaining)")

    async def broadcast(self, account_id: str, event_type: str, data: dict) -> None:
        """
        Push an event to all SSE clients watching account_id.

        Non-blocking: if a client queue is full the event is dropped for that
        client only — it will re-sync on the next conversation list refresh.
        """
        subscribers = self._subscribers.get(account_id, set())
        if not subscribers:
            return

        payload = json.dumps({"type": event_type, **data})
        dropped = 0
        for q in list(subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dropped += 1

        logger.debug(f"SSE broadcast '{event_type}' → account {account_id} "
                     f"({len(subscribers)} clients, {dropped} dropped)")

    async def event_generator(
        self, account_id: str, keepalive_seconds: int = 15
    ) -> AsyncGenerator[dict, None]:
        """
        Async generator consumed by EventSourceResponse.

        Yields SSE-formatted dicts with 'event' and 'data' keys.
        Sends a keepalive comment every `keepalive_seconds` to prevent
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
