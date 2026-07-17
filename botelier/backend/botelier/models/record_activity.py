"""RecordActivity Model - Per-record audit trail entries.

Multi-tenant isolation: activity entries are ACCOUNT-scoped. Every query MUST
filter by account_id to prevent cross-tenant data access.

One row is written for each dashboard action on a record: created, updated
(field edits and/or status change), and deleted. ``record_id`` is intentionally
NOT a foreign key so the "deleted" entry survives the record's deletion and the
audit trail remains intact.

The initial "created" entry for records captured by voice/SMS (which pre-date
this table or are written outside the dashboard API) is synthesized at read
time from the record's own metadata (created_at, source_channel, capture
method, assistant) rather than backfilled.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from botelier.database import Base


class RecordActivityAction:
    """Action constants for record activity entries."""

    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"


class RecordActivity(Base):
    """A single audit-trail entry for a record.

    SECURITY: Always filter by account_id to prevent cross-tenant access.
    """

    __tablename__ = "record_activity"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Deliberately no FK: the "deleted" entry must outlive the record row.
    record_id = Column(UUID(as_uuid=True), nullable=False)

    actor_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    action = Column(String(32), nullable=False)

    old_status = Column(String(60), nullable=True)
    new_status = Column(String(60), nullable=True)

    # List of record-data field keys whose values changed in this action.
    changed_fields = Column(JSONB, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    actor = relationship("User", foreign_keys=[actor_user_id])

    __table_args__ = (
        Index("ix_record_activity_record_created", "record_id", "created_at"),
        Index("ix_record_activity_account_created", "account_id", "created_at"),
    )

    def __repr__(self):
        return f"<RecordActivity {self.action} record={self.record_id}>"

    def to_dict(self):
        return {
            "id": str(self.id),
            "record_id": str(self.record_id),
            "action": self.action,
            "actor_user_id": str(self.actor_user_id) if self.actor_user_id else None,
            "actor_name": self.actor.display_name if self.actor else None,
            "old_status": self.old_status,
            "new_status": self.new_status,
            "changed_fields": self.changed_fields or [],
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
        }
