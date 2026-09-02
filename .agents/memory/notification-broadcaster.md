---
name: Notification Broadcaster — Postgres LISTEN/NOTIFY
description: How the SMS SSE broadcaster works, its multi-worker design, and the Neon pooler constraint.
---

# Notification Broadcaster — Postgres LISTEN/NOTIFY

## Rule

`notification_broadcaster.py` uses one asyncpg connection per worker that LISTENs on the `sms_events` Postgres channel. `broadcast()` sends `pg_notify('sms_events', json_payload)` so all workers receive and fan out events to their in-memory SSE queues simultaneously. Falls back silently to in-process fanout if the asyncpg connection fails.

**Why:** The previous in-process dict was invisible to other workers — SSE clients on worker B missed events published by worker A (Twilio webhook). Postgres NOTIFY delivers cross-worker at zero infra cost.

**How to apply:**
- Call `await broadcaster.start()` in the FastAPI `startup` hook; `await broadcaster.stop()` in `shutdown`.
- The singleton is imported from `botelier.services.notification_broadcaster`.
- The `broadcast(account_id, event_type, data)` API is unchanged; callers (`webhook.py`, etc.) need no modification.
- The listener loop runs `asyncio.sleep(60)` as a keepalive — asyncpg delivers notifications asynchronously; no polling.
- `_on_pg_notify` is a **sync** callback (asyncpg calls it in the event loop thread); `q.put_nowait()` is safe here.

## Neon Pooler Constraint

**If `DATABASE_URL` points to Neon's pgBouncer pooler endpoint (URL contains `-pooler.`), asyncpg LISTEN/NOTIFY will fail** and the broadcaster logs a warning then falls back to in-process mode. For true cross-worker delivery in production, a `DATABASE_LISTEN_URL` pointing to the Neon **direct** connection endpoint must be configured separately.

The fallback preserves the pre-change single-worker behaviour — no regression, but no cross-worker delivery either.

## Pipecat / Voice Event Loop Isolation

Pipecat pipelines run as asyncio tasks on the same event loop as the HTTP server (confirmed from `pipecat/pipeline/worker.py` source). A "separate event loop in the same process" is not a pipecat pattern and would break its internals. True isolation requires **separate Cloud Run services** (voice WebSocket handler service vs HTTP/SMS API service) — separate OS processes with separate event loops. This is infrastructure work, not code work.
