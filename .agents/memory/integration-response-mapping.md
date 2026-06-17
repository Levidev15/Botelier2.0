---
name: Integration response-mapping precedence & OHIP shapes
description: How flow/integration responseMapping resolves, the three places that must stay in lockstep, and OHIP OpenAPI response-wrapper shapes.
---

# Integration response-mapping resolution

## Single shared extractor
Both `IntegrationClient` and `flow_executor` resolve response paths through ONE
module-level `extract_json_value(data, path)` in
`botelier/backend/botelier/services/integration_client.py`. It strips the `$`/`$.`
prefix, supports dot keys, `[n]` bracket index, legacy `.0.` index, and `[*]`
wildcard (flattens + dedupes → list; scalar otherwise; `None` when empty).

**Why:** a previously-divergent local extractor in `flow_executor` never stripped
`$.`, so any `$.`-prefixed responseMapping silently resolved to `None` (the
"silent API node" class of bug). Keep both call sites delegating to the shared
function — never reintroduce a second path parser.

## Three places must change in lockstep
When you fix an integration endpoint's `responseMapping`, update ALL of:
1. The seed — `botelier/backend/botelier/seeds/*_integration.py` (reseeds into
   `integration_types.endpoints_config` on backend startup via `set_endpoints`).
2. The frontend flow template — `botelier/frontend/components/flow-editor/store.ts`
   (e.g. `OPERA_OHIP_BOOKING_TEMPLATE`), including `autoMappingSource`.
3. Already-saved flows — `flow_versions.flow_config` JSONB rows in the DB.

**Why:** node-level `responseMapping` OVERRIDES the seed (`_effective_response_variables`
prefers node `response_variables`/mapping, else seed). Fixing only the seed leaves
existing saved flows and the template still broken. Update saved rows with a precise
quoted-string replace on `flow_config::text` cast back to `::jsonb`.

## "today" sentinel default
`_apply_endpoint_defaults` resolves a variable `default == "today"` to the current
UTC date (`YYYY-MM-DD`). Don't drop it — required date params (e.g. arrivals) need a
concrete value when no caller value is supplied. Caller-supplied values still win.

## OHIP (Oracle OPERA Cloud) response-wrapper shapes (from OpenAPI specs)
- Availability (PAR `/par/v1/.../availability`): rooms/rates are nested —
  `hotelAvailability[*].roomStays[*].roomRates[*].roomType` / `.ratePlanCode`.
- Reservations list (RSV `/rsv/v1/hotels/{id}/reservations`): `reservations.reservationInfo` (array) + `reservations.count`. Supports `reservationStatuses`, `arrivalStartDate`, `arrivalEndDate`, `givenName`, `surname`.
- Profiles search (CRM `/crm/v1/profiles`): `profileSummaries.profileInfo` + `.count`. Query params: `givenName`, `profileName`, `email`, `phone` (NO `surname`/`phoneNumber`).
- Single profile (CRM `/crm/v1/profiles/{id}`): wrapper `profileDetails`.
- Room types (LOV `/lov/v1/listOfValues/hotels/{id}/roomTypes`): `listOfValues.items`.
- Rate plans (RTP `/rtp/v1/hotels/{id}/ratePlans`): top-level `ratePlans` array.
