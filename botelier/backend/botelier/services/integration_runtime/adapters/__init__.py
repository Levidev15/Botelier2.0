"""Per-vendor integration adapters + resolution registry."""

from .base import BaseIntegrationAdapter, DefaultAdapter, RefreshContext
from .guestcentric import GuestCentricAdapter
from .oauth2 import OAuth2AuthorizationCodeAdapter, resolve_token_endpoint
from .opera_cloud import (
    _ORACLE_ALLOWED_SUFFIXES,
    OperaCloudAdapter,
    _validate_opera_gateway_url,
)
from .registry import (
    DEFAULT_ADAPTER,
    GUESTCENTRIC_ADAPTER,
    OAUTH2_AUTHCODE_ADAPTER,
    OPERA_ADAPTER,
    resolve_adapter,
)

__all__ = [
    "BaseIntegrationAdapter",
    "DefaultAdapter",
    "RefreshContext",
    "OperaCloudAdapter",
    "GuestCentricAdapter",
    "OAuth2AuthorizationCodeAdapter",
    "resolve_token_endpoint",
    "resolve_adapter",
    "OPERA_ADAPTER",
    "GUESTCENTRIC_ADAPTER",
    "OAUTH2_AUTHCODE_ADAPTER",
    "DEFAULT_ADAPTER",
    "_validate_opera_gateway_url",
    "_ORACLE_ALLOWED_SUFFIXES",
]
