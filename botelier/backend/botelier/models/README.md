# `models/` — SQLAlchemy ORM

## Purpose

One file per logical area. Each module declares one or more SQLAlchemy `Base` subclasses mapped to Postgres tables.

## Main files

| File | Tables |
|---|---|
| `account.py` | `accounts` (tenant root) |
| `user.py` | `users` |
| `role.py` | RBAC roles + permissions |
| `invitation.py` | `invitations` (team onboarding) |
| `assistant.py` | `assistants` (AI agent config) |
| `tool.py`, `tool_set.py` | Tool definitions + collections |
| `flow_version.py` | Versioned conversation flows |
| `knowledge_base.py`, `knowledge_entry.py` | KB + entries |
| `mcp_connection.py` | MCP server connection config |
| `integration.py` | Third-party integration config |
| `phone_number.py` | Twilio number assignments |
| `disposition.py`, `resolution_option.py` | Post-call categorization |
| `call_log.py` | **`CallLog`, `CallLeg`, `CallEvent`, plus enums (`CallStatus`, `CallOutcome`, `LegType`)** |
| `sms_conversation.py`, `sms_template.py`, `sms_compliance.py` | SMS side-channel |

## How it connects

- All models inherit from the `Base` declared in `database.py`.
- `init_db()` (in `database.py`) is called from `main.py` startup — does not run destructive migrations.
- Production schema migrations live in `backend/prod_migration.sql` and are applied via `backend/run_prod_migration.py`.

## Conventions

- File name = singular noun; class name = PascalCase singular.
- Foreign keys to `accounts.id` are present on every tenant-owned table.
- Timestamps default to `datetime.utcnow` in app code (not DB-side `now()`), so backfills must use the same.
- Enums are defined alongside the model that owns them (e.g. `CallStatus` in `call_log.py`).

## Setup

Auto-imported via `botelier.models.*`. Tables are created by `init_db()` if missing.

## Gotchas

- **`CallEvent.offset_ms` is `BigInteger`** (`models/call_event.py:47`; prod column type `bigint`). Historically it was `INTEGER` (int32, ~24.85-day overflow window). Task #123 enforces the BIGINT invariant at startup (`database._assert_call_events_offset_ms_bigint`) and routes all writers through `services/_event_offset.compute_offset_ms` — no clamping. The fresh `CREATE TABLE` (in `database._ADDITIVE_MIGRATIONS`) declares BIGINT directly so a clean deploy never depends on a follow-up ALTER.
- `CallLog.duration_seconds` is `INTEGER` — the seconds ceiling (~68 years) is not at risk in practice.
- Adding a column requires a matching entry in `prod_migration.sql` for production; `init_db()` only creates new tables, not new columns.
