---
name: OAuth callback completion & refresh locking
description: Why OAuth completion is an authenticated frontend endpoint (not the public callback), and the no-unlocked-refresh rule.
---

## OAuth completion flow
- The registered redirect_uri (`GET /oauth/callback`, API host) is a **stateless hop**: no cookie, no DB, no code exchange. It 302s to `{FRONTEND_URL}/dashboard/integrations/oauth/complete` — target comes ONLY from config (`get_frontend_url()`, falls back to `get_public_base_url()`), never from request data (Origin header in state = code-leak/open-redirect).
- The actual exchange is `POST /oauth/complete`, **authenticated** (Bearer). Check order matters and must never regress: parse state → `_assert_account_access` → load integration + verify ownership → validate/consume one-time nonce → only then handle provider `error` or exchange the code. Handling `error` earlier let any authenticated user cross-tenant-DoS pending connections.
- **Why not a browser-binding cookie:** host-only cookies don't survive dashboard-host vs PUBLIC_BASE_URL API-host topology; authenticated completion is stronger (forwarded links fail unless the recipient is logged into the same account) and topology-agnostic.
- State format: `{account_id}:{integration_id}:{nonce}` — no user-controlled data allowed in state.

## Token refresh locking
- Refresh must NEVER run unlocked. Advisory-lock connect/execute failures retry (`_LOCK_ACQUIRE_RETRIES`/backoff constants in `integration_runtime/locks.py`) then raise `TokenRefreshLockUnavailableError`.
- That error must be caught on **every** `_refresh_token_with_lock` call site (proactive pre-request AND forced 401/403 refresh) via the shared helper, surfacing a transient AUTH_ERROR APIResponse without tripping the circuit breaker.

**How to apply:** any change to OAuth connect flow, redirect URIs, or refresh locking must preserve the check order, config-only redirect targets, and lock-error handling on all refresh paths. Regression tests live in `tests/test_resilience_and_oauth.py`.
