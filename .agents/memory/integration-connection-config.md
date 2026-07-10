---
name: Integration connection_config (non-secret per-connection constants)
description: How property-level constants (e.g. hotelId) are stored/resolved for account integrations, and the _build_url substitution invariants.
---

# Non-secret connection settings via the `storage` flag

Account integrations split per-connection values into two stores on the
`AccountIntegration` row: `credentials_encrypted` (secrets) and `connection_config`
(plaintext JSON). To route a `required_fields` entry into `connection_config` instead
of the encrypted blob, flag it `"storage": "connection_config"` in the seed. Use this
for non-secret, property-level constants that never change call-to-call (GuestCentric
`hotelId` is declared this way). Keep real secrets un-flagged so they stay encrypted.

**Why:** the backend already auto-applies `connection_config` everywhere
(`_apply_endpoint_defaults` merges it as lowest-priority for query/body;
`_inject_connection_config_to_slots` injects it into flow slots for path params). The
only gap was a way to *set* it from the UI. The storage flag reuses the generic
`required_fields` rendering (ConnectModal/EditModal) with zero frontend schema change —
the server splits by flag (`_split_fields_by_storage` in `api/integrations.py`).
Industry pattern: Airbyte per-field secret flags, Nango/Paragon credentials-vs-config split.

**How to apply:**
- `/connect` and credentials `PATCH` split incoming fields by the flag; PATCH also
  drops any config key still lingering in the credentials blob (lazy migration so the
  two stores can't diverge). GET-credentials merges `connection_config` back so the
  edit form pre-fills it. Validators receive a combined `{**conn_config, **creds}` view.
- Keep the `credentials` read-side fallback permanently for legacy connections; no
  data migration needed — values migrate lazily on the next edit save.

# `_build_url` hotel_id substitution invariants (subtle, cost a bug each)

1. **Double-brace before single-brace.** `{{hotel_id}}` CONTAINS `{hotel_id}` as a
   substring, so `.replace("{hotel_id}", v)` run first corrupts `{{hotel_id}}` →
   `{v}` (outer braces survive). Always replace `{{...}}` forms before `{...}` forms.
2. **camelCase → snake bridge lives in `_build_url`, not slot injection.**
   connection_config stores the field key `hotelId` (camelCase), but paths use
   `{{hotel_id}}` (snake). `_substitute_variables`/`_inject_connection_config_to_slots`
   match on exact key, so they will NOT map `hotelId`→`{{hotel_id}}`. The `_build_url`
   fallback accepts both `hotel_id` and `hotelId` from BOTH conn_config and credentials
   and does the `.replace()` for all four `{}`/`{{}}` × snake/camel forms.
3. **Path and `basic_auth_query_params` must use the SAME precedence** —
   connection_config first, then credentials — or a stale credentials copy makes the
   `?hotelId=` query param disagree with the resolved path segment.

**Behavioral note:** JWT GuestCentric connections with `hotelId` set now get
`?hotelId=` appended (the `basic_auth_query_params` block runs for the whole
`basic_or_jwt` auth_type, both methods — do NOT gate it by auth_method, JWT needs
`apikey` appended too). GuestCentric documents `hotelId` as a scoping param, so this
is expected. OHIP (`oauth2_client_credentials`) is unaffected: no storage-flagged
fields, empty connection_config, and its query-param block never runs.
