---
name: JWT auth query params
description: Providers (e.g. GuestCentric) that require a credential on every request including JWT login/refresh; the auth_request_query_params config and the three JWT code paths that must stay in lockstep.
---

Some integration providers require a credential (e.g. GuestCentric's `apikey`) as a URL query param on **every** request — including the JWT login and refresh calls, not only data requests. Omitting it makes token login/refresh fail with a 400 like "Apikey parameter is required!".

## The rule
- Which credential keys ride auth requests is declared per provider in `auth_config['auth_request_query_params']` (a list of credential-field keys), so it stays provider-agnostic. The shared helper `build_auth_request_query_params(auth_config, credentials)` in `services/integration_client.py` builds `{key: value}` from credentials and raises `ValueError` (fail-closed) when a declared key is missing/empty.
- **Why:** GuestCentric rejects JWT login/refresh without `apikey`. The Basic Auth *data* path already sent it (via `basic_auth_query_params`), which masked the gap in the JWT auth paths for a long time.

## The three JWT paths that must change in lockstep
Attach `params=auth_query_params or None` to all of these whenever touching JWT auth:
1. `obtain_jwt_token` login POST — `api/integrations.py`
2. `refresh_oauth_token` JWT-branch refresh POST — `api/integrations.py` (its login fallback delegates to `obtain_jwt_token`, so it inherits the fix)
3. `_refresh_jwt_token` refresh POST **and** login POST — `services/integration_client.py`

## How to apply
- New provider whose creds must ride auth calls: add the key(s) to that provider's seed `auth_config['auth_request_query_params']`. The seed upserts on every backend startup, so already-seeded DB rows get updated on restart.
- Providers that don't declare it: the helper returns `{}` → `params=None` → identical to prior behavior (no regression; confirmed for Opera which is oauth2 and never enters the JWT branch anyway).
- Security: the credential rides the outbound auth URL query string only; httpx doesn't log request URLs, and existing log redaction (`_COMMON_SECRET_PARAMS`) covers `apikey=`.
