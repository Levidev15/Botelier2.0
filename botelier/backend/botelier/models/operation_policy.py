"""Operation Policy Models — Universal API Adapter.

Per-connection operation enablement, risk classification, and policy rules.
A ``ConnectionOperationPolicy`` row is created (default-disabled) for every
endpoint discovered in a spec import.  Operators enable, configure, test, and
publish each one through the Integration Builder UI.

``ApprovalRequest`` is written when ``approval_required=True`` on a policy and
execution is attempted; the engine blocks until the request resolves.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from botelier.database import Base


class OperationTestStatus(str, enum.Enum):
    UNTESTED = "untested"
    PASSED = "passed"
    FAILED = "failed"


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ConnectionOperationPolicy(Base):
    """Per-connection, per-operation policy row.

    Unique on (account_integration_id, operation_id).  One row is created per
    discovered endpoint; all start disabled.  Operators enable and configure via
    the Integration Builder dashboard.

    Execution lifecycle:
      Discovered (enabled=False) → Enabled → Tested (test_status=passed) → Published
      (operator calls publish_operation() which creates the Tool row).
    """

    __tablename__ = "connection_operation_policies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    account_integration_id = Column(
        UUID(as_uuid=True),
        ForeignKey("account_integrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Matches the endpoint ``id`` field in endpoints_config JSON.
    operation_id = Column(String(255), nullable=False)

    enabled = Column(Boolean, nullable=False, default=False)

    # read | write | financial | destructive | admin | sensitive
    risk_level = Column(String(32), nullable=True)

    confirm_required = Column(Boolean, nullable=False, default=False)
    approval_required = Column(Boolean, nullable=False, default=False)

    max_amount = Column(Numeric(12, 2), nullable=True)
    max_executions_per_conv = Column(Integer, nullable=True)

    # ["voice","sms","flow","test"] or NULL = all channels
    allowed_channels = Column(JSONB, nullable=True)

    # Response bounding
    response_size_bytes = Column(Integer, nullable=False, default=32768)
    redact_field_patterns = Column(JSONB, nullable=True)

    # Response field projection — {variable_name: jsonpath} dict.
    # When set, only the extracted fields are forwarded to the LLM instead of
    # the full raw response body (eliminates token bloat for large API payloads).
    response_mapping = Column(JSONB, nullable=True)

    # Param ownership overrides — {param_name: "llm"|"connection"|"fixed"}.
    # Overrides the ownership declared in the imported spec for each variable.
    param_ownership_overrides = Column(JSONB, nullable=True)

    # Request-shape overrides — {headers, content_type, body_template, timeout,
    # retry_count}. Normalized via operation_publisher.normalize_request_overrides
    # before persisting; baked into the published version config at publish time
    # so tested and live request shapes cannot diverge.
    request_overrides = Column(JSONB, nullable=True)

    # Test lifecycle
    test_status = Column(
        String(16),
        nullable=False,
        default=OperationTestStatus.UNTESTED.value,
    )
    tested_at = Column(DateTime, nullable=True)
    test_passed = Column(Boolean, nullable=True)
    test_error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    __table_args__ = (
        __import__("sqlalchemy").UniqueConstraint(
            "account_integration_id",
            "operation_id",
            name="uq_conn_op_policy",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "account_integration_id": str(self.account_integration_id),
            "operation_id": self.operation_id,
            "enabled": self.enabled,
            "risk_level": self.risk_level,
            "confirm_required": self.confirm_required,
            "approval_required": self.approval_required,
            "max_amount": float(self.max_amount) if self.max_amount is not None else None,
            "max_executions_per_conv": self.max_executions_per_conv,
            "allowed_channels": self.allowed_channels,
            "response_size_bytes": self.response_size_bytes,
            "redact_field_patterns": self.redact_field_patterns,
            "response_mapping": self.response_mapping or {},
            "param_ownership_overrides": self.param_ownership_overrides or {},
            "request_overrides": self.request_overrides or {},
            "test_status": self.test_status,
            "tested_at": self.tested_at.isoformat() if self.tested_at else None,
            "test_passed": self.test_passed,
            "test_error": self.test_error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ApprovalRequest(Base):
    """Human-approval gate written when a policy has ``approval_required=True``.

    The engine blocks further execution until the request is resolved by an
    admin.  Expired requests are treated as rejected.
    """

    __tablename__ = "approval_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    integration_id = Column(
        UUID(as_uuid=True),
        ForeignKey("account_integrations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action_id = Column(
        UUID(as_uuid=True),
        ForeignKey("integration_actions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    channel = Column(String(32), nullable=False)
    call_sid = Column(String(64), nullable=True, index=True)

    requested_args = Column(JSONB, nullable=True)
    amount = Column(Numeric(12, 2), nullable=True)

    status = Column(String(16), nullable=False, default=ApprovalStatus.PENDING.value)
    resolved_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "account_id": str(self.account_id),
            "integration_id": str(self.integration_id) if self.integration_id else None,
            "action_id": str(self.action_id) if self.action_id else None,
            "channel": self.channel,
            "call_sid": self.call_sid,
            "requested_args": self.requested_args,
            "amount": float(self.amount) if self.amount is not None else None,
            "status": self.status,
            "resolved_by": str(self.resolved_by) if self.resolved_by else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }
