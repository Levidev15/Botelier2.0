"""Cross-worker resilience state for the integration runtime (Task #331).

The integration core must be resilient under load and against failing vendors,
and that state MUST be shared across every stateless replica — a per-process
token bucket or in-memory breaker would let each worker independently hammer a
throttling or down provider. So both live in Postgres, keyed by
``integration_id`` (which already encodes account + provider + property/
connection), and are mutated under ``SELECT ... FOR UPDATE`` so concurrent
workers serialize on the single row.

Design notes:
  • NO foreign keys. These are ephemeral operational counters, not business
    records — an orphan row after an integration is deleted is harmless and can
    be swept later. Avoiding FKs also keeps the row writable for integrations
    that are never persisted (e.g. parity/unit tests inject a detached
    ``AccountIntegration``), so the resilience path stays exercisable in tests.
  • ``account_id`` is stored for observability/scoping only (also no FK).
  • These tables carry no secrets.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from botelier.database import Base


class CircuitState(str):
    """Plain string state namespace (VARCHAR column, not a native PG enum)."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class IntegrationRateLimit(Base):
    """Token-bucket state for one integration's outbound provider requests.

    ``tokens`` is a float so partial refills accrue between requests; it is
    refilled lazily on each acquire from ``updated_at`` elapsed * refill rate,
    capped at the configured capacity.
    """

    __tablename__ = "integration_rate_limits"

    integration_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    tokens = Column(Float, nullable=False, default=0.0)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return (
            f"<IntegrationRateLimit integration={self.integration_id} "
            f"tokens={self.tokens:.2f}>"
        )


class IntegrationCircuitBreaker(Base):
    """Circuit-breaker state machine for one integration/provider connection.

    States: ``closed`` (healthy, requests flow), ``open`` (provider is failing —
    requests short-circuit until the cooldown elapses), ``half_open`` (a single
    probe request is allowed to test recovery).
    """

    __tablename__ = "integration_circuit_breakers"

    integration_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    state = Column(String(16), nullable=False, default=CircuitState.CLOSED)
    failure_count = Column(Integer, nullable=False, default=0)
    opened_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return (
            f"<IntegrationCircuitBreaker integration={self.integration_id} "
            f"state={self.state} failures={self.failure_count}>"
        )
