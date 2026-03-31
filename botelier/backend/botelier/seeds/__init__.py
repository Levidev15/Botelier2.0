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

from sqlalchemy.orm import Session


def seed_all_integrations(db: Session) -> None:
    """
    Run every integration seed in sequence.

    Idempotent — safe to call on every application startup.  Each seed is
    wrapped individually so a failure in one does not block the others.
    """
    from loguru import logger

    seeds = []

    try:
        from botelier.seeds.opera_integration import seed_opera_integration
        seeds.append(("opera", seed_opera_integration))
    except ImportError as exc:
        logger.warning(f"Could not import opera seed: {exc}")

    try:
        from botelier.seeds.guestcentric_integration import seed_guestcentric_integration
        seeds.append(("guestcentric", seed_guestcentric_integration))
    except ImportError as exc:
        logger.warning(f"Could not import guestcentric seed: {exc}")

    for name, fn in seeds:
        try:
            fn(db)
            logger.debug(f"Seed '{name}' completed")
        except Exception as exc:
            logger.error(f"Seed '{name}' failed (non-fatal): {exc}")
