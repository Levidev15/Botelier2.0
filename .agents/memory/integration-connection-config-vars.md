---
name: Integration connection_config variable injection
description: How property-level constants (hotel_id, hotel_name, currency, etc.) should be stored and how they flow into API calls and flow variables.
---

## The rule

Property-level constants for an integration — things that are fixed per hotel/property (hotel_id, hotel_name, hotel_reservations_email, default currency) — must be stored in `account_integrations.connection_config` (a JSON text column). They must NOT be collected from callers each turn and must NOT be hardcoded in the flow.

## How they now flow (3 layers, lowest → highest priority)

1. **`_apply_endpoint_defaults` in `integration_client.py`** — merges `integration.get_connection_config()` into `effective_vars` before endpoint defaults and caller variables. Fixes the API call itself.
2. **`_inject_connection_config_to_slots` in `flow_executor.py`** — called at the top of `_handle_integration_api_request` before `execute_and_log`. Injects connection_config keys into `collected_slots` (non-destructive: never overwrites existing slots). Fixes downstream SET_VARIABLE nodes (e.g. `build_hotels_array` uses `"{{hotel_id}}"` to build the hotels array for cancellation-policy lookups).
3. **Fail-fast in `_build_url`** — after all substitutions, `re.findall(r"\{\{(\w+)\}\}", path)` detects any unresolved path variables and raises `_MissingRequiredVariables`. This surfaces a clear error ("Missing required variables: hotel_id") instead of forwarding a malformed URL and getting a cryptic 422 from the upstream API.

## Why

Before this fix: `{{hotel_id}}` in GuestCentric endpoint paths was never resolved in the flow simulator (or live flow), causing 422 "Invalid hotel id in url request". The `build_hotels_array` SET_VARIABLE node also produced `["{{hotel_id}}"]` literally, breaking cancellation policy calls. The `create_booking` endpoint similarly needed hotel_name, hotel_reservations_email from property config.

## How to apply

When connecting a GuestCentric (or similar) integration, store these fields in `connection_config` via the integration connection editor:
- `hotel_id` — the property's GuestCentric hotel ID
- `hotel_name` — used in booking payloads
- `hotel_reservations_email` — used in booking payloads
- `currency` (optional) — default currency (EUR or USD); falls back to GuestCentric default (EUR) if absent

The GuestCentric credentials already support `hotelId` via `basic_auth_query_params` (appended to every request as `?hotelId=...`), but the PATH variable `{{hotel_id}}` is resolved from credentials AND now also from connection_config.

## Double-log note

`ActionExecutor._write_logs` writes one `IntegrationActionInvocation` + one `IntegrationCallLog` per call. `IntegrationClient._write_call_log` also writes one `IntegrationCallLog` on the success/failure path inside `execute_request`. This results in 2× `integration_call_logs` rows per integration API call — a known cosmetic/analytics duplication, not a functional bug.
