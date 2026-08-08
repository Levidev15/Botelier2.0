# Botelier - Multichannel AI SaaS Platform

Botelier is a multi-tenant, multichannel AI platform that provides businesses with a configurable AI agent capable of handling voice calls and SMS.

## Run & Operate

### Dev (Replit)
- `botelier-backend` workflow: `uvicorn main:app --host 0.0.0.0 --port 3001`
- `botelier-dashboard` workflow: `npm run dev` (Next.js via custom `server.js`, port 5000)
- Dev Twilio number (+1 702 707 4036) points to `riker.replit.dev`
- Dev uses a **separate** database, fully isolated from production

### Environment variables — OAuth2 split-domain topology

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `PUBLIC_BASE_URL` | prod only | auto (Replit domain) | API host — registered OAuth2 redirect_uri base. Set on voice.botelier.ai and any custom API domain. |
| `FRONTEND_URL` | only when API and dashboard are on different hosts | `PUBLIC_BASE_URL` | Dashboard host. After the OAuth consent redirect, `/oauth/callback` hops the browser to `{FRONTEND_URL}/dashboard/integrations/oauth/complete`. Set this when `PUBLIC_BASE_URL` differs from the dashboard origin (e.g. `PUBLIC_BASE_URL=https://api.botelier.com`, `FRONTEND_URL=https://app.botelier.com`). Leave unset in dev/Replit single-host deployments. |

### Production voice (Azure Container Apps)
- **`voice.botelier.ai`** runs the same full FastAPI codebase; only difference is `PUBLIC_BASE_URL=https://voice.botelier.ai`
- Azure voice container + Replit production deployment share the same production Neon PostgreSQL database
- **Credential master key:** in production the Fernet key encrypting integration credentials comes from Azure Key Vault (secret `integration-encryption-key`, read at boot via managed identity, fails closed). Configured by `AZURE_KEY_VAULT_URL` + `BOTELIER_ENV=production`. Dev uses the `INTEGRATION_ENCRYPTION_KEY` env var. Rotation runbook: `botelier/backend/botelier/crypto.py`.
- Dockerfile: `botelier/backend/Dockerfile` (build context = repo root). CI/CD: `.github/workflows/deploy-voice.yml`. One-time infra: `scripts/azure-voice-setup.sh`.
- Production Twilio numbers route to `https://voice.botelier.ai/api/calls/incoming`: +1 702 935 1117 (Mrs Fields), +1 725 444 6079 (AVA-PV)
- Dashboard, SMS, billing, and all non-voice APIs remain on `botelier.replit.app`

## Stack

- **Backend:** Python 3.11, FastAPI (uvicorn), SQLAlchemy 2.0 ORM, Pydantic v2 validation, PostgreSQL (Neon in prod)
- **Voice:** pipecat-ai 1.5.0 (`deepgram`, `websocket` extras), Twilio 9.x, Deepgram STT (incl. Flux), pluggable LLM/TTS providers
- **Frontend:** Next.js 14.2 (App Router, custom `server.js` entry), React 18.3, TanStack Query, zustand, Tailwind CSS 3.4, recharts, @xyflow/react (flow editor)
- **Migrations:** no Alembic — additive SQL statements in `database.py` (`_ADDITIVE_MIGRATIONS`) plus startup schema assertions

## Where things live

All backend paths relative to `botelier/backend/botelier/` unless noted; frontend paths relative to `botelier/frontend/`.

- `botelier/backend/main.py` — app entry: router registration, startup (DB init, key fail-fast, seeds, VAD pre-warm, stuck-call sweeper)
- `api/` — FastAPI endpoints (API contracts are defined by these routes); `api/sms_pkg/` — SMS webhooks/conversations
- `auth/` — authentication, RBAC (`permissions.py` for permission schemas; `middleware.py` for `check_account_permission`)
- `models/` — SQLAlchemy models (one file per domain: `billing.py`, `property.py`, `payment_page_template.py`, `operation_policy.py`, `record_activity.py`, `integration_resilience.py`, `tool.py`, …)
- `services/` — business logic: `acw_service.py`, `billing_alert_service.py`, `email_service.py`, `property_scope.py`, `sms_service.py`, `operation_publisher.py`, `payments/`, `spec_importer/` (OpenAPI/Swagger/Postman parsers)
- `services/capabilities/` — vendor-neutral capability layer: `registry.py` (the 5 capabilities + schemas), `resolver.py` (fail-closed resolution, `.execute()` / `.execute_sync()`)
- `services/integration_runtime/` — certified-integration pipeline: `client.py` (the chokepoint: property isolation, credential use, redaction), `canonical.py` (versioned vendor-agnostic entities), `resilience.py` (rate limit / breaker / backoff), `adapters/` (per-vendor auth + normalizers, incl. `oauth2.py`)
- `voice/` — voice runtime: `engine.py` (Pipecat pipeline), `call_handler.py`, `function_mapper.py`, `greeting_cache.py`
- `flow_executor.py` — visual-flow runtime interpreter
- `database.py` — DB init, schema assertions, additive migrations, stuck-call sweeper
- `config/domain.py` — public base URL resolution
- `botelier/backend/uploads/greeting_cache/` — greeting audio cache
- Key API modules: `api/billing.py` (account usage), `api/admin_billing.py` (admin billing), `api/properties.py` (per-property CRUD), `api/integrations.py` (integrations + OAuth edge), `api/integration_builder.py` (Universal API Adapter: spec import, policies, publish), `api/payment_pages.py` + `api/payments.py` (payment page designer + public renderer), `api/simulation.py` (flow simulator), `api/records.py` (records + activity log)
- Frontend: `app/` (App Router pages, incl. `(dashboard)/dashboard/settings/payment-page/`), `lib/auth/usePermissions.ts` (permissions hook), `lib/theme/ThemeContext.tsx` + `app/globals.css` (theming), `lib/hooks/useTimezonePreference.ts` (per-user timezone)
- Integration docs: `docs-site/docs/integrations/`. Backend tests + PMS fixtures: `botelier/backend/tests/`.

