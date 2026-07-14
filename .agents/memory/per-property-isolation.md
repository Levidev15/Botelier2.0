---
name: Per-property data isolation
description: How integration data is isolated per property within one account, why the enforcement lives at the IntegrationClient chokepoint, and what it does NOT cover.
---

# Per-property data isolation

An account can operate multiple properties (Hotel A / Hotel B). A caller reaching
one property must never receive another property's integration data. Scope is a
nullable `property_id` on `phone_number`, `assistant`, and `AccountIntegration`
(NULL = account-global / shared).

## Where enforcement lives — and why
All fail-closed enforcement is in `IntegrationClient`
(`services/integration_runtime/client.py`), NOT at FlowExecutor init.

**Why:** the voice `FlowExecutor` is constructed with `db_session=None` at init, so
a property injection there is unreliable. `IntegrationClient` is instantiated in
exactly ONE place (`ActionExecutor._execute_integration`), and its
`_apply_endpoint_defaults` output (`effective_vars`) is the sole input to both
`_build_url` and `_build_body`. So the client is a genuine single chokepoint that
covers voice, SMS, simulator, and any future channel automatically.

**How to apply:** thread `property_id` through `ActionContext` → `IntegrationClient(property_id=...)`.
`_is_property_allowed` allows when session property is None (legacy), or the
integration is account-global (NULL), or they match; rejects otherwise. The reject
returns `AUTH_ERROR` BEFORE any credential decrypt / token refresh / outbound HTTP.

## Identity-key forcing
`PROPERTY_IDENTITY_KEYS` (singular keys: hotel_id/hotelId/property_id/propertyId/
hotel_code/property_code) are re-forced from the connection's `connection_config`
ON TOP of caller/LLM vars, so a supplied hotel_id can't redirect to another
property. Only keys actually present in `connection_config` are forced, so
account-global connections that legitimately let a flow choose a hotel are
unaffected. The plural `hotels` array is intentionally NOT an identity key.

## Session property resolution
`services/property_scope.resolve_session_property_id(dialed_number, assistant, db)`
precedence: dialed phone's `property_id` → assistant's `property_id` → None.
Derived only from trusted server-side signals, never from caller/LLM input.
Resolved once at contact start and carried through the whole session.

## What it does NOT cover (residual limitations)
- **Legacy custom-HTTP `API_REQUEST` tools and MCP connections bypass
  `IntegrationClient` entirely** — they are NOT property-checked. A tool_set shared
  across two properties' assistants with a hardcoded Hotel-A URL will serve A's
  data to B's callers. Keep property-specific endpoints on certified connections.
- **`ON DELETE SET NULL` is a fail-open trap:** deleting a property would silently
  promote a property-private integration to account-global. The Properties API
  DELETE therefore refuses (HTTP 409) while any phone/assistant/integration is
  still bound.
- **Startup backfill re-stamps NULLs** to the default property every boot. Once a
  second property is added, connections meant to stay shared must have `property_id`
  explicitly re-NULLed or they silently stop serving the new property.
