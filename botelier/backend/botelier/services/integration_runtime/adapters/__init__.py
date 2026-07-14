"""Per-vendor integration adapters + resolution registry."""

from .base import BaseIntegrationAdapter, DefaultAdapter, RefreshContext
from .guestcentric import GuestCentricAdapter
from .opera_cloud import (
    _ORACLE_ALLOWED_SUFFIXES,
    OperaCloudAdapter,
    _validate_opera_gateway_url,
)
from .registry import (
    DEFAULT_ADAPTER,
    GUESTCENTRIC_ADAPTER,
    OPERA_ADAPTER,
    resolve_adapter,
)

__all__ = [
    "BaseIntegrationAdapter",
    "DefaultAdapter",
    "RefreshContext",
    "OperaCloudAdapter",
    "GuestCentricAdapter",
    "resolve_adapter",
    "OPERA_ADAPTER",
    "GUESTCENTRIC_ADAPTER",
    "DEFAULT_ADAPTER",
    "_validate_opera_gateway_url",
    "_ORACLE_ALLOWED_SUFFIXES",
]
