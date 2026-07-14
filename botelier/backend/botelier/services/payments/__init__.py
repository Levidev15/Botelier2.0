"""Payments service (Task #330).

Vendor-neutral payment collection behind the ``collect_payment`` capability. The
processor lives behind a fail-closed provider interface (``providers.py``) so the
capability can ship before any real processor (Stripe) is connected — it simply
reports "unavailable" until one is configured, never a fake success.
"""

from botelier.services.payments.providers import (
    PaymentProviderError,
    PaymentProviderUnavailable,
    ProviderCheckout,
    ProviderEvent,
    get_payment_provider,
)
from botelier.services.payments.service import PaymentService

__all__ = [
    "PaymentService",
    "PaymentProviderError",
    "PaymentProviderUnavailable",
    "ProviderCheckout",
    "ProviderEvent",
    "get_payment_provider",
]
