"""Adapter resolution: integration-type slug → auth_type → DefaultAdapter.

Resolution keys on the slug first (so a provider can pin a dedicated adapter
regardless of its auth_type), then falls back to auth_type (the historical
behavior — every vendor branch used to key on auth_type), and finally to the
generic :class:`DefaultAdapter` for any config-only integration.

Adapters are stateless, so a single shared instance per adapter is reused.
"""

from typing import Optional

from .base import BaseIntegrationAdapter, DefaultAdapter
from .guestcentric import GuestCentricAdapter
from .opera_cloud import OperaCloudAdapter

OPERA_ADAPTER = OperaCloudAdapter()
GUESTCENTRIC_ADAPTER = GuestCentricAdapter()
DEFAULT_ADAPTER = DefaultAdapter()

_SLUG_REGISTRY: dict[str, BaseIntegrationAdapter] = {
    OPERA_ADAPTER.slug: OPERA_ADAPTER,
    GUESTCENTRIC_ADAPTER.slug: GUESTCENTRIC_ADAPTER,
}

_AUTH_TYPE_REGISTRY: dict[str, BaseIntegrationAdapter] = {
    "oauth2_client_credentials": OPERA_ADAPTER,
    "basic_or_jwt": GUESTCENTRIC_ADAPTER,
}


def resolve_adapter(
    slug: Optional[str] = None, auth_type: Optional[str] = None
) -> BaseIntegrationAdapter:
    if slug and slug in _SLUG_REGISTRY:
        return _SLUG_REGISTRY[slug]
    if auth_type and auth_type in _AUTH_TYPE_REGISTRY:
        return _AUTH_TYPE_REGISTRY[auth_type]
    return DEFAULT_ADAPTER
