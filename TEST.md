# CLAUDE.md

<<<<<<< HEAD
Guide for AI coding assistants (and humans) working in this repository.

## 1. Repo layout warning — read first

This repository is a fork of the upstream **Pipecat** voice-AI framework with the **Botelier** SaaS app added under `botelier/`. The two coexist in one git tree.

**Off-limits (upstream Pipecat — do not edit; will create merge conflicts on every upstream sync):**

- `/README.md`, `/CHANGELOG.md`, `/CONTRIBUTING.md`, `/SECURITY.md`, `/COMMUNITY_INTEGRATIONS.md`, `/LICENSE`
- `/pyproject.toml`, `/requirements.txt`, `/uv.lock`, `/MANIFEST.in`, `/codecov.yml`, `/.readthedocs.yaml`, `/pipecat.png`
- `/src/` (the `pipecat` Python package itself)
- `/tests/` at the repo root (Pipecat's tests — distinct from `botelier/backend/tests/`)
- `/docs/`, `/examples/`
- `/scripts/` at the repo root (distinct from `botelier/backend/scripts/` and `botelier/backend/botelier/scripts/`)

**Botelier territory (edit freely):**

- `/botelier/**` — the entire SaaS app
- `/CLAUDE.md` — this file
- `/replit.md` — project memory (architectural decisions, conventions, history)

When in doubt, run `git log --follow <file>` — anything authored by Pipecat upstream is off-limits.

## 2. Project overview

**Botelier** is a multi-tenant SaaS that gives hotels an AI voice assistant. Guests call a Twilio number; a real-time pipeline (Deepgram STT → OpenAI LLM → TTS) handles the conversation, executes tools (MCP, internal HTTP integrations, knowledge-base lookups), and writes a full call log + analytics record. Hotels configure assistants, conversation flows, knowledge bases, tools, dispositions, phone numbers, and team access through a Next.js dashboard.

## 3. Architecture summary

| Layer | Stack |
|---|---|
| Frontend | Next.js 14 App Router (TS), custom `server.js` reverse-proxying `/api/*` and raw-TCP relaying `/api/ws/*` to FastAPI |
| Backend | FastAPI (Python 3.11), SQLAlchemy ORM, loguru |
| Voice pipeline | Pipecat (vendored under `/src/`) wrapped by `botelier/backend/botelier/voice/` |
| Telephony | Twilio Voice + Media Streams (WebSocket μ-law) |
| STT / LLM / TTS | Deepgram / OpenAI / multiple TTS providers |
| Database | Neon Postgres |
| MCP | Local + remote MCP servers via `botelier/backend/botelier/services/mcp_client.py`; `/botelier/test_mcp_server/` is a dev-only sample server |

## 4. Where things live

| You want to… | Look in |
|---|---|
| Add/modify an HTTP route | `botelier/backend/botelier/api/<resource>.py` (one file per resource) |
| Change call lifecycle / DB writes | `botelier/backend/botelier/services/call_logger.py` + `botelier/backend/botelier/database.py` (`run_stuck_call_sweeper`) |
| Edit the Pipecat pipeline | `botelier/backend/botelier/voice/engine.py` |
| Edit per-call orchestration / transcript capture | `botelier/backend/botelier/voice/call_handler.py` |
| Add a new ORM table | `botelier/backend/botelier/models/<name>.py` |
| Add a Pydantic / tool schema | `botelier/backend/botelier/schemas/` |
| Auth / RBAC / tenant scoping | `botelier/backend/botelier/auth/` |
| Twilio TwiML or REST helpers | `botelier/backend/botelier/integrations/twilio/` |
| Frontend page | `botelier/frontend/app/(dashboard)/dashboard/<area>/` |
| Reusable React component | `botelier/frontend/components/<group>/` |

## 5. Backend map

```
botelier/backend/
├── main.py                FastAPI app + startup/shutdown + 5-min sweeper loop
├── requirements.txt
├── botelier/              Main package
│   ├── api/               HTTP / WebSocket routers (file per resource)
│   ├── voice/             Real-time call pipeline (Pipecat wrapper)
│   ├── services/          Cross-cutting business logic (call_logger, mcp_client, ...)
│   ├── models/            SQLAlchemy ORM (one per table)
│   ├── schemas/           Pydantic + tool-schema definitions
│   ├── auth/              JWT, RBAC, account-scoping middleware
│   ├── integrations/      Outbound third-party (Twilio TwiML/REST)
│   ├── config/            Domain + provider catalog
│   ├── scripts/           Maintenance jobs (run as `python -m botelier.scripts.<name>`)
│   ├── seeds/             Idempotent seed data
│   ├── database.py        Engine, session, stuck-call sweeper
│   ├── logging_config.py  Centralised loguru sinks (LOG_PROMPTS gating)
│   ├── flow_executor.py   Conversation-flow runtime entry
│   ├── utils.py, validators.py
│   └── ...
├── scripts/               One-off backfills (separate from package scripts)
├── tests/                 pytest suite for Botelier-only code
└── uploads/               Static asset storage (mounted at /uploads)
```

See `botelier/backend/README.md` and the per-folder READMEs.

## 6. Frontend map

```
botelier/frontend/
├── server.js              Custom Next server: HTTP /api/* proxy + raw-TCP /api/ws/* relay
├── package.json           dev: `node server.js` (port from $PORT, default 5000)
├── app/                   Next 14 App Router with route groups
│   ├── (auth)/            Login
│   ├── (public)/invite/   Public invitation accept
│   ├── (dashboard)/dashboard/   Main tenant UI
│   ├── (admin)/admin/     Super-admin
│   ├── (standalone)/dashboard/  Embedded views
│   └── api/auth/          NextAuth handlers
├── components/
│   ├── flow-editor/       React-Flow visual builder (nodes + inspectors pairing)
│   ├── flow-simulator/    Browser-side flow simulator
│   ├── analytics/         Stat cards, drilldown modal, customizable widget layout
│   ├── forms/             Shared form primitives + assistant config form
│   ├── tabs/, providers/, ui/
├── lib/                   auth/, hooks/, theme/, flow-utils, notifications
└── contexts/              AccountFeaturesContext (plan/feature gating)
```

See `botelier/frontend/README.md` and the per-folder READMEs.

## 7. Voice flow (end-to-end)

1. **Twilio webhook** → `POST /api/calls/incoming` → `botelier/backend/botelier/api/calls.py`
   - Resolves tenant by called number, writes a `CallLog` row, kicks off `voice/prewarm.py` in `asyncio.create_task` (assistant + account + tools + MCP schema + greeting PCM), returns TwiML pointing at the WS.
2. **Twilio media stream** opens WS → `botelier/backend/botelier/api/websockets.py`.
3. **Per-call orchestration** in `voice/call_handler.py`:
   - Pops the prewarm bundle (≤500 ms wait), assembles the Pipecat pipeline via `voice/engine.py` (Silero VAD + `LocalSmartTurnAnalyzerV3` + Deepgram + OpenAI + TTS), runs greeting from `voice/greeting_cache.py`.
   - LLM tool calls dispatch through `voice/function_mapper.py` → `services/mcp_client.py`, `services/integration_client.py`, or `voice/knowledge_handler.py`.
4. **Lifecycle writes** flow through `services/call_logger.py` and `services/call_event_queue.py` into `call_logs`, `call_legs`, `call_events`.
5. **Teardown** is driven by `services/shutdown_finalizer.py`; the **stuck-call sweeper** in `database.run_stuck_call_sweeper` runs every 5 min as a safety net.
6. **Frontend** reads everything through `api/analytics.py` + `api/call_logs.py`, rendered by `components/analytics/`.

## 8. Twilio integration

| File | Role |
|---|---|
| `botelier/backend/botelier/integrations/twilio/client.py` | REST client wrapper |
| `.../twilio/sub_accounts.py` | Per-tenant subaccount management |
| `.../twilio/phone_numbers.py` | Number provisioning |
| `botelier/backend/botelier/api/calls.py` | Inbound webhook + status callback |
| `botelier/backend/botelier/api/websockets.py` | Media-stream WS endpoint |
| `botelier/frontend/server.js` | Raw-TCP WS relay with `setNoDelay(true)` to avoid Nagle batching of 160-byte μ-law frames in prod |

## 9. Coding conventions

**Python**
- `from loguru import logger` everywhere — never `print` in library code (startup banners in `main.py` are the documented exception).
- `botelier.logging_config.configure_logging()` MUST be the first import in any new entry point — see `main.py:14-18`.
- Type hints required on public functions.
- SQLAlchemy session usage: depend on `Depends(get_db)` in API handlers; in services, accept `db: Session` as the first arg. `SessionLocal()` directly only in startup/scripts/sweeper.
- **No silent fallbacks.** If something fails, raise or log a WARNING/ERROR with a traceback. Verbose payload dumps must be gated behind `is_log_prompts_enabled()` (`LOG_PROMPTS=on`) so prod logs stay clean.

**TypeScript / React**
- Server components by default in App Router; only mark `"use client"` when needed.
- API calls via `lib/auth/api-client.ts` — never construct fetch URLs ad-hoc.
- Toast notifications via `lib/notifications.ts` (sonner wrapper).
- Form state via local `useState` + `forms/FormSection.tsx` primitives; complex editor state via Zustand stores (see `components/flow-editor/store.ts`).

## 10. Naming conventions

- API route file = resource name: `api/assistants.py`, `api/call_logs.py`. Each exposes `router = APIRouter(prefix="/api/<resource>")`.
- Service files end in `_service.py` when they wrap a domain (`sms_service.py`, `acw_service.py`); core lifecycle services keep their plain noun (`call_logger.py`, `mcp_client.py`).
- ORM model file = singular noun matching the table: `models/call_log.py` defines `CallLog`, `CallLeg`, `CallEvent`.
- Flow editor convention: every node has a paired inspector — `nodes/MessageNode.tsx` ↔ `inspectors/MessageNodePanel.tsx`. Adding a new node type means adding both files plus registering in `nodes/index.ts`.
- Frontend route groups in parens (`(auth)`, `(dashboard)`, …) do NOT appear in URLs — they exist to scope layouts.

## 11. Safe-change checklist

Before editing any of these areas, read the listed companions first:

| Area | Companions to read first |
|---|---|
| Call lifecycle / sweeper / call_logger | `services/call_logger.py` (Task #123: post-commit isolated event writes via `_write_event_isolated`), `services/_event_offset.py` (single offset_ms helper), `database.py` (`run_stuck_call_sweeper`, `_assert_call_events_offset_ms_bigint` startup invariant), `services/shutdown_finalizer.py`, `models/call_log.py`, `models/call_event.py` |
| Voice pipeline | `voice/engine.py`, `voice/call_handler.py`, `voice/prewarm.py`, `main.py` (model pre-warm) |
| Tool execution | `voice/function_mapper.py`, `services/mcp_client.py`, `services/integration_client.py` |
| Flow editor | `components/flow-editor/store.ts`, `FlowEditor.tsx`, the `nodes/` + `inspectors/` pair you're touching |
| Auth | `auth/middleware.py`, `auth/permissions.py`, frontend `lib/auth/api-client.ts` |
| Twilio webhook | `api/calls.py`, `api/websockets.py`, `frontend/server.js` (WS relay) |
| Analytics | `api/analytics.py`, `models/call_log.py`, `models/call_event.py`, `components/analytics/` |

After any change, restart the affected workflow (see §12).

## 12. Testing, Replit workflows, and doc maintenance

**Replit workflows (defined in `.replit`):**

| Workflow | Command | Notes |
|---|---|---|
| `botelier-backend` | `cd botelier/backend && python -m uvicorn main:app --host 0.0.0.0 --port 3001 --reload` | FastAPI |
| `botelier-dashboard` | `cd botelier/frontend && npm run dev` | runs `node server.js`; binds to `$PORT` (default 5000) |
| `test-mcp-server` | `cd botelier/test_mcp_server && python server.py` | dev sample MCP server |

**Tests** live in `botelier/backend/tests/` (pytest). Existing coverage:
- `test_prewarm_cache.py`
- `test_sweeper_complete_call.py`
- `test_call_lifecycle_hardening.py`
- `test_analytics_partition.py`
- `test_greeting_audio_injector.py`

Run from `botelier/backend/`: `pytest tests/ -q`.

The repo-root `/tests/` directory is Pipecat's — do not run or modify it as part of Botelier work.

**Documentation maintenance rules**

- When adding a new top-level directory under `botelier/`, add a `README.md` in the same PR using the standard 6-section template (Purpose / Main files / How it connects / Conventions / Setup / Gotchas).
- When making an architectural change (new service, new pipeline stage, new auth flow), update `replit.md`.
- Never edit upstream Pipecat docs; if Pipecat behaviour matters, document the Botelier-side wrapper in the relevant `botelier/**/README.md`.
- Keep gotchas concrete and real — only document a footgun once it has bitten the codebase or is provably present in the schema/code.

**Reference: per-folder READMEs**

- [`botelier/README.md`](botelier/README.md)
- Backend: [`backend/`](botelier/backend/README.md), [`backend/botelier/`](botelier/backend/botelier/README.md), [`api/`](botelier/backend/botelier/api/README.md), [`api/sms_pkg/`](botelier/backend/botelier/api/sms_pkg/README.md), [`voice/`](botelier/backend/botelier/voice/README.md), [`voice/flows/`](botelier/backend/botelier/voice/flows/README.md), [`services/`](botelier/backend/botelier/services/README.md), [`models/`](botelier/backend/botelier/models/README.md), [`schemas/`](botelier/backend/botelier/schemas/README.md), [`auth/`](botelier/backend/botelier/auth/README.md), [`integrations/`](botelier/backend/botelier/integrations/README.md), [`config/`](botelier/backend/botelier/config/README.md), [`botelier/scripts/`](botelier/backend/botelier/scripts/README.md), [`backend/scripts/`](botelier/backend/scripts/README.md), [`backend/tests/`](botelier/backend/tests/README.md)
- Frontend: [`frontend/`](botelier/frontend/README.md), [`app/`](botelier/frontend/app/README.md), [`components/`](botelier/frontend/components/README.md), [`flow-editor/`](botelier/frontend/components/flow-editor/README.md), [`flow-simulator/`](botelier/frontend/components/flow-simulator/README.md), [`analytics/`](botelier/frontend/components/analytics/README.md), [`forms/`](botelier/frontend/components/forms/README.md), [`lib/`](botelier/frontend/lib/README.md), [`contexts/`](botelier/frontend/contexts/README.md)
- Other: [`test_mcp_server/`](botelier/test_mcp_server/README.md)
- Project memory: [`replit.md`](replit.md)
=======
This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Pipecat is an open-source Python framework for building real-time voice and multimodal conversational AI agents. It orchestrates audio/video, AI services, transports, and conversation pipelines using a frame-based architecture.

## Common Commands

```bash
# Setup development environment
uv sync --group dev --all-extras --no-extra gstreamer --no-extra local

# Install pre-commit hooks
uv run pre-commit install

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_name.py

# Run a specific test
uv run pytest tests/test_name.py::test_function_name

# Preview changelog
uv run towncrier build --draft --version Unreleased

# Lint and format check
uv run ruff check
uv run ruff format --check

# Update dependencies (after editing pyproject.toml)
uv lock && uv sync
```

## Architecture

### Frame-Based Pipeline Processing

All data flows as **Frame** objects through a pipeline of **FrameProcessors**:

```
[Processor1] → [Processor2] → ... → [ProcessorN]
```

**Key components:**

- **Frames** (`src/pipecat/frames/frames.py`): Data units (audio, text, video) and control signals. Flow DOWNSTREAM (input→output) or UPSTREAM (acknowledgments/errors).

- **FrameProcessor** (`src/pipecat/processors/frame_processor.py`): Base processing unit. Each processor receives frames, processes them, and pushes results downstream.

- **Pipeline** (`src/pipecat/pipeline/pipeline.py`): Chains processors together.

- **ParallelPipeline** (`src/pipecat/pipeline/parallel_pipeline.py`): Runs multiple pipelines in parallel.

- **Transports** (`src/pipecat/transports/`): Transports are frame processors used for external I/O layer (Daily WebRTC, LiveKit WebRTC, WebSocket, Local). Abstract interface via `BaseTransport`, `BaseInputTransport` and `BaseOutputTransport`.

- **Pipeline Task (`src/pipecat/pipeline/task.py`)**: Runs and manages a pipeline. Pipeline tasks send the first frame, `StartFrame`, to the pipeline in order for processors to know they can start processing and pushing frames. Pipeline tasks internally create a pipeline with two additional processors, a source processor before the user-defined pipeline and a sink processor at the end. Those are used for multiple things: error handling, pipeline task level events, heartbeat monitoring, etc.

- **Pipeline Runner (`src/pipecat/pipeline/runner.py`)**: High-level entry point for executing pipeline tasks. Handles signal management (SIGINT/SIGTERM) for graceful shutdown and optional garbage collection. Run a single pipeline task with `await runner.run(task)` or multiple concurrently with `await asyncio.gather(runner.run(task1), runner.run(task2))`.

- **Services** (`src/pipecat/services/`): 60+ AI provider integrations (STT, TTS, LLM, etc.). Extend base classes: `AIService`, `LLMService`, `STTService`, `TTSService`, `VisionService`.

- **Serializers** (`src/pipecat/serializers/`): Convert frames to/from wire formats for WebSocket transports. `FrameSerializer` base class defines `serialize()` and `deserialize()`. Telephony serializers (Twilio, Plivo, Vonage, Telnyx, Exotel, Genesys) handle provider-specific protocols and audio encoding (e.g., μ-law).

- **RTVI** (`src/pipecat/processors/frameworks/rtvi.py`): Real-Time Voice Interface protocol bridging clients and the pipeline. `RTVIProcessor` handles incoming client messages (text input, audio, function call results). `RTVIObserver` converts pipeline frames to outgoing messages: user/bot speaking events, transcriptions, LLM/TTS lifecycle, function calls, metrics, and audio levels.

- **Observers** (`src/pipecat/observers/`): Monitor frame flow without modifying the pipeline. Passed to `PipelineTask` via the `observers` parameter. Implement `on_process_frame()` and `on_push_frame()` callbacks.

### Important Patterns

- **Context Aggregation**: `LLMContext` accumulates messages for LLM calls; `UserResponse` aggregates user input

- **Turn Management**: Turn management is done through `LLMUserAggregator` and
  `LLMAssistantAggregator`, created with `LLMContextAggregatorPair`

- **User turn strategies**: Detection of when the user starts and stops speaking is done via user turn start/stop strategies. They push `UserStartedSpeakingFrame` and `UserStoppedSpeakingFrame` respectively.

- **Interruptions**: Interruptions are usually triggered by a user turn start strategy (e.g. `VADUserTurnStartStrategy`) but they can be triggered by other processors as well, in which case the user turn start strategies don't need to. An `InterruptionFrame` carries an optional `asyncio.Event` that is set when the frame reaches the pipeline sink. If a processor stops an `InterruptionFrame` from propagating downstream (i.e., doesn't push it), it **must** call `frame.complete()` to avoid stalling `push_interruption_task_frame_and_wait()` callers.

- **Uninterruptible Frames**: These are frames that will not be removed from internal queues even if there's an interruption. For example, `EndFrame` and `StopFrame`.

- **Events**: Most classes in Pipecat have `BaseObject` as the very base class. `BaseObject` has support for events. Events can run in the background in an async task (default) or synchronously (`sync=True`) if we want immediate action. Synchronous event handlers need to execute fast.

- **Async Task Management**: Always use `self.create_task(coroutine, name)` instead of raw `asyncio.create_task()`. The `TaskManager` automatically tracks tasks and cleans them up on processor shutdown. Use `await self.cancel_task(task, timeout)` for cancellation.

- **Error Handling**: Use `await self.push_error(msg, exception, fatal)` to push errors upstream. Services should use `fatal=False` (the default) so application code can handle errors and take action (e.g. switch to another service).

### Key Directories

| Directory                  | Purpose                                            |
| -------------------------- | -------------------------------------------------- |
| `src/pipecat/frames/`      | Frame definitions (100+ types)                     |
| `src/pipecat/processors/`  | FrameProcessor base + aggregators, filters, audio  |
| `src/pipecat/pipeline/`    | Pipeline orchestration                             |
| `src/pipecat/services/`    | AI service integrations (60+ providers)            |
| `src/pipecat/transports/`  | Transport layer (Daily, LiveKit, WebSocket, Local) |
| `src/pipecat/serializers/` | Frame serialization for WebSocket protocols        |
| `src/pipecat/observers/`   | Pipeline observers for monitoring frame flow       |
| `src/pipecat/audio/`       | VAD, filters, mixers, turn detection, DTMF         |
| `src/pipecat/turns/`       | User turn management                               |

## Code Style

- **Docstrings**: Google-style. Classes describe purpose; `__init__` has `Args:` section; dataclasses use `Parameters:` section.
- **Linting**: Ruff (line length 100). Pre-commit hooks enforce formatting.
- **Type hints**: Required for complex async code.
- **Dataclass vs Pydantic**: Use `@dataclass` for frames and internal pipeline data (high-frequency, no validation needed). Use Pydantic `BaseModel` for configuration, parameters, metrics, and external API data (benefits from validation and serialization). Specifically:
  - `@dataclass`: Frame types, context aggregator pairs, internal data containers
  - `BaseModel`: Service `InputParams`, transport/VAD/turn params, metrics data, API request/response models, serializer params

### Docstring Example

```python
class MyService(LLMService):
    """Description of what the service does.

    More detailed description.

    Event handlers available:

    - on_connected: Called when we are connected

    Example::

        @service.event_handler("on_connected")
        async def on_connected(service, frame):
            ...
    """

    def __init__(self, param1: str, **kwargs):
        """Initialize the service.

        Args:
            param1: Description of param1.
            **kwargs: Additional arguments passed to parent.
        """
        super().__init__(**kwargs)
```

## Service Implementation

When adding a new service:

1. Extend the appropriate base class (`STTService`, `TTSService`, `LLMService`, etc.)
2. Implement required abstract methods
3. Handle necessary frames
4. By default, all frames should be pushed in the direction they came
5. Push `ErrorFrame` on failures
6. Add metrics tracking via `MetricsData` if relevant
7. Follow the pattern of existing services in `src/pipecat/services/`

## Testing

Test utilities live in `src/pipecat/tests/utils.py`. Use `run_test()` to send frames through a pipeline and assert expected output frames in each direction. Use `SleepFrame(sleep=N)` to add delays between frames.
>>>>>>> 12f78378e4b068d730d59871054f725628d4acd3
