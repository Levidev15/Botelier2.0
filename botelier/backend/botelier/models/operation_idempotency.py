"""OperationIdempotency Model - Cross-session write dedup ledger (Task #330).

The in-memory non-GET guard in ``FlowExecutor`` only protects against duplicate
writes *within a single worker/session*. When a voice websocket drops and the
caller reconnects on a fresh worker, that in-memory state is gone — a retried
booking or charge would fire a second time.

This table is the durable backstop: every mutating operation claims a row keyed
by a caller-stable ``idempotency_key`` BEFORE it runs (``INSERT ... ON CONFLICT
DO NOTHING``). A second attempt with the same key finds the row and either
returns the stored result (already succeeded), refuses (another worker is
mid-flight under a fresh lease), or takes over (the previous holder's lease went
stale). See ``botelier.services.idempotency.IdempotencyLedger``.

Multi-tenant isolation: rows are account-scoped and carry the Task #327
``property_id`` for observability; the uniqueness/dedup guarantee is on the
``idempotency_key`` itself, which already encodes the scope that produced it.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID


from botelier.database import Base


class OperationStatus(str):
    """Plain string status namespace (VARCHAR column, not a native PG enum)."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class OperationIdempotency(Base):
    """A durable dedup record for one logical mutating operation.

    SECURITY: the dedup key is authoritative — never widen a query to match on
    ``account_id`` alone. The key already binds the operation to its tenant,
    property, contact, and arguments.
    """

    __tablename__ = "operation_idempotency"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    idempotency_key = Column(String(128), nullable=False, unique=True, index=True)

    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Human-readable label of what ran (capability name / "flow_node:<id>").
    operation = Column(String(128), nullable=True)

    # Hash of the canonical arguments — observability only; the dedup key is the
    # source of truth for equality.
    args_hash = Column(String(64), nullable=True)

    status = Column(String(16), nullable=False, default=OperationStatus.PENDING)

    # Serialized ActionExecutionResult for the succeeded case (server-only).
    result = Column(JSONB, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    # Retention hint for a future sweeper; not enforced at read time (staleness
    # is judged from updated_at + the execution lease).
    expires_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_operation_idempotency_status_updated", "status", "updated_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<OperationIdempotency key={self.idempotency_key} "
            f"status={self.status} op={self.operation}>"
        )
