"""Record Model - Individual structured output rows.

Multi-tenant isolation: Records are ACCOUNT-scoped. Every query MUST filter by
account_id to prevent cross-tenant data access.

A Record is a single captured row for a RecordType (e.g. one booking). It is
produced either by:
  - automatic LLM extraction from a completed voice/SMS conversation
    (``capture_method='auto_extract'``), or
  - an explicit SAVE_RECORD flow node during a voice call
    (``capture_method='flow_node'``), or
  - manual entry in the dashboard (``capture_method='manual'``).

``data`` is a JSONB object keyed by the RecordType field keys. Records are
rendered tolerantly against the RecordType's current fields, so adding or
removing fields later never corrupts existing rows.
"""

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from botelier.database import Base


class SourceChannel(str, Enum):
    VOICE = "voice"
    SMS = "sms"
    MANUAL = "manual"


class CaptureMethod(str, Enum):
    AUTO_EXTRACT = "auto_extract"
    FLOW_NODE = "flow_node"
    MANUAL = "manual"


class Record(Base):
    """A single structured output row captured against a RecordType.

    SECURITY: Always filter by account_id to prevent cross-tenant access.
    """

    __tablename__ = "records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    record_type_id = Column(
        UUID(as_uuid=True),
        ForeignKey("record_types.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status = Column(String(60), nullable=True)

    data = Column(JSONB, nullable=False, server_default="{}")

    source_channel = Column(String(10), nullable=False, default=SourceChannel.MANUAL.value)
    capture_method = Column(String(20), nullable=False, default=CaptureMethod.MANUAL.value)

    source_call_log_id = Column(
        UUID(as_uuid=True),
        ForeignKey("call_logs.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("sms_conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    assistant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("assistants.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    record_type = relationship("RecordType", foreign_keys=[record_type_id])

    __table_args__ = (
        Index("ix_records_account_type_created", "account_id", "record_type_id", "created_at"),
        Index("ix_records_account_created", "account_id", "created_at"),
        Index("ix_records_source_call_log", "source_call_log_id"),
        Index("ix_records_source_conversation", "source_conversation_id"),
    )

    def __repr__(self):
        return f"<Record {self.id} type={self.record_type_id} status={self.status}>"

    def to_dict(self, include_type: bool = False):
        result = {
            "id": str(self.id),
            "account_id": str(self.account_id),
            "record_type_id": str(self.record_type_id),
            "status": self.status,
            "data": self.data or {},
            "source_channel": self.source_channel,
            "capture_method": self.capture_method,
            "source_call_log_id": str(self.source_call_log_id)
            if self.source_call_log_id
            else None,
            "source_conversation_id": str(self.source_conversation_id)
            if self.source_conversation_id
            else None,
            "assistant_id": str(self.assistant_id) if self.assistant_id else None,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "updated_at": self.updated_at.isoformat() + "Z" if self.updated_at else None,
        }
        if include_type and self.record_type is not None:
            result["record_type_name"] = self.record_type.name
            result["record_type_slug"] = self.record_type.slug
            result["record_type_color"] = self.record_type.color
        return result
