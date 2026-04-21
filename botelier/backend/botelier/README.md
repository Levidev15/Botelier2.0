# `botelier` (Python package)

Main backend package. Everything imported by `main.py` lives here.

## Purpose

Houses all Botelier server-side code: HTTP routes, voice pipeline, business services, ORM models, schemas, auth, integrations, config, and the database session factory.

## Main files

```
botelier/
├── api/                  HTTP/WebSocket routers (file per resource)
├── voice/                Real-time call pipeline (Pipecat wrapper)
├── services/             Cross-cutting business logic
├── models/               SQLAlchemy ORM (one file per table)
├── schemas/              Pydantic + tool-schema definitions
├── auth/                 JWT, RBAC, account-scoping middleware
├── integrations/         Outbound third-party (currently: twilio/)
├── config/               Domain + provider catalog
├── scripts/              Maintenance jobs (`python -m botelier.scripts.<name>`)
├── seeds/                Idempotent seed data (called from main.py startup)
├── database.py           SQLAlchemy engine, SessionLocal, init_db,
│                         run_stuck_call_sweeper (5-min safety net)
├── flow_executor.py      Conversation-flow runtime entry point
├── logging_config.py     Centralised loguru sinks; LOG_PROMPTS gating
├── utils.py              log_task_exception, misc helpers
├── validators.py         Shared validation helpers
└── TOOLS_README.md       Notes about tool definition / execution
```

## How it connects

- `main.py` (one level up) imports each `api/*.py` router and includes it on the `FastAPI` app.
- `api/` modules call into `services/` and read/write `models/` via a `db: Session` dependency.
- `voice/` uses `services/call_logger.py`, `services/mcp_client.py`, and `services/integration_client.py` from inside the Pipecat pipeline.
- `database.py` is the only module that constructs `SessionLocal` — all others import it.

## Conventions

- One concern per file. Big files (`call_logger.py`, `call_handler.py`) are an exception driven by tight coupling, not preference.
- All logging goes through `from loguru import logger`. Verbose dumps are wrapped in `if is_log_prompts_enabled(): logger.debug(...)`.
- Public functions take typed args; SQLAlchemy `Session` is always the first parameter in service functions.

## Setup

Imported as `botelier.*` from `main.py`. Not directly runnable.

## Gotchas

- `database.py:run_stuck_call_sweeper` writes a `finalization_forced` and `call_ended` `CallEvent` per closed row. Both events store `offset_ms` (`bigint` column). Task #123: writes use the single `services/_event_offset.py:compute_offset_ms` helper — no clamping. The startup invariant `database._assert_call_events_offset_ms_bigint` refuses to start the app if the column type drifts back to int4. Task #123 also decoupled these event writes from the `complete_call` transaction (post-commit, fresh session via `_write_event_isolated`), so an event INSERT failure cannot roll back the disposition.
- `seeds/` is invoked unconditionally on every backend startup; new seed functions must be idempotent.
