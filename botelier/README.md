# Botelier

Multi-tenant SaaS that gives hotels an AI voice assistant. Guests call a Twilio number; a real-time pipeline (Deepgram STT → OpenAI LLM → TTS) handles the conversation, runs tools (MCP / HTTP integrations / knowledge-base lookups), and writes a full call log and analytics record. Hotels configure everything through a Next.js dashboard.

## Purpose

Self-contained Botelier app. Lives inside this repo's `botelier/` directory; the rest of the repo is the upstream Pipecat framework (off-limits — see [`/CLAUDE.md`](../CLAUDE.md)).

## Main files

```
botelier/
├── backend/             FastAPI service (Python) — REST + WebSocket + voice pipeline
│   ├── main.py          App entry, startup hooks, 5-min stuck-call sweeper loop
│   ├── botelier/        Main Python package (api/, voice/, services/, models/, …)
│   ├── scripts/         Backend-local backfills
│   └── tests/           pytest suite for Botelier-only code
├── frontend/            Next.js 14 dashboard (TS, App Router)
│   ├── server.js        Custom Next server: HTTP proxy + raw-TCP WS relay
│   ├── app/             Route groups: (auth), (public), (dashboard), (admin), (standalone)
│   ├── components/      flow-editor, flow-simulator, analytics, forms, ui, …
│   ├── lib/             auth, hooks, theme, flow-utils, notifications
│   └── contexts/
├── test_mcp_server/     Dev-only sample MCP server
└── README.md            (this file)
```

## How it connects

- **Frontend → Backend.** `frontend/server.js` proxies HTTP `/api/*` and raw-TCP-relays `/api/ws/*` to the FastAPI service.
- **Backend → Twilio.** Inbound calls hit `/api/calls/incoming`; Twilio opens a media stream WS to `/api/ws/twilio/{call_sid}`.
- **Backend → Pipecat.** `voice/engine.py` assembles Silero VAD + Deepgram + OpenAI + TTS into a Pipecat pipeline; `voice/call_handler.py` orchestrates per-call.
- **Backend → DB.** SQLAlchemy → Neon Postgres. Lifecycle writes go through `services/call_logger.py`; `database.run_stuck_call_sweeper` is the safety net.
- **Backend → MCP.** `services/mcp_client.py` connects to remote MCP servers configured per account; `test_mcp_server/` is a dev sample.

See [`/CLAUDE.md`](../CLAUDE.md) for the full architecture and the safe-change checklist.

## Conventions

- One Python package (`backend/botelier/`) — never split into siblings.
- Routes are file-per-resource under `backend/botelier/api/`.
- ORM under `backend/botelier/models/`, Pydantic under `backend/botelier/schemas/`, business logic under `backend/botelier/services/`.
- Frontend pages under route groups in `frontend/app/(group)/...`; route groups don't appear in URLs.
- AI provider catalog (STT / LLM / TTS) lives in `backend/botelier/config/providers.py`; adding a provider is enum + factory only.

## Setup

Replit workflows defined in `.replit`:

| Workflow | Command |
|---|---|
| `botelier-backend` | `cd botelier/backend && python -m uvicorn main:app --host 0.0.0.0 --port 3001 --reload` |
| `botelier-dashboard` | `cd botelier/frontend && npm run dev` |
| `test-mcp-server` | `cd botelier/test_mcp_server && python server.py` |

Backend listens on `:3001`. Frontend `server.js` binds to `$PORT` (default `5000`) and proxies `/api/*` to `BACKEND_URL` (default `http://localhost:3001`).

## Gotchas

- The repo root is upstream Pipecat — do not edit `/README.md`, `/src/`, `/tests/`, `/docs/`, `/examples/`, `/scripts/`, `/pyproject.toml`, or `/CHANGELOG.md`. See [`/CLAUDE.md §1`](../CLAUDE.md).
- Keep `replit.md` in sync after architectural changes.
- Per-folder READMEs live alongside each area listed under **Main files** above (e.g. [`backend/`](backend/README.md), [`backend/botelier/`](backend/botelier/README.md), [`api/`](backend/botelier/api/README.md), [`voice/`](backend/botelier/voice/README.md), [`services/`](backend/botelier/services/README.md), [`models/`](backend/botelier/models/README.md), [`auth/`](backend/botelier/auth/README.md), [`integrations/`](backend/botelier/integrations/README.md), [`config/`](backend/botelier/config/README.md), [`schemas/`](backend/botelier/schemas/README.md), [`frontend/`](frontend/README.md), [`app/`](frontend/app/README.md), [`components/`](frontend/components/README.md), [`flow-editor/`](frontend/components/flow-editor/README.md), [`analytics/`](frontend/components/analytics/README.md), [`lib/`](frontend/lib/README.md), [`backend/tests/`](backend/tests/README.md), [`test_mcp_server/`](test_mcp_server/README.md)).
