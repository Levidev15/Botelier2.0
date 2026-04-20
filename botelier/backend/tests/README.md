# `backend/tests/` — Botelier pytest suite

## Purpose

Unit and integration tests for Botelier-only code. Isolated from the upstream Pipecat tests at the repo root (`/tests/`).

## Main files

| File | Covers |
|---|---|
| `test_prewarm_cache.py` | `voice/prewarm.py` — LRU eviction, TTL expiry, concurrent set/pop, cold-path fallback. |
| `test_sweeper_complete_call.py` | `database.run_stuck_call_sweeper` + `services/call_logger.complete_call` interaction; idempotency on terminal rows. |
| `test_call_lifecycle_hardening.py` | Forced-by paths, `ended_at` writes, `caller_spoke` semantics. |
| `test_analytics_partition.py` | Partitioning of analytics queries. |
| `test_greeting_audio_injector.py` | Greeting injection via `voice/greeting_cache.py`; phantom-caller-speech regression guard. |

## How it connects

- Imports the installed `botelier.*` package.
- Uses an in-memory or test-config SQLAlchemy session — does NOT touch prod DB.

## Conventions

- One file per area, mirroring the source layout.
- Fixtures live alongside the test file unless shared (then promote to `conftest.py`).

## Setup

```
cd botelier/backend
pytest tests/ -q
```

Run a single file: `pytest tests/test_prewarm_cache.py -q`.

## Gotchas

- The repo-root `/tests/` directory belongs to upstream Pipecat — do NOT include it in Botelier test runs.
- Tests assume `configure_logging()` is callable; if a test imports `botelier.*` modules directly, ensure logging is initialized to avoid noisy fallback sinks.
