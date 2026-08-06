"""Adapter resolution: integration-type slug → auth_type → DefaultAdapter.

Resolution keys on the slug first (so a provider can pin a dedicated adapter
regardless of its auth_type), then falls back to auth_type.  The generic
:class:`DefaultAdapter` is deliberately limited to explicit no-auth/config-only
types; unknown auth schemes must fail closed before an outbound request.

Adapters are stateless, so a single shared instance per adapter is reused.
"""

from typing import Optional

from .base import BaseIntegrationAdapter, DefaultAdapter
from .guestcentric import GuestCentricAdapter
from .oauth2 import OAuth2AuthorizationCodeAdapter
from .opera_cloud import OperaCloudAdapter


class UnsupportedAuthTypeError(ValueError):
    """Raised when an integration declares an auth scheme no adapter supports."""


OPERA_ADAPTER = OperaCloudAdapter()
GUESTCENTRIC_ADAPTER = GuestCentricAdapter()
OAUTH2_AUTHCODE_ADAPTER = OAuth2AuthorizationCodeAdapter()
DEFAULT_ADAPTER = DefaultAdapter()

_SLUG_REGISTRY: dict[str, BaseIntegrationAdapter] = {
    OPERA_ADAPTER.slug: OPERA_ADAPTER,
    GUESTCENTRIC_ADAPTER.slug: GUESTCENTRIC_ADAPTER,
}

_AUTH_TYPE_REGISTRY: dict[str, BaseIntegrationAdapter] = {
    "oauth2_client_credentials": OPERA_ADAPTER,
    "basic_or_jwt": GUESTCENTRIC_ADAPTER,
    "oauth2_authorization_code": OAUTH2_AUTHCODE_ADAPTER,
}
_GENERIC_AUTH_TYPES = {"none", "default", ""}


def resolve_adapter(
    slug: Optional[str] = None, auth_type: Optional[str] = None
) -> BaseIntegrationAdapter:
    if slug and slug in _SLUG_REGISTRY:
        return _SLUG_REGISTRY[slug]
    normalized_auth_type = (auth_type or "").strip().lower()
    if normalized_auth_type in _AUTH_TYPE_REGISTRY:
        return _AUTH_TYPE_REGISTRY[normalized_auth_type]
    if normalized_auth_type in _GENERIC_AUTH_TYPES:
        return DEFAULT_ADAPTER
    raise UnsupportedAuthTypeError(
        f"Authentication type '{auth_type}' is not supported by the integration runtime"
    )
