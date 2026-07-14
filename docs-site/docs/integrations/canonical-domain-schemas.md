---
id: canonical-domain-schemas
title: Canonical Domain Schemas
sidebar_label: Canonical Domain Schemas
---

# Canonical Domain Schemas

Different PMS/CRS vendors return the same business concepts in wildly different JSON shapes. Oracle Opera Cloud describes a reservation one way; GuestCentric describes the same reservation another way. **Canonical domain schemas** give Botelier one vendor-neutral vocabulary for these concepts, so that once a vendor response is normalized, a consumer **cannot tell which vendor produced the data**.

This page is the reference for what the canonical shapes are, how they are produced, and how to extend them. The schemas live in `botelier/backend/botelier/services/integration_runtime/canonical.py`.

## Scope

Canonicalization covers the **PMS domain only**:

- `reservation`
- `guest`
- `room`
- `rate_plan`
- `availability`

Non-PMS domains are intentionally out of scope. Capability-level tools built on top of the canonical shapes are also out of scope for this layer — this layer only normalizes data.

## Hybrid design: canonical is opt-in per endpoint

Canonicalization is **not** applied to every endpoint. It is a deliberate, per-endpoint opt-in:

- **Multi-vendor domains** (a reservation exists in both Opera and GuestCentric) are canonicalized so a consumer gets one shape regardless of provider.
- **Single-vendor or custom endpoints** keep using their existing per-endpoint `response_mapping` untouched. There is no benefit to inventing a shared shape for something only one vendor offers.

An endpoint opts in by adding a `canonical_entity` field to its seed definition:

```python
{
    "id": "get_reservation",
    "canonical_entity": "reservation",   # <-- opts this endpoint into canonicalization
    "category": "Reservations",
    "name": "Get Reservation by Confirmation Number",
    # ... method, path, variables, response_mapping (unchanged) ...
}
```

The string value must match one of the `CanonicalEntity` values (`reservation`, `guest`, `room`, `rate_plan`, `availability`). Seeds use a **plain string** here and never import the canonical module.

## The envelope

An adapter's `normalize()` returns a **versioned envelope**, which the runtime attaches to `APIResponse.canonical` (and, downstream, `ActionExecutionResult.canonical`):

```json
{
  "schema_version": "1",
  "entity": "reservation",
  "items": [
    {
      "reservation_id": "R-12345",
      "confirmation_number": "CONF987",
      "status": "confirmed",
      "guest_first_name": "Jane",
      "guest_last_name": "Doe",
      "arrival_date": "2026-08-01",
      "departure_date": "2026-08-03",
      "room_type_code": "DLX",
      "rate_plan_code": "BAR",
      "adults": 2,
      "children": 0,
      "total_amount": 450.0,
      "currency": "USD"
    }
  ]
}
```

Three states are deliberately distinct:

| Result | Meaning |
|---|---|
| `canonical = None` | **Not canonicalized.** Either the endpoint wasn't tagged, the request failed, or the normalizer opted out / errored. The per-endpoint `response_mapping` is still present and authoritative. |
| `items: []` | **Canonicalized successfully, no records.** e.g. a search with zero matches. |
| `items: [ {...} ]` | **Canonicalized with records.** |

`canonical` is purely **additive** — it never replaces `raw_response` or the per-endpoint mapped fields. Existing consumers that don't know about `canonical` are unaffected.

## Where normalization lives

Normalizers live **inside each vendor adapter**, never in the shared runtime:

- `adapters/opera_cloud.py` — `reservation`, `guest`, `room`, `rate_plan`, `availability`
- `adapters/guestcentric.py` — `reservation`, `availability`

This keeps every vendor quirk contained in that vendor's adapter. The `canonical.py` module only owns the **target shapes** and the **envelope**; it has no vendor knowledge. The shared `IntegrationClient` calls `adapter.normalize(entity, endpoint_id, raw)` after normal response processing and is otherwise vendor-agnostic.

Normalization is **best-effort and fully isolated**: a normalizer that raises or returns `None` simply leaves `canonical` unset. It can never break the underlying request or its per-endpoint mapping.

## Canonical shapes

All fields are optional (`None` when the vendor didn't supply them). IDs are coerced to strings; counts to ints; amounts to floats.

### Reservation

| Field | Type | Notes |
|---|---|---|
| `reservation_id` | str | Vendor's primary reservation identifier |
| `confirmation_number` | str | Guest-facing confirmation code |
| `status` | str | One of the `ReservationStatus` values below |
| `guest_first_name` | str | |
| `guest_last_name` | str | |
| `arrival_date` | str | Check-in date |
| `departure_date` | str | Check-out date |
| `room_type_code` | str | |
| `rate_plan_code` | str | |
| `adults` | int | |
| `children` | int | |
| `total_amount` | float | |
| `currency` | str | |

**Reservation status vocabulary** (`ReservationStatus`): `confirmed`, `in_house`, `checked_out`, `cancelled`, `no_show`, `waitlisted`, `unknown`. Each adapter maps its own vendor status strings onto these values.

### Guest

| Field | Type |
|---|---|
| `guest_id` | str |
| `first_name` | str |
| `last_name` | str |
| `email` | str |
| `phone` | str |

### Room

| Field | Type |
|---|---|
| `room_type_code` | str |
| `name` | str |
| `description` | str |
| `max_occupancy` | int |

### Rate Plan

| Field | Type |
|---|---|
| `rate_plan_code` | str |
| `name` | str |
| `description` | str |
| `currency` | str |

### Availability

| Field | Type |
|---|---|
| `room_type_code` | str |
| `room_name` | str |
| `rate_plan_code` | str |
| `arrival_date` | str |
| `departure_date` | str |
| `available` | bool |
| `total_amount` | float |
| `currency` | str |

## Versioning policy

The canonical shapes are a **contract** — treat them like a public API. The version travels inside every envelope (`schema_version`) so consumers can branch on it.

- **Adding a new optional field** is backwards-compatible — keep `CANONICAL_SCHEMA_VERSION` the same.
- **Renaming, removing, or changing the type/meaning** of an existing field is a **breaking** change: bump `CANONICAL_SCHEMA_VERSION` and update every normalizer **and** consumer in lockstep.

## Extending: adding an entity or a vendor

**A new canonical entity:**

1. Add a value to `CanonicalEntity` and a dataclass in `canonical.py`.
2. Implement its normalizer branch inside each relevant vendor adapter.
3. Tag the appropriate seed endpoint(s) with the new `canonical_entity`.
4. Add fixtures + tests (see below).

**A new vendor for an existing entity:**

1. Implement the entity's branch in the new vendor's adapter `normalize()`.
2. Tag that vendor's seed endpoint(s) with the matching `canonical_entity`.
3. Add a cross-vendor parity fixture proving the new vendor produces the **same** canonical dict for the **same** scenario.

## Testing

Normalizers are pure functions of the raw JSON body — no DB, no HTTP. Tests call `ADAPTER.normalize(...)` directly with recorded raw responses in `botelier/backend/tests/fixtures/pms/<vendor>/<endpoint>.json`.

The headline guarantee is a **cross-vendor parity** test: Opera and GuestCentric fixtures describing the *same* booking must normalize to a **byte-identical** canonical dict. See `botelier/backend/tests/test_canonical_normalization.py`.
