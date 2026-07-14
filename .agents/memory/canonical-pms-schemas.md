---
name: Canonical PMS domain schemas
description: How vendor-agnostic PMS entities (reservation/guest/room/rate_plan/availability) are normalized, and the contracts to keep consistent.
---

# Canonical PMS domain schemas

Vendor-neutral shapes in `integration_runtime/canonical.py`; normalizers live INSIDE each
vendor adapter (`adapters/opera_cloud.py`, `adapters/guestcentric.py`). The shared
`IntegrationClient._apply_canonical` calls `adapter.normalize(entity, endpoint_id, raw)`
after normal response processing and attaches the envelope to `APIResponse.canonical`
(threaded to `ActionExecutionResult.canonical`). Envelope = `{schema_version, entity, items[]}`.

## Opt-in, and which paths it covers
- An endpoint canonicalizes only if its seed carries a `canonical_entity` string tag
  (plain string — seeds never import the canonical module). Untagged / single-vendor /
  custom endpoints keep their per-endpoint `response_mapping` untouched.
- Runs ONLY for certified adapters (Opera, GuestCentric). Legacy custom-HTTP API_REQUEST
  tools and MCP bypass `IntegrationClient` entirely, so they are never canonicalized —
  same blind spot as the per-property isolation check.
- `canonical` is purely additive; it never replaces `raw_response` or mapped fields.

## The None-vs-[] contract (keep consistent)
- `normalize()`/helpers return **None** when the expected top-level wrapper key is ABSENT
  (or raw isn't a dict) → "not canonicalized". Return **[]** only when the wrapper is
  PRESENT but holds no records → "canonicalized, zero records".
- **Why:** a vendor shape drift must surface as `canonical=None`, not a misleading
  "zero reservations". Conflating them would silently report empty results to consumers.
- **How to apply:** each per-entity helper first does `if "<wrapper>" not in raw: return None`,
  then returns a (possibly empty) list. Normalization is best-effort/isolated: raising or
  returning None can never break the underlying request (double try/except: adapter + client).

## Cross-vendor parity is the contract
- The headline guarantee: the SAME booking scenario normalizes to a byte-identical canonical
  dict across Opera and GuestCentric (`tests/test_canonical_normalization.py`, fixtures in
  `tests/fixtures/pms/<vendor>/`). Adding a vendor for an existing entity requires a parity fixture.
- Fixtures are hand-authored, so watch for fixture-vs-reality drift. Opera `search_reservations`,
  `get_arrivals`, `get_in_house_guests` are tagged `reservation` but only `get_reservation` has a
  fixture — validate their real OHIP wrapper before a consumer relies on them.

## Versioning
- Adding an optional field = backwards-compatible, keep `CANONICAL_SCHEMA_VERSION`.
- Rename/remove/retype an existing field = breaking: bump the version AND update every
  normalizer + consumer in lockstep. Version travels inside every envelope so consumers can branch.
- Numeric coalescing must preserve legitimate `0.0` (comp/free stay) — use explicit
  `is None` checks, never `a or b`, when falling back between amount sources.
