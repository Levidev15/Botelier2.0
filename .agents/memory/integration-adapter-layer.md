---
name: Integration runtime adapter layer
description: How per-vendor auth/refresh/URL/header logic is layered behind IntegrationClient, and the fail-closed coupling that keeps the generic default adapter safe.
---

# Integration runtime adapter layer

The integration runtime lives in `services/integration_runtime/` (types, jsonpath,
redaction, locks, authparams, client, and `adapters/`). `services/integration_client.py`
is a **pure re-export facade** — add logic to the runtime modules, never to the facade.

Provider-specific auth/refresh/URL/header logic is delegated to per-vendor **adapters**
resolved per integration by **slug → auth_type → generic DefaultAdapter**
(`adapters/registry.py`, singletons `OPERA_ADAPTER` / `GUESTCENTRIC_ADAPTER` /
`DEFAULT_ADAPTER`).

## Rules / constraints

- **Adapters must never import `client.py`** (import cycle). Direction is one-way:
  adapters import base/authparams/models/ssrf_safe_transport; `client` imports `.adapters`;
  the facade imports both.
- **The oauth/jwt refresh shims must call the SPECIFIC adapter, not resolve by
  integration_type.** `_refresh_oauth_token` → `OPERA_ADAPTER.refresh_oauth`,
  `_refresh_jwt_token` → `GUESTCENTRIC_ADAPTER.refresh_jwt`. **Why:** parity tests pass
  objects with no `integration_type`, so resolution would fail. Only the generic
  `_refresh_token` path resolves via the registry.
- **Oracle gateway-URL SSRF allow-list is single-sourced** in `adapters/opera_cloud.py`
  (`_validate_opera_gateway_url` raises `ValueError`, `_ORACLE_ALLOWED_SUFFIXES`). The
  api-edge validator in `api/integrations.py` delegates and translates `ValueError` →
  `HTTPException(400)`, preserving the exact 4 detail strings. Don't reintroduce a second
  copy of the allow-list.

## The DefaultAdapter safety coupling (important for new auth types)

DefaultAdapter is genuinely generic (`needs_token=False`, no-op refresh, bearer/base_url).
An unknown `auth_type` therefore runs **token-less** instead of the old fall-through to the
Opera OAuth path. This is safe **only because** the connect/reconnect routes in
`api/integrations.py` fail closed with "Unsupported auth type" — no connected integration
can carry an unknown auth_type today.

**How to apply:** when adding a NEW `auth_type` (Task #327+ / future integrations), you
MUST add a matching adapter + `registry.py` entry, or connected integrations of that type
will silently run token-less. Reusing an existing auth_type (`oauth2_client_credentials`,
`basic_or_jwt`) needs no runtime code.
