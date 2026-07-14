"""Payment processor provider interface (Task #330).

The processor is abstracted behind ``PaymentProvider`` so ``PaymentService`` never
imports a specific SDK. Two contracts matter:

- ``create_checkout`` — mint a hosted-checkout session the caller can pay on.
  It receives the ``idempotency_key`` so a retried call is deduped *by the
  processor too* (the durable ledger only prevents our side from re-firing; true
  exactly-once needs the processor to honour the same key).
- ``verify_webhook`` / ``parse_event`` — a completion callback is only trusted
  after its signature verifies. A forged completion would be a free booking, so
  verification MUST fail closed.

v1 ships ``StubPaymentProvider``: no processor is connected, so it is *not
configured* and refuses to create checkouts or trust webhooks. ``collect_payment``
therefore fails closed to an explicit "payment unavailable" until Stripe (or
another provider) is wired in — it never fakes a success.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class PaymentProviderError(Exception):
    """A processor call failed in a way the caller should surface as failed."""


class PaymentProviderUnavailable(PaymentProviderError):
    """No usable processor is configured for this (account, property)."""


@dataclass
class ProviderCheckout:
    """Result of minting a hosted-checkout session."""

    checkout_url: str
    provider_ref: str
    expires_at: Optional[datetime] = None
    raw: dict = field(default_factory=dict)


@dataclass
class ProviderEvent:
    """A verified processor webhook event, normalized."""

    provider_ref: str
    status: str  # one of PaymentStatus.* (captured / failed / expired / ...)
    raw: dict = field(default_factory=dict)


class PaymentProvider:
    """Abstract processor. Implementations must fail closed on every path."""

    name: str = "abstract"

    def is_configured(self) -> bool:
        raise NotImplementedError

    def create_checkout(
        self,
        *,
        amount: float,
        currency: str,
        description: Optional[str],
        reference: Optional[str],
        idempotency_key: str,
        return_url: str,
    ) -> ProviderCheckout:
        raise NotImplementedError

    def verify_webhook(self, *, payload: bytes, signature: Optional[str]) -> bool:
        raise NotImplementedError

    def parse_event(self, payload: bytes) -> ProviderEvent:
        raise NotImplementedError


class StubPaymentProvider(PaymentProvider):
    """The v1 default: no processor connected → everything fails closed.

    This is intentionally NOT a fake-success provider. Until a real processor is
    connected (Stripe, Task #330 follow-up), ``collect_payment`` reports the
    capability as unavailable rather than pretending a link was issued.
    """

    name = "stub"

    def is_configured(self) -> bool:
        return False

    def create_checkout(self, **_kwargs) -> ProviderCheckout:
        raise PaymentProviderUnavailable(
            "No payment processor is connected for this property."
        )

    def verify_webhook(self, *, payload: bytes, signature: Optional[str]) -> bool:
        # Fail closed: with no configured secret we cannot authenticate a
        # completion, so we must reject it. Trusting it would be a free booking.
        return False

    def parse_event(self, payload: bytes) -> ProviderEvent:
        raise PaymentProviderUnavailable("No payment processor is connected.")


def get_payment_provider(
    db: Session, account_id: Optional[str], property_id: Optional[str]
) -> PaymentProvider:
    """Return the processor bound to ``(account_id, property_id)``.

    v1: always the fail-closed stub — no processor is connected yet. When a
    provider (e.g. Stripe) is added, detect its property-scoped connection here
    and return a configured adapter; the rest of ``PaymentService`` is unchanged.
    """
    return StubPaymentProvider()
