# Botelier - Multichannel AI SaaS Platform

Botelier is a multi-tenant, multichannel AI platform that provides businesses with a configurable AI agent capable of handling voice calls and SMS.

## Run & Operate

### Dev (Replit — unchanged)
- `botelier-backend` workflow: `uvicorn main:app --host 0.0.0.0 --port 3001`
- `botelier-dashboard` workflow: `npm run dev` (Next.js, port 5000)
- Dev Twilio number (+1 702 707 4036) points to `riker.replit.dev`
- Uses a **separate** development database, isolated from production — integrations, credentials, and test data created in dev never reach the production database

### Production voice (Azure Container Apps)
- **`voice.botelier.ai`** runs the same full FastAPI codebase as Replit
- The Azure voice container and the Replit **production** deployment connect to the same **production** Neon PostgreSQL database
- Only difference: `PUBLIC_BASE_URL=https://voice.botelier.ai` on the Azure container
- **Credential master key in Azure Key Vault:** the Fernet key that encrypts all integration
  credentials is stored in Key Vault (secret `integration-encryption-key`), read once at boot
  via the container's managed identity, and cached in-memory. Configured by `AZURE_KEY_VAULT_URL`
  + `BOTELIER_ENV=production` (never a container env-var secret). Fails closed if the vault is
  unreachable. Dev keeps using the `INTEGRATION_ENCRYPTION_KEY` env var. Rotation runbook lives
  in `botelier/backend/botelier/crypto.py`; one-time wiring in `scripts/azure-voice-setup.sh` (Step 5b).
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
- **Property model:** `botelier/backend/botelier/models/property.py` — `Property` (per-account location); nullable `property_id` FKs on `phone_number`, `assistant`, `AccountIntegration`.
- **Property scope resolver:** `botelier/backend/botelier/services/property_scope.py` — `resolve_session_property_id(dialed_number, assistant, db)` (precedence: phone → assistant → None).
- **Properties API:** `botelier/backend/botelier/api/properties.py` — `/api/properties` CRUD. Permissions: `properties.view`, `properties.manage`.
- **Property binding routes:** assign/clear a resource's `property_id` (NULL = account-global). Assistant: `property_id` on create/update (`api/assistants.py`). Phone number: `PUT /api/phone-numbers/{id}/property` (`api/phone_numbers.py`). Integration: `property_id` on connect + `PATCH /api/integrations/account/{account_id}/integration/{integration_id}/property` (`api/integrations.py`). All three validate the property belongs to the resource's account via `property_scope.property_belongs_to_account` (fail closed / HTTP 400 on cross-account).
- **Per-property isolation chokepoint:** `botelier/backend/botelier/services/integration_runtime/client.py` — `IntegrationClient(property_id=...)`, `_is_property_allowed()`, `PROPERTY_IDENTITY_KEYS` forcing in `_apply_endpoint_defaults`.
- **Canonical PMS schemas:** `botelier/backend/botelier/services/integration_runtime/canonical.py` — versioned vendor-agnostic entities (`reservation`/`guest`/`room`/`rate_plan`/`availability`) + `build_envelope`. Per-vendor normalizers live INSIDE each adapter (`adapters/opera_cloud.py`, `adapters/guestcentric.py`). Wired via `IntegrationClient._apply_canonical` → `APIResponse.canonical` / `ActionExecutionResult.canonical`. Opt-in per endpoint via a seed `canonical_entity` tag. Docs: `docs-site/docs/integrations/canonical-domain-schemas.md`. Tests + fixtures: `tests/test_canonical_normalization.py`, `tests/fixtures/pms/`.
- **Integration resilience:** `botelier/backend/botelier/services/integration_runtime/resilience.py` — cross-worker (Postgres-backed) rate limiting (token bucket), retry backoff (`compute_backoff_delay` full-jitter + `parse_retry_after`), circuit breaker (`circuit_allow`/`circuit_record_success`/`circuit_record_failure`). `ResilienceConfig.from_integration` merges `connection_config["resilience"]` over `auth_config["resilience"]` over defaults. State models: `models/integration_resilience.py` (`IntegrationRateLimit`, `IntegrationCircuitBreaker`, `CircuitState`; PK=integration_id, NO FKs). Wired into `client.py` `execute_request` (breaker+limit gates after url build; 429/5xx retry for safe methods only). Error types `APIErrorType.RATE_LIMITED`/`CIRCUIT_OPEN`. Tests: `tests/test_resilience_and_oauth.py`.
- **3-legged OAuth2:** `adapters/oauth2.py` (`OAuth2AuthorizationCodeAdapter`, auth_type `oauth2_authorization_code`; runtime `refresh_token` grant, transient→CONNECTED vs terminal→TOKEN_EXPIRED). API edge in `api/integrations.py`: `POST /api/integrations/account/{id}/oauth/authorize` (integrations.manage; creates CONNECTING integration + consent URL) and public `GET /api/integrations/oauth/callback` (nonce-validated code→token exchange, encrypted token storage, redirect to dashboard).
- **Designable PMS payment page:** `botelier/backend/botelier/models/payment_page_template.py` (`PaymentPageTemplate` + `default_page_design()`; `property_id` NULL = account default), API `botelier/backend/botelier/api/payment_pages.py` (`/api/payment-pages` GET/PUT/DELETE; `properties.view`/`properties.manage`, fail-closed cross-property). Public renderer + combined submit in `botelier/backend/botelier/api/payments.py` (`GET /api/payments/review/{token}`, `POST /api/payments/review/{token}/submit`). PMS-native routing in `services/capabilities/resolver.py` (`_card_capture_candidates`, `resolve_pms_native_payment`, `_service_backed_payment`); `PaymentService.collect_payment_pms_native()` in `services/payments/service.py`. Combined seed endpoints (`create_reservation_with_payment` / `book_reservation_with_payment`) tagged `supports_card_capture` (NO `capability` tag). Adapter card validation: `integration_runtime/adapters/base.py` `validate_card_capture` + `guestcentric.py` override. Dashboard designer: `botelier/frontend/app/(dashboard)/dashboard/settings/payment-page/page.tsx`. Docs: `docs-site/docs/integrations/designable-payment-page.md`. Tests: `tests/test_pms_native_payment.py`.
- **Universal capability layer:** `botelier/backend/botelier/services/capabilities/` — `registry.py` (`CapabilitySpec` + the 4 vendor-neutral capabilities `search_availability`/`lookup_reservation`/`book_reservation`/`cancel_reservation`; `build_capability_schema`, `get_capability`, `capability_names`, `all_capabilities`), `resolver.py` (`CapabilityResolver` fail-closed resolution + `translate_variables` + `format_capability_result`; `.execute()` async for voice/sim, `.execute_sync()` for SMS). Resolution reuses per-property scoping via `property_scope.property_access_allowed`. Seeds tag vendor endpoints with `capability` + `capability_params` (canonical→vendor key map). `ToolType.CAPABILITY` (`models/tool.py`; enum migration in `database.py`). Channel wiring: voice `voice/function_mapper.py` `_map_capability`, SMS `services/sms_service.py`, flow `flow_executor.py` `_handle_capability_request`, simulator `api/simulation.py` `_build_capability_tool_schemas`. Docs: `docs-site/docs/integrations/universal-capability-tools.md`. Tests: `tests/test_capabilities.py`.

