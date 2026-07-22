---
name: Spec import fail-closed & format detection
description: Universal API Adapter spec import — content-based format detection, zero-endpoint rejection, YAML fallback, varchar(64) spec_version limit
---

# Spec import fail-closed & format detection

**Rule:** In the spec importer (`services/spec_importer/`), detected content type always wins over the user-declared format chip (`detect_spec_kind()`), and any parse that yields zero endpoints/requests must raise `ValueError` *before* `db.add`/`db.flush` — never persist an empty "Imported API" row with HTTP 200.

**Why:** A user imported a Postman collection URL with "Swagger" selected; the OpenAPI parser found no `paths`, silently persisted a 0-endpoint row, and returned 200 — "nothing happened" from the user's view. Silent success on garbage input is worse than a clear 400.

**How to apply:**
- New spec formats: add detection to `detect_spec_kind()` and raise on empty parse results.
- API layer (`integration_builder.py`) parses upload/URL bytes via `_parse_spec_bytes` (JSON → YAML fallback, rejects non-dict). Don't reintroduce `json.loads`-only parsing — YAML specs are common.
- `integration_types.spec_version` is **varchar(64)**: Postman's `info.schema` is a full URL (>64 chars) — store the extracted version (e.g. "2.1.0") and clamp all writers to 64 chars or inserts 500 with StringDataRightTruncation.
- Known non-blocking hardening gaps (authenticated + `integrations.manage` gated): no response-size cap on spec URL fetch; PyYAML `safe_load` alias-expansion DoS possible on hostile specs.
