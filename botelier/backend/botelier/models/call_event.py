"""
CallEvent Model - Timeline of events during a call.

Records meaningful state transitions throughout every call for
root-cause diagnosis. Events are written in two ways:
  - Twilio webhook events: written directly (await) in HTTP handlers
  - Pipecat pipeline events: queued via CallEventQueue (non-blocking)
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Integer, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from botelier.database import Base


class CallEvent(Base):
    """
    Records a single event in the timeline of a call.

    Columns:
        id           UUID primary key
        call_log_id  FK → call_logs.id
        event_type   e.g. call_initiated, websocket_connected, greeting_started
        event_source twilio | pipecat | app
        severity     info | warning | error
        occurred_at  UTC timestamp of the event
        offset_ms    milliseconds since call started (for display: +0:04)
        details      JSONB payload with extra context (e.g. CallStatus, duration)
    """
    __tablename__ = "call_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    call_log_id = Column(
        UUID(as_uuid=True),
        ForeignKey("call_logs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    event_type = Column(String, nullable=False)
    event_source = Column(String, nullable=False, default="app")
    severity = Column(String, nullable=False, default="info")

    occurred_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    offset_ms = Column(Integer, nullable=True)

    details = Column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_call_events_call_log_occurred", "call_log_id", "occurred_at"),
    )

    def __repr__(self):
        return f"<CallEvent {self.event_type} @ {self.occurred_at}>"

    def to_dict(self):
        return {
            "id": str(self.id),
            "call_log_id": str(self.call_log_id),
            "event_type": self.event_type,
            "event_source": self.event_source,
            "severity": self.severity,
            "occurred_at": self.occurred_at.isoformat() + "Z" if self.occurred_at else None,
            "offset_ms": self.offset_ms,
            "details": self.details,
        }
