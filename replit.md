# Botelier - Multichannel AI SaaS Platform

Botelier is a multi-tenant, multichannel AI platform that provides businesses with a configurable AI agent capable of handling voice calls and SMS.

## Run & Operate

_Populate as you build_

## Stack

- **Frameworks:** Next.js, FastAPI, React
- **Runtime Versions:** _Populate as you build_
- **ORM:** _Populate as you build_
- **Validation:** _Populate as you build_
- **Build Tool:** _Populate as you build_

## Where things live

- `/botelier/api/`: FastAPI endpoints for core services.
- `/botelier/auth/`: Authentication, authorization, and RBAC logic (see `permissions.py` for permission schemas).
- `/botelier/backend/`: Backend services and business logic (e.g., `services/acw_service.py`, `voice/engine.py`).
- `/botelier/frontend/`: Next.js frontend application.
- `/botelier/sms_pkg/`: SMS specific services and webhooks.
- `/config/domain.py`: Public base URL configuration.
- `/database.py`: Database initialization and schema assertions.
- `/lib/auth/usePermissions.ts`: Frontend permissions hook.
- `/lib/theme/ThemeContext.tsx`: Manages UI theme state.
- `/migrations/`: Database migrations (additive only).
- `/uploads/greeting_cache/`: Greeting audio cache files.
- `globals.css`: Global CSS overrides for theming.
- **DB Schema:** `database.py` (for startup assertions), individual model definitions within relevant backend packages.
- **API Contracts:** Defined implicitly by FastAPI endpoints in `/botelier/api/`.
- **Theme Files:** `lib/theme/ThemeContext.tsx`, `globals.css`.

## Architecture decisions

- **Multi-tenant isolation by `account_id`:** Every query, Twilio sub-account, and cache key is isolated per tenant. RBAC is enforced at the API edge.
- **Channel-agnostic abstractions:** Concepts shared across voice, SMS, and chat (assistants, knowledge bases, tools, dispositions, ACW) live in shared models, with channel-specific logic wrapping them.
- **Decoupled writes from observability:** Business writes commit first; analytics/event writes happen post-commit in isolated transactions to prevent logging failures from rolling back business state.
- **Schema invariants are startup-asserted:** Critical column types are checked on app startup, and the application refuses to start on drift. Migrations are additive only.
- **Horizontal scale and concurrency:** The system is built for many simultaneous calls and SMS conversations per account, with stateless web/worker processes and persistent state in PostgreSQL.

## Product

- **Multichannel AI Agent:** Configurable AI agent handling voice calls and SMS, with web chat on the roadmap.
- **Visual Flow Editor:** Drag-and-drop interface for creating and managing AI conversation flows with versioning and simulation.
- **Pluggable AI Providers:** Supports various STT, LLM, and TTS providers.
- **Twilio Integration:** Manages phone numbers, call handling, sub-account isolation, and call transfers.
- **Role-Based Access Control (RBAC):** Granular permissions for users and administrators.
- **Post Call QA / After-Call Work (ACW):** Configurable system for analyzing call transcripts, dispositions, resolution status, and AI quality scores.
- **Analytics Dashboards:** Customizable dashboards for call and SMS analytics with real-time data, filtering, and export.
- **SMS Management:** Comprehensive SMS handling including webhooks, conversations, analytics, AI handoff, and A2P 10DLC compliance.
- **Feature Entitlement System:** Extensible system for managing subscription tier features and per-account overrides.

## User preferences
- **Branding:** All customer-facing code should be branded as "Botelier"
- **Architecture:** Clean separation - Pipecat as hidden dependency
- **Code Quality:** Organized, maintainable, no duplication
- **Future-proof:** Easy to update and extend
- **Naming:** Use generic terms (Account, not Hotel) to support various business types
- **Scale & Concurrency:** Always design for horizontal scale and many concurrent calls / SMS / chat sessions per account. No global locks, no per-process state that prevents adding workers, no synchronous blocking on observability writes.
- **Channel-Agnostic:** Voice and SMS are first-class peers, and chat is on the near-term roadmap. Shared concepts (assistant config, knowledge base, tools, dispositions, ACW) must live in channel-agnostic models — never lock an abstraction into a single channel.

## Gotchas

- **Backend Workflow Reloads:** The `botelier-backend` workflow (uvicorn) does not use `--reload`. Manual restart is required after code changes, as reloads would terminate long-lived WebSockets for voice calls.
- **`call_events.offset_ms`:** This column must be `BIGINT`. The app will refuse to start if it drifts to `int4` to prevent silent overflow in long-lived calls.
- **Silent Caller Detection:** `caller_spoke` is a tri-state boolean. `NULL` and `TRUE` are considered eligible for `ai_handled` in analytics; `FALSE` (no caller audio) reclassifies calls into `unresolved`.

## Pointers

- **Pipecat Framework:** [Link to Pipecat documentation]
- **Twilio Docs:** [Link to Twilio documentation]
- **Sonner React Toasts:** [Link to Sonner documentation]
- **React Flow:** [Link to React Flow documentation]
- **Recharts:** [Link to Recharts documentation]
- **OpenAI API:** [Link to OpenAI documentation]