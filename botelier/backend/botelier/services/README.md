# `services/` — Cross-cutting business logic

## Purpose

Reusable, side-effect-bearing code used by both `api/` and `voice/`. Most write paths against Postgres flow through here.

## Main files

| File | Owns |
|---|---|
| `call_logger.py` | All lifecycle writes for `call_logs`, `call_legs`, `call_events`. `complete_call()` is the terminal-state finalizer (sweeper + normal teardown both call it). |
| `call_event_queue.py` | Async batcher for `CallEvent` inserts to avoid hot-path commits. |
| `shutdown_finalizer.py` | `finalize_active_calls_on_shutdown()` — finalizes in-flight calls on SIGTERM with a `shutdown` reason before the sweeper would otherwise see them. |
| `acw_service.py` | After-call work / disposition assignment. |
| `mcp_client.py` | Connects to remote MCP servers; lists + invokes tools. |
| `integration_client.py` | Generic HTTP integrations (Opera Cloud, custom REST). |
| `recording_sync.py` | Fetches Twilio call recordings + stores them. |
| `notification_broadcaster.py` | Server-Sent Events pipe for live dashboard updates. |
| `sms_service.py` | Outbound SMS send + thread state. |
| `sms_compliance_service.py` | A2P 10DLC compliance state machine. |

## How it connects

- Called from `api/*` (HTTP path) and `voice/*` (real-time path).
- `call_logger` is invoked from `voice/call_handler.py`, `database.run_stuck_call_sweeper`, `shutdown_finalizer`, and various `api/*` endpoints.
- `notification_broadcaster` is consumed by frontend SSE listeners.

## Conventions

- Public functions take `db: Session` as the first arg.
- `call_logger.complete_call(forced_by=...)` is the canonical terminal transition; non-`forced_by` calls come from the normal pipeline teardown, `forced_by="sweeper"` from the safety net, `forced_by="webhook_safety_net"` and `forced_by="finally_defensive"` from defensive paths in `voice/`.
- `complete_call` is idempotent on already-terminal rows (silent no-op when `forced_by` is set and `ended_at` is already populated).

## Setup

Imported as `botelier.services.*`. Not standalone.

## Gotchas

- **`offset_ms` is computed via the single helper `_event_offset.compute_offset_ms`** (Task #123). The DB column is `bigint` and the startup invariant `database._assert_call_events_offset_ms_bigint` refuses to start the app on type drift, so no clamping is needed. All three writers (`api/calls._write_event`, `services/call_event_queue.log`, `services/call_logger._write_event_inline`) call the helper. Adding a new direct `CallEvent` writer? Use the helper — never recompute the offset inline.
- **Finalization observability is committed in a separate transaction** (Task #123). `complete_call` first commits the CallLog status/ended_at mutation, then writes `finalization_forced` / `call_ended` events through `_write_event_isolated` (fresh `SessionLocal()`, never raises). An event-write failure logs a warning and leaves the disposition committed — honoring the "observability never blocks a disposition" contract that the docstring on `_write_event_inline` advertises.
- **Don't bypass `call_logger`.** All `CallLog` / `CallEvent` writes should go through it so observability events (`finalization_forced`, `call_ended`) are emitted consistently and the `offset_ms` helper is applied.
- `call_event_queue` is async — don't assume a write is durable until the queue flushes.
