"""RecordType Model - Account-defined structured output tables.

Multi-tenant isolation: RecordTypes are ACCOUNT-scoped. Every query MUST
filter by account_id to prevent cross-tenant data access.

A RecordType is the schema/definition of a structured "output table" for an
account (e.g. "Bookings", "Housekeeping Requests", "Appointments"). Each type
declares its own custom columns (``fields``) and lifecycle ``status_options``.

Records (see record.py) are individual rows captured against a RecordType,
either by automatic LLM extraction from a voice/SMS conversation or by an
explicit SAVE_RECORD flow node.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from botelier.database import Base


class RecordType(Base):
    """Account-scoped definition of a structured output table.

    SECURITY: Always filter by account_id to prevent cross-tenant access.

    ``fields`` is a JSONB array of column definitions. Each field is a dict:
        {
          "key": "guest_name",        # stable machine key used in Record.data
          "label": "Guest Name",      # human label for the UI
          "type": "text",             # text|number|date|datetime|boolean|select|phone|email
          "required": false,
          "options": ["A", "B"]       # only for type == "select"
        }

    ``status_options`` is a JSONB array of lifecycle states:
        {"value": "open", "label": "Open", "color": "#f59e0b"}

    ``assistant_ids`` limits which assistants trigger auto extraction for this
    type. ``null`` (or empty) means ALL assistants in the account.
    """

    __tablename__ = "record_types"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name = Column(String(120), nullable=False)
    slug = Column(String(120), nullable=False)
    description = Column(Text, nullable=True)

    icon = Column(String(40), nullable=True)
    color = Column(String(20), nullable=True, default="#6366f1")

    fields = Column(JSONB, nullable=False, server_default="[]")
    status_options = Column(JSONB, nullable=False, server_default="[]")

    # Opt-in gate: only types with auto_extract=true are considered by the
    # post-conversation LLM extraction service.
    auto_extract = Column(Boolean, nullable=False, default=False, server_default="false")
    extraction_instructions = Column(Text, nullable=True)

    # null / empty = all assistants; otherwise only listed assistant UUIDs
    # (stored as strings) trigger auto extraction for this type.
    assistant_ids = Column(JSONB, nullable=True)

    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    display_order = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("uq_record_types_account_slug", "account_id", "slug", unique=True),
        Index("ix_record_types_account_active", "account_id", "is_active"),
    )

    def __repr__(self):
        return f"<RecordType {self.name} ({self.slug})>"

    def to_dict(self, include_counts: bool = False, record_count: int = 0):
        result = {
            "id": str(self.id),
            "account_id": str(self.account_id),
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "icon": self.icon,
            "color": self.color,
            "fields": self.fields or [],
            "status_options": self.status_options or [],
            "auto_extract": bool(self.auto_extract),
            "extraction_instructions": self.extraction_instructions,
            "assistant_ids": self.assistant_ids,
            "is_active": bool(self.is_active),
            "display_order": self.display_order,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "updated_at": self.updated_at.isoformat() + "Z" if self.updated_at else None,
        }
        if include_counts:
            result["record_count"] = record_count
        return result
