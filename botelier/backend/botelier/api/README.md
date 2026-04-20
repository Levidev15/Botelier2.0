# `api/` — HTTP & WebSocket routers

## Purpose

One file per resource. Each module exposes a FastAPI `router` that is registered in `backend/main.py`.

## Main files

| File | Owns |
|---|---|
| `auth.py` | Email/password login, register, validate, verify-invitation |
| `account.py` | Account-level client endpoints (features, etc.) |
| `team.py` | Account team management |
| `invitations.py` | Public invitation accept |
| `admin.py` | Platform super-admin endpoints |
| `assistants.py` | Assistant CRUD + config |
| `tools.py`, `tool_sets.py` | Tool definitions and collections |
| `flow_versions.py`, `flow_templates.py` | Versioned conversation flows + templates |
| `knowledge_bases.py` | KB CRUD + entries |
| `mcp_connections.py` | MCP server connection config |
| `integrations.py` | Third-party integration config |
| `providers.py` | Read-only catalog (STT/LLM/TTS) from `config/providers.py` |
| `phone_numbers.py` | Twilio number provisioning + assignment |
| `dispositions.py`, `resolution_options.py` | Post-call categorization |
| `secrets.py` | Encrypted account-level secret store |
| `calls.py` | **Twilio inbound webhook + status callback; spawns prewarm** |
| `websockets.py` | **Twilio media-stream WS endpoint** |
| `call_logs.py` | Call drilldown + history |
| `analytics.py` | Dashboards, partitions, aggregates |
| `simulation.py` | Flow simulator backend |
| `api_tester.py` | Generic HTTP-tool sandbox proxy |
| `sms_pkg/` | SMS sub-package — see [`sms_pkg/README.md`](sms_pkg/README.md) |
| `sms_compliance.py` | SMS A2P 10DLC compliance |

## How it connects

- Imported and registered by `backend/main.py`.
- Calls into `botelier/services/*` and `botelier/voice/*`.
- Reads/writes via SQLAlchemy `Session` injected with `Depends(get_db)`.
- `calls.py` schedules `voice/prewarm.py` via `asyncio.create_task` so the webhook returns TwiML immediately while config loads in the background.

## Conventions

- Each file: `router = APIRouter(prefix="/api/<resource>", tags=["<resource>"])`.
- Auth: depend on `botelier.auth.middleware` helpers; never accept a user object as a plain arg.
- Tenant scoping: every query that touches account-owned data must filter by `account_id` from the auth dependency. Missing this = data leak.
- Response models: prefer Pydantic schemas from `botelier/schemas/`; ad-hoc dicts only for trivial endpoints.

## Setup

Auto-mounted by `main.py`. To add a route:
1. Create `api/<resource>.py` exposing `router`.
2. Import + `include_router` in `main.py`.

## Gotchas

- Route registration order in `main.py` matters when prefixes overlap (`flow_versions_router` is included before `tools_router` for that reason — see `main.py:69-70`).
- `calls.py` writes the `CallLog` row before responding to Twilio; if the DB write fails, the call still rings but with no log. Handle DB errors here carefully.
- `websockets.py` exposes the singleton `call_handler`; `main.py:206-207` reads `active_calls` and `call_tasks` from it on every sweeper tick to avoid closing live calls.
