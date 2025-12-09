"""
Account Invitation Model - Manages invitations to join accounts.

Platform Admins can invite users to accounts. Users receive an email
and must accept the invitation to join with the assigned role.
"""

import uuid
import secrets
from datetime import datetime, timedelta
from sqlalchemy import Column, String, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from botelier.database import Base


class InvitationStatus(str, enum.Enum):
    """Status of an invitation."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    REVOKED = "revoked"


class AccountInvitation(Base):
    """
    Invitation to join an account.
    
    Platform Admins create invitations for users to join accounts.
    Each invitation has a unique token and expiration date.
    """
    __tablename__ = "account_invitations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    invitee_email = Column(String, nullable=False, index=True)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False)
    invited_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    token = Column(String, unique=True, nullable=False, index=True)
    
    status = Column(SQLEnum(InvitationStatus), default=InvitationStatus.PENDING, nullable=False)
    
    expires_at = Column(DateTime, nullable=False)
    accepted_at = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)
    
    account = relationship("Account")
    role = relationship("Role")
    invited_by = relationship("User")
    
    @classmethod
    def generate_token(cls) -> str:
        """Generate a secure random token for the invitation."""
        return secrets.token_urlsafe(32)
    
    @classmethod
    def default_expiration(cls, days: int = 7) -> datetime:
        """Get default expiration datetime (7 days from now)."""
        return datetime.utcnow() + timedelta(days=days)
    
    @property
    def is_valid(self) -> bool:
        """Check if invitation is still valid (pending and not expired)."""
        if self.status != InvitationStatus.PENDING:
            return False
        return datetime.utcnow() < self.expires_at
    
    @property
    def is_expired(self) -> bool:
        """Check if invitation has expired."""
        return datetime.utcnow() >= self.expires_at
    
    def accept(self) -> None:
        """Mark invitation as accepted."""
        self.status = InvitationStatus.ACCEPTED
        self.accepted_at = datetime.utcnow()
    
    def revoke(self) -> None:
        """Revoke the invitation."""
        self.status = InvitationStatus.REVOKED
    
    def expire(self) -> None:
        """Mark invitation as expired."""
        self.status = InvitationStatus.EXPIRED
    
    def __repr__(self):
        return f"<AccountInvitation {self.invitee_email} -> {self.account_id} status={self.status.value}>"
