"""FlowSession Model - Durable per-contact flow execution state (Task #330).

Voice flows run inside a Pipecat media-stream worker whose state
(``current_node_id`` + ``collected_slots``) lives only in memory on that
worker (see ``FlowExecutor``/``FunctionMapper._flow_executors``). If the
websocket drops and the caller reconnects, a fresh worker/executor is created
and every collected slot is lost — the caller has to start over, and any
half-finished booking/payment is orphaned.

A ``FlowSession`` row is a durable snapshot of that in-memory state, written
after every node advance / slot write in an isolated transaction (decoupled
from the business write path, last-write-wins, no locks). On reconnect the new
executor rehydrates from this row by ``(session_key, tool_id)`` and resumes at
the same node with the same slots.

Multi-tenant isolation: FlowSessions are ACCOUNT-scoped and carry the Task #327
``property_id`` so a resumed session keeps its per-property scope. ``session_key``
is the channel's stable contact identifier (``call_sid`` for voice).
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from botelier.database import Base


class FlowSessionStatus(str):
    """String status values (kept as a plain namespace, not a PG enum).

    Additive-only migrations avoid native enums; a VARCHAR keeps new statuses
    from requiring an ``ALTER TYPE`` on every provisioned database.
    """

    ACTIVE = "active"
    COMPLETE = "complete"
    ABANDONED = "abandoned"


class FlowSession(Base):
    """Durable snapshot of a single flow execution's state.

    SECURITY: Always filter by account_id to prevent cross-tenant access. The
    unique key ``(session_key, tool_id)`` guarantees one live snapshot per
    (contact, flow) so reconnects upsert rather than duplicate.
    """

    __tablename__ = "flow_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Per-property isolation (Task #327). Carried through resume so a rehydrated
    # session keeps its (account_id, property_id) scope. NULL = account-global.
    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    channel = Column(String(16), nullable=False, default="voice")

    # Stable per-contact identifier for this channel (call_sid for voice).
    session_key = Column(String(255), nullable=False, index=True)

    # The flow tool this snapshot belongs to. A single contact may run more than
    # one flow tool, so the snapshot is keyed per (session_key, tool_id).
    tool_id = Column(UUID(as_uuid=True), nullable=False)

    flow_version_id = Column(UUID(as_uuid=True), nullable=True)

    current_node_id = Column(String(255), nullable=True)

    collected_slots = Column(JSONB, nullable=False, server_default="{}")

    status = Column(String(32), nullable=False, default=FlowSessionStatus.ACTIVE)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        UniqueConstraint("session_key", "tool_id", name="uq_flow_sessions_key_tool"),
        Index("ix_flow_sessions_account_session", "account_id", "session_key"),
    )

    def __repr__(self) -> str:
        return (
            f"<FlowSession session_key={self.session_key} tool_id={self.tool_id} "
            f"node={self.current_node_id} status={self.status}>"
        )
