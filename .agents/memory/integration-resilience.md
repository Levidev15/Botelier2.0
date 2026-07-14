---
name: Integration resilience & 3-legged OAuth2
description: Cross-worker rate limiting / retry backoff / circuit breaking and authorization_code OAuth2 in the integration runtime — the non-obvious constraints.
---

# Integration resilience gates + 3-legged OAuth2

## Where the gates live (and what they DON'T cover)
The rate-limit + circuit-breaker gates live INSIDE `IntegrationClient.execute_request`
(after the url is built, after property/status/token checks). Like per-property
isolation and canonicalization, that means they cover **certified integrations only**.
Legacy custom-HTTP `API_REQUEST` tools and MCP bypass `IntegrationClient` entirely, so
they are neither throttled nor breaker-protected. This is the same chokepoint pattern —
don't try to move the gates elsewhere expecting broader coverage.

## Fail-OPEN is deliberate
**Why:** a resilience-infra bug (DB blip, lock timeout) must never take down the live
integration path it is meant to protect. Every stateful op in `resilience.py` catches
its own exception and returns "allow". Do not "harden" this into fail-closed.

## Own short-lived SessionLocal, never the caller's db
**Why:** committing the caller's session would flush its unrelated pending work, and in
unit/parity tests the caller's `db` is a `MagicMock`. Every resilience op opens its own
`SessionLocal`, does `INSERT ON CONFLICT DO NOTHING` + `SELECT ... FOR UPDATE` +
commit + close. That row lock is what makes the token bucket / breaker cross-worker safe.

## One execute_request == exactly one breaker outcome
- 429 or 5xx (even after exhausting retries) → `circuit_record_failure`
- transport exhaustion (timeout/network after retries) → `circuit_record_failure`
- any response the vendor actually produced — 2xx OR a 4xx client error (auth,
  not-found, validation) → `circuit_record_success` (the vendor is demonstrably up)
- an unexpected `Exception` (our own bug) → does NOT touch the breaker
**How to apply:** if you add a new outcome branch to the retry loop, decide its breaker
verdict explicitly; never double-record within a single call.

## Retries are idempotent-only
Only methods in `_SAFE_METHODS` re-issue on 429/5xx. A write is never re-applied. A
`Retry-After` header is honored but capped by `backoff_max_s` so a hostile/huge value
can't stall a live call. Backoff is full-jitter (uniform in [0, capped]).

## Generous defaults keep the parity gate green
Defaults: bucket cap 30 @ 15/s refill; breaker threshold 5 @ 30s cooldown. A single
healthy connection never trips, so `test_integration_client_parity.py` (asserts exactly
1 captured request + exact URL) stays passing. `ResilienceConfig.from_integration`
merges `connection_config["resilience"]` over `auth_config["resilience"]` over defaults —
operators tune per connection with no code change. A malformed override silently falls
back to defaults (never breaks the request path).

## State tables carry NO foreign keys
`integration_rate_limits` / `integration_circuit_breakers` (PK = integration_id) are
ephemeral operational counters, not business records. No FKs = an orphan row after an
integration delete is harmless, AND the resilience path stays exercisable when tests
inject a detached `AccountIntegration` that was never persisted. Created via
`CREATE TABLE IF NOT EXISTS` in `_ADDITIVE_MIGRATIONS`.

## OAuth2 authorization_code: transient vs terminal
Adapter (`adapters/oauth2.py`, auth_type `oauth2_authorization_code`) has `needs_token=True`
so the shared advisory-lock refresh runs before each request. Refresh grant:
- network blip → keep CONNECTED (next request retries)
- non-200, or no refresh token available → `TOKEN_EXPIRED` (user must re-consent)
**Why:** never persist `ERROR` in the adapter — it trips the status gate and permanently
disables auto-refresh. Refresh-token rotation only overwrites when the provider returns
a new one (many keep the original valid).

## OAuth2 callback is public but nonce-bound
`GET /api/integrations/oauth/callback` has no `get_current_user` dependency (the
consenting user's session lives with the provider). Its only security binding: a random
nonce (`secrets.token_urlsafe`) stored in `connection_config["_oauth_state_nonce"]` and
encoded into the OAuth `state` as `{integration_id}:{nonce}`. On callback: validate
UUID, load integration, `secrets.compare_digest` the nonce, then clear it one-time
(so state can't be replayed) regardless of outcome. `POST .../oauth/authorize` is
`integrations.manage`-gated and creates the CONNECTING integration + returns the consent
URL. Token exchange uses `SSRFSafeTransport`.
