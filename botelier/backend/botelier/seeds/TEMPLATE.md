# Integration Seed Template

Use this template as the starting point for a new integration seed module.

## File naming

`seeds/<name>_integration.py`

## Required function signature

```python
def seed_<name>_integration(db: Session) -> None:
    """
    Seed the <Name> integration type.

    Idempotent — safe to call on every application startup.
    Uses upsert (INSERT ... ON CONFLICT DO UPDATE) so re-runs are
    a no-op when the data has not changed.
    """
```

## Minimum fields for `IntegrationType`

| Field | Notes |
|---|---|
| `id` | Stable UUID — hardcode so re-seeding hits the same row |
| `name` | Display name, e.g. `"Opera Cloud"` |
| `slug` | Lowercase identifier used in code, e.g. `"opera_cloud"` |
| `description` | One-line description shown in the UI |
| `category` | e.g. `"pms"`, `"crm"`, `"payment"` |
| `auth_type` | e.g. `"oauth2"`, `"api_key"`, `"basic_auth"`, `"basic_or_jwt"` |
| `base_url` | Default API base URL (can be overridden per account) |
| `endpoints` | JSON array of available endpoint definitions |
| `config_schema` | JSON Schema for account-level configuration fields |
| `is_active` | Set to `True` |

## Upsert pattern

```python
from sqlalchemy.dialects.postgresql import insert as pg_insert

stmt = pg_insert(IntegrationType).values(**payload)
stmt = stmt.on_conflict_do_update(
    index_elements=["id"],
    set_={k: v for k, v in payload.items() if k != "id"},
)
db.execute(stmt)
db.commit()
```

## Registration

After creating the seed file, add it to `seeds/__init__.py`:

```python
try:
    from botelier.seeds.<name>_integration import seed_<name>_integration
    seeds.append(("<name>", seed_<name>_integration))
except ImportError as exc:
    logger.warning(f"Could not import <name> seed: {exc}")
```
