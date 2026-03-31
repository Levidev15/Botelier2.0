"""
Botelier integration seed functions.

Contract
--------
Every integration seed module MUST expose a function with the signature::

    def seed_<name>_integration(db: Session) -> None:
        ...

The function MUST be idempotent: safe to call on every application startup.
Use ``INSERT ... ON CONFLICT DO UPDATE`` (upsert) rather than plain inserts.

Adding a new integration
------------------------
1. Copy ``seeds/TEMPLATE.md`` for the shape of a seed module.
2. Create ``seeds/<name>_integration.py`` and implement the seed function.
3. Import and call the function from ``seed_all_integrations`` below.
4. Register the call in ``main.py`` startup (or rely on ``seed_all_integrations``).

``seed_all_integrations`` is the canonical entry point — call it from startup
instead of importing individual seed functions directly.
"""

from typing import List, Optional
from sqlalchemy.orm import Session


_REQUIRED_TOP_LEVEL = {"name", "slug", "auth_type", "provider"}
_REQUIRED_ENDPOINT_KEYS = {"id", "name", "path", "method"}


def verify_seed(slug: str, db: Session) -> Optional[List[str]]:
    """
    Validate that a seeded IntegrationType row in the DB is structurally sound.

    Checks for:
    - Row exists with the given slug
    - Required top-level fields are non-empty (name, slug, auth_type, provider)
    - ``endpoints_config`` is a non-empty JSON list where each entry has the required keys
    - ``required_fields`` entries (JSON list) each have ``key`` and ``label``

    Returns a list of error strings if any issues are found, or ``None`` if
    the seed passes validation.  Designed to be called during startup after
    ``seed_all_integrations`` so misconfigured connectors are surfaced in logs
    immediately rather than at call-time.
    """
    import json as _json
    from loguru import logger as _logger
    from botelier.models.integration import IntegrationType

    row = db.query(IntegrationType).filter(IntegrationType.slug == slug).first()
    if row is None:
        return [f"No IntegrationType row found for slug '{slug}'"]

    errors: List[str] = []

    for field in _REQUIRED_TOP_LEVEL:
        val = getattr(row, field, None)
        if not val:
            errors.append(f"Field '{field}' is empty or missing")

    raw_endpoints = getattr(row, "endpoints_config", None)
    if isinstance(raw_endpoints, str):
        try:
            endpoints = _json.loads(raw_endpoints)
        except Exception:
            endpoints = []
            errors.append("'endpoints_config' is not valid JSON")
    else:
        endpoints = raw_endpoints or []

    if not isinstance(endpoints, list) or len(endpoints) == 0:
        errors.append("'endpoints_config' must be a non-empty list")
    else:
        for i, ep in enumerate(endpoints):
            if not isinstance(ep, dict):
                errors.append(f"endpoints_config[{i}] is not a dict")
                continue
            for k in _REQUIRED_ENDPOINT_KEYS:
                if not ep.get(k):
                    errors.append(f"endpoints_config[{i}] missing required key '{k}'")

    raw_rf = getattr(row, "required_fields", None)
    if isinstance(raw_rf, str):
        try:
            required_fields = _json.loads(raw_rf)
        except Exception:
            required_fields = []
    else:
        required_fields = raw_rf or []

    if isinstance(required_fields, list):
        for i, rf in enumerate(required_fields):
            if not isinstance(rf, dict):
                errors.append(f"required_fields[{i}] is not a dict")
                continue
            for k in ("key", "label"):
                if not rf.get(k):
                    errors.append(f"required_fields[{i}] missing '{k}'")

    if errors:
        _logger.warning(f"Seed validation failed for slug '{slug}': {errors}")
    else:
        _logger.debug(f"Seed validation passed for slug '{slug}'")

    return errors if errors else None


def seed_all_integrations(db: Session) -> None:
    """
    Run every integration seed in sequence, then validate each.

    Idempotent — safe to call on every application startup.  Each seed is
    wrapped individually so a failure in one does not block the others.
    Validation warnings are logged but never raise exceptions.
    """
    from loguru import logger

    # Each entry: (display_name, db_slug, seed_function)
    seeds = []

    try:
        from botelier.seeds.opera_integration import seed_opera_integration
        seeds.append(("opera", "opera-cloud", seed_opera_integration))
    except ImportError as exc:
        logger.warning(f"Could not import opera seed: {exc}")

    try:
        from botelier.seeds.guestcentric_integration import seed_guestcentric_integration
        seeds.append(("guestcentric", "guestcentric-crs", seed_guestcentric_integration))
    except ImportError as exc:
        logger.warning(f"Could not import guestcentric seed: {exc}")

    for name, slug, fn in seeds:
        try:
            fn(db)
            logger.debug(f"Seed '{name}' completed")
        except Exception as exc:
            logger.error(f"Seed '{name}' failed (non-fatal): {exc}")

    for name, slug, _ in seeds:
        try:
            verify_seed(slug, db)
        except Exception as exc:
            logger.warning(f"Seed validation for '{name}' (slug='{slug}') raised an exception (non-fatal): {exc}")
