# Botelier - Multichannel AI SaaS Platform

Botelier is a multi-tenant, multichannel AI platform that provides businesses with a configurable AI agent capable of handling voice calls and SMS.

## Run & Operate

### Dev (Replit — unchanged)
- `botelier-backend` workflow: `uvicorn main:app --host 0.0.0.0 --port 3001`
- `botelier-dashboard` workflow: `npm run dev` (Next.js, port 5000)
- Dev Twilio number (+1 702 707 4036) points to `riker.replit.dev`

### Production voice (Azure Container Apps)
- **`voice.botelier.ai`** runs the same full FastAPI codebase as Replit
- Both connect to the same Neon PostgreSQL database
- Only difference: `PUBLIC_BASE_URL=https://voice.botelier.ai` on the Azure container
- Dockerfile: `botelier/backend/Dockerfile` (build context = repo root)
- CI/CD: `.github/workflows/deploy-voice.yml` (triggers on push to `botelier/backend/**` or `src/pipecat/**`)
- One-time infrastructure setup: `scripts/azure-voice-setup.sh`
- Production Twilio numbers route to `voice.botelier.ai`:
  - +1 702 935 1117 (Mrs Fields): `https://voice.botelier.ai/api/calls/incoming`
  - +1 725 444 6079 (AVA-PV): `https://voice.botelier.ai/api/calls/incoming`
- Dashboard, SMS, billing, and all non-voice APIs remain on `botelier.replit.app`

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
- **Billing models:** `botelier/backend/botelier/models/billing.py` — `AccountBillingConfig`, `CallBillingItem`.
- **Billing API (account):** `botelier/backend/botelier/api/billing.py` — `/api/billing/usage/summary|calls|timeseries`, `/api/billing/config`.
- **Billing API (admin):** `botelier/backend/botelier/api/admin_billing.py` — `/api/admin/billing/accounts`, `/{id}/detail`, `/{id}/config`.
- **Billing alert service:** `botelier/backend/botelier/services/billing_alert_service.py` — threshold check + email dispatch.
- **Email service:** `botelier/backend/botelier/services/email_service.py` — SMTP delivery wrapper.

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
- **Usage & Billing APIs:** Account-scoped usage summary, paginated call cost list, cost timeseries, and rate config read endpoint. Admin cross-account table, per-account detail, and rate config CRUD. Permissions: `usage.view`, `usage.export`, `billing_rates.view`, `billing_rates.manage`.
- **Billing Threshold Alerts:** After each call completes, MTD spend is compared to `monthly_alert_threshold_usd`. When first crossed in a calendar month, an email is sent to platform admins and the account owner. Duplicate suppression is handled by the `account_billing_alerts` table (unique on `account_id + alert_year + alert_month`) using an atomic `INSERT ON CONFLICT DO NOTHING` — never stamped on the shared platform-default config row. The alert row is committed only after confirmed SMTP delivery; a failed send rolls the row back, enabling automatic retry on the next call. Email via `SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASSWORD`/`ALERT_EMAIL_FROM` env vars; silently skips if SMTP is unconfigured.

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