## Architecture decisions

- **Multi-tenant isolation by `account_id`:** Every query, Twilio sub-account, and cache key is isolated per tenant. RBAC is enforced at the API edge.
- **Channel-agnostic abstractions:** Concepts shared across voice, SMS, and chat (assistants, knowledge bases, tools, dispositions, ACW) live in shared models, with channel-specific logic wrapping them.
- **Decoupled writes from observability:** Business writes commit first; analytics/event writes happen post-commit in isolated transactions so logging failures never roll back business state.
- **Schema invariants are startup-asserted:** Critical column types are checked on app startup and the app refuses to start on drift. Migrations are additive only.
- **Horizontal scale and concurrency:** Built for many simultaneous calls/SMS per account — stateless web/worker processes, persistent state in PostgreSQL, no global locks.

## Product

- **Multichannel AI Agent:** Configurable AI agent for voice + SMS; web chat on the roadmap.
- **Visual Flow Editor:** Drag-and-drop conversation flows with versioning and simulation. CONDITION branching, per-collect `maxRetries` with fallback branch, global "talk to a human" escalation (`call_settings.escalation_number`), mid-flow KB Q&A.
- **Pluggable AI Providers:** Swappable STT, LLM, and TTS providers per assistant.
- **Twilio Integration:** Phone numbers, call handling, sub-account isolation, transfers.
- **RBAC:** Granular permissions for users and administrators.
- **Post Call QA / ACW:** Configurable transcript analysis — dispositions, resolution status, AI quality scores, and an auto-generated ≤3-word call Topic (Call Logs column + last CSV column).
- **Analytics Dashboards:** Customizable call and SMS analytics with real-time data, filtering, export.
- **SMS Management:** Webhooks, conversations, analytics, AI handoff, A2P 10DLC compliance.
- **Feature Entitlement System:** Subscription-tier features with per-account overrides.
- **Canonical Domain Schemas:** Multi-vendor PMS responses (reservations, guests, rooms, rate plans, availability) are normalized inside each vendor adapter into a shared versioned canonical envelope that rides alongside — never replaces — the raw response. Opt-in per endpoint via a seed `canonical_entity` tag.
- **Universal Capability Tools:** The AI calls vendor-neutral capabilities (`search_availability`, `lookup_reservation`, `book_reservation`, `cancel_reservation`, `collect_payment`) that resolve at runtime to the caller's property-scoped provider connection — "the AI only knows tools, never vendors". Identical behavior on voice, SMS, and simulator.
- **Universal API Adapter:** Any REST API plugs in by importing its OpenAPI/Swagger/Postman spec; endpoints become `DYNAMIC_OPERATION` LLM tools routed through the certified `IntegrationClient` pipeline. The LLM sees only LLM-owned parameters; connection/secret/fixed params are injected at runtime. Tools are namespaced by connection slug. Full 3-channel parity.
- **Per-Property Data Isolation:** A `property_id` scope is resolved once at contact start (dialed number → assistant → NULL) and carried through the session; every integration resolution is scoped to `(account_id, property_id)` and fails closed before any outbound HTTP. Properties CRUD at `/api/properties`.
- **Designable Payment Page:** Per-property review+pay page designer with PMS-native single-call booking+charge (Stripe fallback when ambiguous).
- **Usage & Billing APIs:** Account usage summary/calls/timeseries + rate config; admin cross-account views and rate CRUD. Permissions: `usage.view`, `usage.export`, `billing_rates.view`, `billing_rates.manage`.
- **Billing Threshold Alerts:** First crossing of `monthly_alert_threshold_usd` in a calendar month emails platform admins + account owner. Dedup via `account_billing_alerts` unique row (`INSERT ON CONFLICT DO NOTHING`); the row commits only after confirmed SMTP delivery so failed sends retry on the next call. Silently skips when SMTP env vars are unset.

