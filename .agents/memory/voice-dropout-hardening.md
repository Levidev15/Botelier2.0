---
name: Voice dropout invariants
description: Durable invariants behind the speech cut-in/out fixes — what must not regress
---

- **One failure class:** anything that clears carrier-buffered Twilio audio (false interruptions), starves the shared event loop, or micro-fragments TTS requests is heard by callers as speech cutting in and out. Evaluate new voice/pipeline code against all three.
- **Flux interruption gating must cover EVERY event handler.** Flux dispatches StartOfTurn, Update, EagerEndOfTurn, and EndOfTurn to separate private handlers; a word-count gate that skips one (eager EOT especially) lets a pending interruption fire late and clear freshly started bot audio. Any subclass over these private handlers needs a hasattr fork-guard that falls back loudly, since dev (pip) and prod (vendored fork) pipecat can diverge.
- **Telephony transport is hard 8 kHz μ-law.** Every TTS provider must be pinned/clamped to 8000 Hz at construction — assistant-level config is untrusted here; a mismatch corrupts or resamples live audio.
- **Endpoints doing synchronous SQLAlchemy with zero awaits belong off the event loop** (plain `def` → Starlette threadpool, or `to_thread` with own SessionLocal). The loop paces live-call audio; one slow sync query = audio gap for every active call. `LOOP_LAG_THRESHOLD_MS` env tunes the lag monitor (0 disables).
- **Never key concurrent Twilio mark waits on a shared name** — an Event-per-name map overwrites the first waiter and produces dead-air timeouts; wire names must be uniquified per send.
- **ACA voice app must stay at max-replicas 1 until call state is externalized**, and the replica pin must ride EVERY `az containerapp update` (setup script AND CI deploy) — an update that only sets `--image` silently preserves an old bad scale config on pre-existing apps.
