---
name: Call lifecycle webhooks & pipeline teardown
description: Which Twilio webhook reliably fires on caller hangup, and where pipeline-cancel + after-call-work enqueue must live in lockstep.
---

# Call lifecycle webhooks & pipeline teardown

## Reliability of Twilio call callbacks on a plain caller hangup
On a plain caller hangup, Twilio reliably POSTs **only** `/api/calls/status`
(`CallStatus=completed`). It does **not** reliably request `/api/calls/connect-complete`,
which historically was the only path that cancelled the Pipecat pipeline and enqueued
after-call work. So `/status` is the only guaranteed terminal callback for hangups and
must be treated as the backstop that tears down the pipeline.

**Symptom when this is ignored:** the pipeline lingers as a "zombie" until Pipecat's own
idle auto-cancel (`IDLE_TIMEOUT_SECS=300`, ~5 min). During that window an idle tracker
fires every ~30s writing paired `idle_timeout` + `caller_silence_detected` ghost events
(~18/call), and after-call work never runs.

## After-call-work enqueue points must stay in lockstep
ACW, record-extraction, and billing-alert are enqueued from **three** paths that must be
kept consistent: connect-complete (cold), transfer-status (warm), and the `/status`
terminal backstop. If you add a new terminal path or a new after-call helper, wire it into
all the relevant ones. All three enqueue helpers are idempotent (dedup on `acw_completed_at`,
per-type extraction gates, monthly alert suppression), so a late duplicate callback is safe.

## Teardown ordering in the /status terminal branch
When tearing down a still-active pipeline from `/status`, order matters:
1. **Stop the idle tracker first** (synchronous, idempotent) — closes the ghost-event
   window before any `await` yields the loop.
2. Save the transcript (best-effort) so ACW/record-extraction have it.
3. Cancel the pipeline (idempotent; records a TTL-bounded pending-cancel if the task
   isn't registered yet).
4. Enqueue after-call work.
Run this **after** the row is already terminal (`update_status(completed)`/`call_ended`),
so handle_call's finally-block defensive finalization no-ops instead of emitting a spurious
`finalization_forced` event.

## Two mutually-exclusive gates on the same `_pipeline_was_active` flag
- Task #96 **safety net** fires only when the pipeline is **INACTIVE** and the DB row is
  still non-terminal (forces `complete_call`).
- The **zombie teardown** fires only when the pipeline is **ACTIVE**.
Capture `_pipeline_was_active` **before** any mutation so both gates stay mutually exclusive.

## Do NOT tear down transfer calls from /status
Transfers (`call_log.has_transfer`) are finalized by the transfer-status (warm) or
connect-complete (cold) paths. Cancelling from `/status` while a bridge is live can abort
transfer finalization (EndFrame is deliberately gated on a confirmed Twilio update), leave
`has_transfer` unset, and mis-classify the call. Always exclude `has_transfer` from any
`/status` teardown. This is why the transport-level `on_client_disconnected`→cancel
approach was rejected: the AI-leg WS closes mid-transfer and would wrongly kill bridging.

## Known limitation: is_pipeline_active is per-worker
`is_pipeline_active(call_sid)` only sees the local worker's in-memory registry. Current
topology is single-process-per-container, so this holds. If voice ever scales to multiple
workers, a `/status` callback landing on a different worker would report inactive → the
safety net finalizes the row while the pipeline zombies on the original worker until the
300s idle timeout. Would need a shared/out-of-process pipeline registry to fix.