## Architecture decisions

- **Multi-tenant isolation by `account_id`:** Every query, Twilio sub-account, and cache key is isolated per tenant. RBAC is enforced at the API edge.
- **Channel-agnostic abstractions:** Concepts shared across voice, SMS, and chat (assistants, knowledge bases, tools, dispositions, ACW) live in shared models, with channel-specific logic wrapping them.
- **Decoupled writes from observability:** Business writes commit first; analytics/event writes happen post-commit in isolated transactions to prevent logging failures from rolling back business state.
- **Schema invariants are startup-asserted:** Critical column types are checked on app startup, and the application refuses to start on drift. Migrations are additive only.
- **Horizontal scale and concurrency:** The system is built for many simultaneous calls and SMS conversations per account, with stateless web/worker processes and persistent state in PostgreSQL.

## Product

- **Multichannel AI Agent:** Configurable AI agent handling voice calls and SMS, with web chat on the roadmap.
- **Visual Flow Editor:** Drag-and-drop interface for creating and managing AI conversation flows with versioning and simulation. Supports CONDITION nodes (branch on collected variables), per-collect `maxRetries` with a fallback branch (reprompt → fallback → escalate → graceful end), a global "talk to a human" escalation (`call_settings.escalation_number`), and mid-flow knowledge-base Q&A (answer a question, then resume slot collection). Every editor-exposed node field reaches the LLM via `_get_current_node_context`.
- **Pluggable AI Providers:** Supports various STT, LLM, and TTS providers.
- **Twilio Integration:** Manages phone numbers, call handling, sub-account isolation, and call transfers.
- **Role-Based Access Control (RBAC):** Granular permissions for users and administrators.
- **Post Call QA / After-Call Work (ACW):** Configurable system for analyzing call transcripts, dispositions, resolution status, and AI quality scores.
- **Analytics Dashboards:** Customizable dashboards for call and SMS analytics with real-time data, filtering, and export.
- **SMS Management:** Comprehensive SMS handling including webhooks, conversations, analytics, AI handoff, and A2P 10DLC compliance.
- **Feature Entitlement System:** Extensible system for managing subscription tier features and per-account overrides.
- **Canonical Domain Schemas:** For multi-vendor PMS domains (reservations, guests, rooms, rate plans, availability), each vendor's raw response is normalized inside its adapter into a shared, versioned canonical shape so a consumer cannot tell which vendor produced the data. Hybrid: canonicalization is opt-in per endpoint (a seed `canonical_entity` tag); single-vendor/custom endpoints keep their per-endpoint `response_mapping`. The canonical envelope (`{schema_version, entity, items[]}`) rides alongside — never replaces — the raw response and mapped fields.
- **Universal Capability Tools:** The AI calls abstract, vendor-neutral capabilities (`search_availability`, `lookup_reservation`, `book_reservation`, `cancel_reservation`) instead of a specific vendor endpoint. At runtime the capability resolves to the caller's property-scoped provider connection and translates the request into that vendor's shape — "the AI only knows tools, never vendors". Behaves identically on voice, SMS, and in the simulator (all share one registry + resolver). Reads come back canonical; writes return raw+mapped. Resolution reuses the Task #327 fail-closed per-property scoping and refuses to guess when >1 provider matches. Certified integrations only (legacy custom-HTTP + MCP are not capability-resolvable).
- **Per-Property Data Isolation:** An account operating multiple properties (e.g. Hotel A / Hotel B) isolates integration data per property. A `property_id` scope is resolved once at contact start (dialed number → assistant → NULL for legacy/account-global) and carried through the whole session (voice, SMS, simulator). Every integration resolution is scoped to `(account_id, property_id)` and fails closed on cross-property access — the reject happens before any outbound HTTP or credential use. Property-identity keys (`hotel_id`/`property_id`/etc.) are re-forced from the connection's config so a caller/LLM can never redirect a request to another property. Properties CRUD lives at `/api/properties` (`properties.view`/`properties.manage`).
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
- **Simulator↔live parity:** The flow simulator (`api/simulation.py`) must mirror a real call. It runs the *resolved assistant's* `llm_model` per session (fallback `gpt-4o-mini`, matching the new-assistant default) — never hardcode a stronger model, as a better-than-production preview hides real behavior. It resolves the backing assistant (explicit `assistant_id`, permission-checked; else fallback by `tool_set_id` **scoped to `tool.account_id`**, fails closed with no account) to inject the same KB block + escalation number. `tool_set_id` ownership is not validated on assistant create/update, so any assistant lookup by `tool_set_id` must also filter `account_id`. COLLECT_SLOT/COLLECT_FORM nodes do not force `tool_choice` (matching live); API_REQUEST nodes still force it (see engine).
- **Flow escalation function:** The global "talk to a human" tool is a transient in-memory `request_human` tool built by `FunctionMapper.build_escalation_tool()` from `call_settings.escalation_number`; it drives a real Twilio transfer via the `action="transfer"` result path. No DB row / no migration.
- **Generic flow naming:** Built-in confirmation dispatch is `confirm_details` (renamed from `confirm_booking`); the result key is `collected_data` (renamed from `booking_data`). Exact-name dispatch runs before the `confirm_` prefix match, so keep that ordering when adding handlers.
- **Per-property isolation covers certified integrations only:** The fail-closed `(account_id, property_id)` check and identity-key forcing live in `IntegrationClient`, which only handles *certified* integrations (Opera, GuestCentric, etc.). Legacy custom-HTTP `API_REQUEST` tools (operator-configured raw URLs) and MCP connections bypass `IntegrationClient` entirely and are NOT property-checked — a tool_set shared across two properties' assistants with a hardcoded Hotel-A URL will serve A's data to B's callers. Keep property-specific endpoints on certified connections, or scope custom tools per property.
- **Default-property backfill re-stamps NULLs every startup:** `_backfill_default_properties()` assigns each account's NULL-`property_id` phone numbers / assistants / integrations to that account's default property on every boot. This preserves single-property behavior, but once an operator adds a *second* property, any connection they intend to keep account-global (shared) must have its `property_id` explicitly set to NULL again — otherwise it stays bound to the default property and silently stops serving the new property. Deleting a property is refused (HTTP 409) while resources are still bound to it, to avoid `ON DELETE SET NULL` silently promoting a property-private integration to account-global.
- **Capability resolution fails closed and is certified-only:** A capability (`search_availability` etc.) resolves to the single `CONNECTED` certified integration whose seed endpoint is tagged with that `capability`, filtered by per-property scope (property-bound preferred over account-global). **More than one candidate in the chosen tier is ambiguous and returns `None` (reported unavailable) — the resolver never arbitrarily picks a provider**, because silently routing a caller to the wrong PMS is worse than "unavailable". Property-identity keys (`hotel_id`/`property_id`) are deliberately NOT capability parameters — they are re-forced from the resolved connection by `IntegrationClient`, so a caller/LLM can't redirect to another property. The `mutating` flag on `CapabilitySpec` is the single source of truth for the flow non-GET idempotency guard (a capability node has no HTTP method to key off — the method lives on the resolved vendor endpoint), so book/cancel must stay `mutating=True`. Canonicalization is reads-only (`canonical_entity` set on search/lookup, `None` on book/cancel). Legacy custom-HTTP `API_REQUEST` tools and MCP bypass `IntegrationClient` → not capability-resolvable and not property-checked. Booking is not perfectly vendor-neutral in v1: GuestCentric's book needs rate/cancellation-policy/meal-plan ids that only exist after an availability lookup (collected as flow slots, passed through untranslated; a standalone book lacking them fails explicitly, never silently). Adding a vendor for an existing capability = tag its seed endpoint with `capability` + a `capability_params` (canonical→vendor key) map; no per-channel code change.
- **Canonical normalization is opt-in, additive, and certified-only:** A PMS endpoint emits a canonical envelope only if its seed carries a `canonical_entity` tag, and only certified adapters (Opera, GuestCentric) normalize — legacy custom-HTTP `API_REQUEST` tools and MCP bypass `IntegrationClient` and are never canonicalized. `canonical` is purely additive (never replaces `raw_response`/mapped fields). Contract to preserve: a normalizer returns `None` when the expected top-level wrapper key is **absent** ("not canonicalized", so vendor shape drift is visible) but `[]` when the wrapper is **present but empty** ("zero records") — keep those distinct. Numeric coalescing between amount sources must use explicit `is None` checks so a legitimate `0.0` (comp/free stay) survives. Adding a vendor for an existing entity requires a byte-identical cross-vendor parity fixture. Breaking a canonical shape requires bumping `CANONICAL_SCHEMA_VERSION` and updating every normalizer + consumer in lockstep.
- **Integration resilience gates are certified-only and fail-open:** The rate-limit + circuit-breaker gates live inside `IntegrationClient.execute_request`, so like per-property isolation and canonicalization they cover *certified* integrations only — legacy custom-HTTP `API_REQUEST` tools and MCP bypass `IntegrationClient` entirely and are neither throttled nor breaker-protected. All resilience DB ops (`resilience.py`) run in their OWN short-lived `SessionLocal` (never the caller's `db`, which may be a `MagicMock` in tests or hold unrelated pending work) and **fail open** — a resilience-infra error allows the request rather than blocking a live call. Retries only re-issue 429/5xx for idempotent methods (`_SAFE_METHODS`); a `Retry-After` is honored but capped by `backoff_max_s`. One logical `execute_request` == exactly one breaker outcome: a 429/5xx (even after exhausting retries) or transport exhaustion records a failure; any response the vendor actually produced (2xx or a 4xx client error) records success and resets the breaker; an unexpected `Exception` does NOT trip the breaker. Defaults are generous (bucket cap 30 @ 15/s refill, breaker threshold 5 @ 30s cooldown) so a single healthy connection never trips — this is what keeps the no-behavior-change parity gate green. Operators tune per connection via `connection_config["resilience"]` (overrides `auth_config["resilience"]`).
- **OAuth2 authorization_code refresh is terminal on definitive rejection:** The `oauth2_authorization_code` adapter distinguishes transient (network blip → stays CONNECTED so the next request retries) from terminal (non-200, or no refresh token → `TOKEN_EXPIRED`, user must re-consent). Never persist `ERROR` in the adapter — it would trip the status gate and permanently disable auto-refresh. The public `GET /api/integrations/oauth/callback` is intentionally unauthenticated; its only security binding is the unguessable CSRF nonce stored in `connection_config["_oauth_state_nonce"]` and encoded into the OAuth `state` (`{integration_id}:{nonce}`), compared with `secrets.compare_digest` and cleared one-time after use.
- **Light-mode input visibility — hardcoded dark hex classes:** The dashboard (and every page under `(dashboard)/layout.tsx`) wraps content in a `.themed-app` div. `globals.css` contains a whitelist of dark hex bg overrides scoped to `[data-theme="light"] .themed-app` — any `bg-[#xxx]` class NOT in that whitelist stays black in light mode, making text invisible. **Rule: always use `bg-[#1a1a1a]` (or another already-registered hex) for flow-editor inputs and cards. Never use CSS 3-digit shorthands like `bg-[#111]` — they generate a different Tailwind class name and won't match the 6-digit registry entry.** When adding any new dark hex class anywhere inside `.themed-app`, immediately add its light-mode override to the `/* Background overrides */` block in `globals.css`.

## Pointers

- **Pipecat Framework:** [Link to Pipecat documentation]
- **Twilio Docs:** [Link to Twilio documentation]
- **Sonner React Toasts:** [Link to Sonner documentation]
- **React Flow:** [Link to React Flow documentation]
- **Recharts:** [Link to Recharts documentation]
- **OpenAI API:** [Link to OpenAI documentation]