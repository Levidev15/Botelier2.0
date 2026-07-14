# Integration Seed Template

**This file is a pointer, not a spec.** For the full, accurate, worked-example-driven guide to adding a new integration — seed shape, `auth_config` per `auth_type`, `required_fields` including `show_when`, endpoint definitions, registration, runtime auth behavior, flow-editor wiring, docs, and testing — see:

**[`docs-site/docs/integrations/adding-a-new-integration.md`](../../../../docs-site/docs/integrations/adding-a-new-integration.md)** (rendered at `/integrations/adding-a-new-integration` in the docs site).

Read `opera_integration.py` (`auth_type: "oauth2_client_credentials"`) and `guestcentric_integration.py` (`auth_type: "basic_or_jwt"`) in this directory alongside that guide — they are the real, current worked examples. Do not hand-derive the `IntegrationType` shape from an old snapshot of this file; the fields below (`category`, `base_url`, `config_schema`, a hardcoded `id`, and an `ON CONFLICT` upsert) do not match the current model or seed pattern and are kept here only as a historical note.

## Quick reference (see the guide for the real thing)

- File naming: `seeds/<name>_integration.py`, exposing `def seed_<name>_integration(db_session): ...`
- `auth_type` today is one of `"oauth2_client_credentials"` or `"basic_or_jwt"` — not `"oauth2"`, `"api_key"`, or `"basic_auth"`.
- The seed function queries `IntegrationType` by `slug`, updates it in place if found, otherwise constructs and inserts a new row — there is no `INSERT ... ON CONFLICT` upsert and no hardcoded `id`.
- `IntegrationType` fields are `slug`, `name`, `description`, `logo_url`, `provider`, `auth_type`, `documentation_url`, `auth_config`, `required_fields`, `endpoints` (set via `set_auth_config` / `set_required_fields` / `set_endpoints`). There is no top-level `category`, `base_url`, or `config_schema` field.
- Runtime engine now lives in `services/integration_runtime/`; `services/integration_client.py` is a re-export facade. Provider-specific auth/refresh/header logic lives in `integration_runtime/adapters/`. Reusing an existing `auth_type` needs no runtime code; a brand-new auth model means a new adapter plus a `registry.py` entry.

## Registration

After creating the seed file, add it to `seeds/__init__.py`'s `seed_all_integrations`:

```python
try:
    from botelier.seeds.<name>_integration import seed_<name>_integration
    seeds.append(("<name>", "<slug>", seed_<name>_integration))
except ImportError as exc:
    logger.warning(f"Could not import <name> seed: {exc}")
```
