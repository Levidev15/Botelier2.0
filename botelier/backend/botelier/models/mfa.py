"""Durable MFA challenges, sessions, limits and non-secret audit events."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from botelier.database import Base


class MFASession(Base):
    __tablename__ = "mfa_sessions"
    # SHA-256 of opaque cookie secret; never store the bearer/cookie itself.
    id = Column(String(64), primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    primary_at = Column(DateTime, nullable=False)
    verified_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    restricted = Column(Boolean, nullable=False, default=True)
    recovery_grant = Column(Boolean, nullable=False, default=False, server_default="false")
    revoked = Column(Boolean, nullable=False, default=False)
    pending_secret_encrypted = Column(Text, nullable=True)
    pending_expires_at = Column(DateTime, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class MFARecoveryCode(Base):
    __tablename__ = "mfa_recovery_codes"
    code_hash = Column(String(64), primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    consumed_at = Column(DateTime, nullable=True)


class MFARateLimit(Base):
    __tablename__ = "mfa_rate_limits"
    key = Column(String(64), primary_key=True)
    window_started_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, nullable=False, default=0)


class MFAAudit(Base):
    __tablename__ = "mfa_audit_events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    event = Column(String(64), nullable=False)
    account_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
