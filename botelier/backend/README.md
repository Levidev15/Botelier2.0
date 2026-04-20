# Backend

FastAPI service for the Botelier SaaS.

## Purpose

Hosts the REST API, the Twilio media-stream WebSocket endpoint, and the real-time voice pipeline. Owns all writes to Neon Postgres.

## Main files

```
backend/
├── main.py              FastAPI app, CORS, router registration, startup/shutdown
│                        - Configures loguru BEFORE other imports
│                        - Seeds integration types
│                        - One-time idempotent migration of invalid Deepgram models
│                        - Pre-warms Silero VAD + LocalSmartTurnAnalyzerV3
│                        - Spawns _stuck_call_sweeper_loop (every 5 min)
│                        - Calls finalize_active_calls_on_shutdown on SIGTERM
├── requirements.txt     Python deps
├── prod_migration.sql   Production schema migration (run via run_prod_migration.py)
├── run_prod_migration.py
├── botelier/            Main package — see backend/botelier/README.md
├── scripts/             One-off backfills (see scripts/README.md)
├── tests/               pytest suite (see tests/README.md)
└── uploads/             Static files mounted at /uploads (greeting cache, attachments)
```

## How it connects

- Twilio → `botelier/api/calls.py` (HTTP webhook) and `botelier/api/websockets.py` (media stream WS).
- Frontend → all `/api/*` routes in `botelier/api/`.
- Postgres → `botelier/database.py` (engine, `SessionLocal`, sweeper).
- Pipecat (vendored at repo `/src/pipecat/`) → `botelier/voice/engine.py`.

## Conventions

- Loguru sinks are configured first. New entry points must call `from botelier.logging_config import configure_logging; configure_logging()` before any other `botelier.*` import (see `main.py:14-18`).
- Routers are imported and registered in `main.py`. Adding a route = create a file under `botelier/api/`, expose `router`, register in `main.py`.
- Long-running background work is launched via `asyncio.create_task` and instrumented with `botelier.utils.log_task_exception`.

## Setup

Run via the `botelier-backend` workflow:

```
cd botelier/backend && python -m uvicorn main:app --host 0.0.0.0 --port 3001 --reload
```

Required env: `DATABASE_URL`. Optional: `LOG_PROMPTS=on` enables verbose payload dumps for debugging (default off in prod).

Health check: `GET /api/health`. OpenAPI docs: `/api/docs`.

## Gotchas

- CORS is wide-open (`allow_origins=["*"]`) — `main.py:60-65` flags this as a TODO before prod tightening.
- Do not import anything from `botelier.*` before `configure_logging()` runs, or the centralised sinks won't apply to that module.
- `main.py:96-98` mounts `uploads/` as static — the directory is created at startup; do not assume it exists at import time.
- The 5-minute sweeper loop will swallow individual tick exceptions to stay alive; check WARNINGs from `botelier.database:run_stuck_call_sweeper` rather than relying on the loop dying.
