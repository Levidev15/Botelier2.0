"""
Feature Catalog and Entitlement System.

Defines every feature available on the platform, which subscription tiers include
it by default, and provides a resolver that merges tier defaults with per-account
overrides to produce the effective feature map for an account.

Usage
-----
    from botelier.auth.features import FEATURE_CATALOG, get_account_features

    effective = get_account_features(
        subscription_tier=account.subscription_tier.value,
        feature_flags_override=account.feature_flags or {},
    )
    # -> {"call_recording": True, "qa_scoring": False, ...}

Adding a new feature
--------------------
1. Add an entry to FEATURE_CATALOG with name, description, and tier_defaults.
2. That's it — no migration or model change needed.  The resolver derives the
   effective state from the catalog + per-account override at request time.
"""

from typing import Dict, Any


# ---------------------------------------------------------------------------
# FEATURE_CATALOG
#
# Each key is the feature slug used everywhere (API, DB override, frontend).
# Each value is a dict with:
#   name          — human-readable display name
#   description   — one-line description for admin UI
#   tier_defaults — which tiers include this feature by default
#                   Valid tier keys: free, starter, professional, enterprise
# ---------------------------------------------------------------------------
FEATURE_CATALOG: Dict[str, Dict[str, Any]] = {
    "call_recording": {
        "name": "Call Recording",
        "description": "Record inbound calls and access recordings from the call log.",
        "tier_defaults": {
            "free": False,
            "starter": False,
            "professional": True,
            "enterprise": True,
        },
    },
    "qa_scoring": {
        "name": "QA Scoring",
        "description": "Automated after-call quality scoring and agent evaluation.",
        "tier_defaults": {
            "free": False,
            "starter": False,
            "professional": True,
            "enterprise": True,
        },
    },
}


def get_account_features(
    subscription_tier: str,
    feature_flags_override: Dict[str, Any],
) -> Dict[str, bool]:
    """
    Resolve the effective feature set for an account.

    Resolution order (last writer wins):
    1. FEATURE_CATALOG tier defaults for the account's subscription tier.
    2. Per-account overrides from the ``feature_flags`` JSONB column.

    Features not present in the override dict fall back to the tier default.
    Unknown features in the override dict are ignored (not forwarded to callers).

    Args:
        subscription_tier: The account's subscription tier string
                           (e.g. ``"professional"``).  Unknown tier values
                           default to False for all features.
        feature_flags_override: The account's raw ``feature_flags`` dict
                                (may be empty or None).

    Returns:
        Dict mapping every known feature slug to its effective bool state.
    """
    overrides = feature_flags_override or {}
    result: Dict[str, bool] = {}
    for slug, meta in FEATURE_CATALOG.items():
        tier_default = bool(meta["tier_defaults"].get(subscription_tier, False))
        if slug in overrides:
            result[slug] = bool(overrides[slug])
        else:
            result[slug] = tier_default
    return result