## User preferences
- **Branding:** All customer-facing code should be branded as "Botelier"
- **Architecture:** Clean separation - Pipecat as hidden dependency
- **Code Quality:** Organized, maintainable, no duplication
- **Future-proof:** Easy to update and extend
- **Naming:** Use generic terms (Account, not Hotel) to support various business types
- **Scale & Concurrency:** Always design for horizontal scale and many concurrent calls / SMS / chat sessions per account. No global locks, no per-process state that prevents adding workers, no synchronous blocking on observability writes.
- **Channel-Agnostic:** Voice and SMS are first-class peers, and chat is on the near-term roadmap. Shared concepts (assistant config, knowledge base, tools, dispositions, ACW) must live in channel-agnostic models — never lock an abstraction into a single channel.

## Gotchas

- **Backend workflow has no `--reload`:** manual restart required after backend code changes (reloads would kill long-lived voice WebSockets).
- **`call_events.offset_ms` must be `BIGINT`:** the app refuses to start if it drifts to `int4` (silent overflow in long calls).
- **`caller_spoke` is tri-state:** `NULL`/`TRUE` are eligible for `ai_handled` in analytics; `FALSE` (no caller audio) reclassifies the call as `unresolved`.
- **Simulator↔live parity:** the simulator runs the *resolved assistant's* `llm_model` (fallback `gpt-4o-mini`) — never a hardcoded stronger model. Any assistant lookup by `tool_set_id` must also filter `account_id` (ownership is not validated on create/update). COLLECT nodes don't force `tool_choice`; API_REQUEST nodes do.
- **Flow escalation is a transient tool:** `request_human` is built in-memory by `FunctionMapper.build_escalation_tool()` from `call_settings.escalation_number` — no DB row, drives a real Twilio transfer.
- **Generic flow naming:** confirmation dispatch is `confirm_details`, result key `collected_data`; exact-name dispatch must run before the `confirm_` prefix match.
- **ACW terminal states:** QA failures stamp `acw_skip_reason` + `acw_completed_at` (terminal — no auto-retry; recovery is the manual "Run QA" button, which is allowed whenever a skip reason is set). The ≤3-word topic cap is enforced only server-side (`_sanitize_topic`) — OpenAI strict json_schema rejects `maxLength`. CSV export is strictly additive: new columns append after `Transcript`.
- **Certified-only enforcement:** per-property isolation, canonical normalization, and resilience gates (rate limit + circuit breaker) all live in `IntegrationClient` — legacy custom-HTTP `API_REQUEST` tools and MCP bypass it entirely and get none of these protections. Keep property-specific endpoints on certified connections.
- **Default-property backfill re-stamps NULLs every boot:** `_backfill_default_properties()` binds NULL-`property_id` resources to the account's default property on startup. After adding a second property, anything meant to stay account-global must be explicitly reset to NULL. Property deletion is refused (HTTP 409) while resources are bound.
- **Capability resolution fails closed:** more than one candidate provider in the chosen tier → `None` ("unavailable") — the resolver never guesses. Property-identity keys (`hotel_id` etc.) are NOT capability params; they're re-forced from the connection by `IntegrationClient`. `CapabilitySpec.mutating` is the single source of truth for the flow idempotency guard — book/cancel stay `mutating=True`.
- **Canonical normalization contract:** a normalizer returns `None` when the vendor wrapper key is absent (drift visible) vs `[]` when present-but-empty (zero records) — keep distinct. Amount coalescing must use explicit `is None` so a legitimate `0.0` survives. Breaking a canonical shape requires bumping `CANONICAL_SCHEMA_VERSION` and updating all normalizers + consumers in lockstep.
- **Resilience gates fail open:** resilience DB ops use their OWN short-lived `SessionLocal` and an infra error allows the request (never blocks a live call). Retries re-issue only 429/5xx for idempotent methods. One `execute_request` = exactly one breaker verdict; any vendor-produced response (2xx or 4xx) counts as breaker success.
- **OAuth2 refresh — transient vs terminal:** network blips keep the integration CONNECTED (retry next request); definitive rejection → `TOKEN_EXPIRED` (re-consent). Never persist `ERROR` in the adapter — it permanently disables auto-refresh. The public OAuth callback is secured only by the one-time CSRF nonce in the `state` param.
- **Barge-in gating:** Pipecat broadcasts `InterruptionFrame` on EVERY user turn start, so interrupted-marking must gate on bot-speaking state. The per-assistant interruption toggle is `AlwaysUserMuteStrategy` — never `enable_interruptions=False`. Silero path uses `MinWordsUserTurnStartStrategy` (default 2 words) so noise can't cut the bot off.
- **Terminal speech is context-ID-bound (Pipecat 1.5.0):** hangup/transfer-after-goodbye callbacks bind to the TTS audio context ID via `_run_after_speech` (fires on `on_audio_context_completed`, immune to spurious mid-turn `BotStoppedSpeakingFrame`); `BotStopped` watcher and a fixed delay are fallbacks only. Hangups additionally await a Twilio playback mark before the REST hangup so goodbyes are never clipped.
- **Light-mode dark-hex whitelist:** inside `.themed-app`, any `bg-[#xxxxxx]` class must have a light-mode override registered in `globals.css` or it stays black in light mode. Use already-registered hexes (e.g. `bg-[#1a1a1a]`); never 3-digit shorthands like `bg-[#111]` (different Tailwind class name, won't match).
