"""Property Model - Represents a distinct property/location under an Account.

A single account (e.g. a hotel management company) may operate multiple
properties (Hotel A, Hotel B). Callers/texters reach a specific property via the
dialed number / assistant, and every integration resolution is scoped to
(account_id, property_id) so one property can never receive another property's
data. See Task #327 (Per-Property Data Isolation).

Scoping semantics (enforced server-side in the integration-resolution layer):
- ``property_id`` on phone_numbers / assistants / account_integrations is
  nullable. A NULL ``property_id`` means "account-global / shared" — usable by
  any property under the account (e.g. one central reservation system).
- A session whose property resolves to NULL (a number/assistant not assigned to
  a property) preserves legacy account-only scoping.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from botelier.database import Base


class Property(Base):
    """A property/location operated by an Account.

    Resources (phone numbers, assistants, integration connections) may be bound
    to a property to isolate one property's data from another within the same
    account. Backfill assigns each existing account a single default property so
    current single-property behavior is preserved.
    """

    __tablename__ = "properties"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    address = Column(Text, nullable=True)
    timezone = Column(String(50), nullable=True)

    # Marks the account's default property (created by the backfill for existing
    # accounts). Exactly one default per account is expected but not DB-enforced.
    is_default = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Property {self.name} account={self.account_id}>"

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "account_id": str(self.account_id),
            "name": self.name,
            "description": self.description,
            "address": self.address,
            "timezone": self.timezone,
            "is_default": self.is_default,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "updated_at": self.updated_at.isoformat() + "Z" if self.updated_at else None,
        }
