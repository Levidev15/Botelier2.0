"""Integration Models - Multi-tenant integration system for third-party services.

Supports platform-level integration types (e.g., Oracle Opera Cloud) that accounts
can connect to with their own credentials. Data is completely isolated per account.

Models:
  IntegrationType      — platform-level registry of available integration types (seeded)
  AccountIntegration   — per-account connection to an integration type (encrypted creds)
  AccountSecret        — per-account encrypted key-value secret store for custom API calls
  IntegrationCallLog   — per-call log of every external API call made via integrations
"""

import enum
import json
import uuid
from datetime import datetime

from cryptography.fernet import InvalidToken
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from botelier.crypto import get_cipher as _get_platform_cipher
from botelier.database import Base


class IntegrationStatus(str, enum.Enum):
    """Status of an account's integration connection."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    TOKEN_EXPIRED = "token_expired"


class IntegrationActionKind(str, enum.Enum):
    """Origin/type for a reusable account action."""

    CERTIFIED = "certified"
    CUSTOM_HTTP = "custom_http"
    IMPORTED = "imported"  # Auto-generated from Universal Adapter spec import


class IntegrationActionStatus(str, enum.Enum):
    """Lifecycle status for reusable actions."""

    DRAFT = "draft"
    PUBLISHED = "published"
    DISABLED = "disabled"


class IntegrationInvocationChannel(str, enum.Enum):
    """Runtime channel that invoked an integration action."""

    VOICE = "voice"
    SMS = "sms"
    FLOW = "flow"
    TEST = "test"
    API = "api"


class IntegrationType(Base):
    """Platform-level registry of available integrations.

    These are seeded by the platform (e.g., Oracle Opera Cloud, future integrations).
    Accounts can choose to connect to any enabled integration type.
    """

    __tablename__ = "integration_types"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    slug = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    logo_url = Column(String, nullable=True)

    provider = Column(String, nullable=False)

    auth_type = Column(String, nullable=False, default="oauth2")

    auth_config = Column(Text, nullable=True)

    required_fields = Column(Text, nullable=True)

    endpoints_config = Column(Text, nullable=True)

    is_enabled = Column(Boolean, default=True, nullable=False)

    documentation_url = Column(String, nullable=True)

    # Universal Adapter — provenance
    origin = Column(
        String(32), nullable=False, default="platform_certified"
    )  # platform_certified | customer_imported
    source_type = Column(
        String(32), nullable=True
    )  # manual | openapi | swagger | postman
    raw_spec = Column(JSONB, nullable=True)
    spec_version = Column(String(32), nullable=True)
    spec_url = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    account_integrations = relationship(
        "AccountIntegration", back_populates="integration_type", cascade="all, delete-orphan"
    )

    def get_auth_config(self) -> dict:
        """Parse auth_config JSON."""
        if self.auth_config:
            return json.loads(self.auth_config)
        return {}

    def set_auth_config(self, config: dict):
        """Set auth_config from dict."""
        self.auth_config = json.dumps(config)

    def get_required_fields(self) -> list:
        """Parse required_fields JSON."""
        if self.required_fields:
            return json.loads(self.required_fields)
        return []

    def set_required_fields(self, fields: list):
        """Set required_fields from list."""
        self.required_fields = json.dumps(fields)

    def get_endpoints(self) -> list:
        """Parse endpoints_config JSON."""
        if self.endpoints_config:
            return json.loads(self.endpoints_config)
        return []

    def set_endpoints(self, endpoints: list):
        """Set endpoints_config from list."""
        self.endpoints_config = json.dumps(endpoints)

    def __repr__(self):
        return f"<IntegrationType {self.slug} ({self.name})>"


class AccountIntegration(Base):
    """Per-account connection to an integration type.

    Accounts can have multiple connections per integration type (e.g., one per hotel).
    Each connection has a name for identification. Credentials are encrypted at rest.
    """

    __tablename__ = "account_integrations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    integration_type_id = Column(
        UUID(as_uuid=True),
        ForeignKey("integration_types.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Per-property scoping (Task #327). NULL = account-global (shared) connection,
    # usable by any property under the account (e.g. one central reservation
    # system). A non-NULL value binds the connection to a single property and the
    # integration-resolution layer fails closed for callers on any other property.
    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    connection_name = Column(String, nullable=True)

    status = Column(
        SQLEnum(IntegrationStatus), default=IntegrationStatus.DISCONNECTED, nullable=False
    )

    credentials_encrypted = Column(Text, nullable=True)

    access_token_encrypted = Column(Text, nullable=True)
    refresh_token_encrypted = Column(Text, nullable=True)
    token_expires_at = Column(DateTime, nullable=True)

    connection_config = Column(Text, nullable=True)

    last_sync_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)

    # Universal Adapter — per-connection metadata
    environment = Column(
        String(16), nullable=False, default="production"
    )  # sandbox | production
    allowed_base_domains = Column(
        JSONB, nullable=True
    )  # SSRF allowlist; None = not restricted

    connected_at = Column(DateTime, nullable=True)
    connected_by_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    integration_type = relationship("IntegrationType", back_populates="account_integrations")

    def _get_cipher(self):
        """Get the platform-wide credential cipher."""
        return _get_platform_cipher()

    def set_credentials(self, credentials: dict):
        """Encrypt and store credentials."""
        cipher = self._get_cipher()
        data = json.dumps(credentials).encode()
        self.credentials_encrypted = cipher.encrypt(data).decode()

    def get_credentials(self) -> dict:
        """Decrypt and return credentials.

        Returns {} if the stored blob cannot be decrypted (e.g. the encryption
        key was rotated since the credentials were saved).  Callers that need
        to merge-in new values will treat missing fields as absent, prompting
        the user to re-enter them — far better than a 500.
        """
        if not self.credentials_encrypted:
            return {}
        try:
            cipher = self._get_cipher()
            data = cipher.decrypt(self.credentials_encrypted.encode())
            return json.loads(data.decode())
        except (InvalidToken, Exception):
            import logging
            logging.getLogger(__name__).warning(
                "get_credentials: decryption failed for integration %s — "
                "key may have rotated; returning empty dict",
                self.id,
            )
            return {}

    def set_access_token(self, token: str):
        """Encrypt and store access token."""
        cipher = self._get_cipher()
        self.access_token_encrypted = cipher.encrypt(token.encode()).decode()

    def get_access_token(self) -> str | None:
        """Decrypt and return access token.

        Returns None on decryption failure so callers treat the token as
        expired and trigger a fresh token fetch rather than crashing.
        """
        if not self.access_token_encrypted:
            return None
        try:
            cipher = self._get_cipher()
            return cipher.decrypt(self.access_token_encrypted.encode()).decode()
        except (InvalidToken, Exception):
            import logging
            logging.getLogger(__name__).warning(
                "get_access_token: decryption failed for integration %s", self.id
            )
            return None

    def set_refresh_token(self, token: str):
        """Encrypt and store refresh token."""
        cipher = self._get_cipher()
        self.refresh_token_encrypted = cipher.encrypt(token.encode()).decode()

    def get_refresh_token(self) -> str | None:
        """Decrypt and return refresh token.

        Returns None on decryption failure so callers skip the stale token
        and fall back to a full re-authenticate.
        """
        if not self.refresh_token_encrypted:
            return None
        try:
            cipher = self._get_cipher()
            return cipher.decrypt(self.refresh_token_encrypted.encode()).decode()
        except (InvalidToken, Exception):
            import logging
            logging.getLogger(__name__).warning(
                "get_refresh_token: decryption failed for integration %s", self.id
            )
            return None

    def get_connection_config(self) -> dict:
        """Parse connection_config JSON."""
        if self.connection_config:
            return json.loads(self.connection_config)
        return {}

    def set_connection_config(self, config: dict):
        """Set connection_config from dict."""
        self.connection_config = json.dumps(config)

    def is_token_expired(self) -> bool:
        """Check if access token is expired."""
        if not self.token_expires_at:
            return True
        return datetime.utcnow() >= self.token_expires_at

    def __repr__(self):
        return f"<AccountIntegration account={self.account_id} type={self.integration_type_id} status={self.status.value}>"


class AccountSecret(Base):
    """Per-account encrypted key-value secret store.

    Stores sensitive values (API keys, tokens) encrypted at rest using the same
    Fernet key as AccountIntegration. Secrets are referenced in flow/tool configs
    as {{secrets.key_name}} — the actual value is never stored in the config.

    The secret value is NEVER returned by any API endpoint. Only metadata
    (id, name, key, description, created_at) is exposed to the frontend.
    """

    __tablename__ = "account_secrets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name = Column(String(255), nullable=False)

    key = Column(String(100), nullable=False, index=True)

    value_encrypted = Column(Text, nullable=False)

    description = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    def _get_cipher(self):
        return _get_platform_cipher()

    def set_value(self, value: str):
        """Encrypt and store the secret value."""
        cipher = self._get_cipher()
        self.value_encrypted = cipher.encrypt(value.encode()).decode()

    def get_value(self) -> str:
        """Decrypt and return the secret value."""
        if not self.value_encrypted:
            return ""
        cipher = self._get_cipher()
        return cipher.decrypt(self.value_encrypted.encode()).decode()

    def __repr__(self):
        return f"<AccountSecret account={self.account_id} key={self.key}>"


class IntegrationCallLog(Base):
    """Log of every external API call made via IntegrationClient or custom URL flows.

    Written fire-and-forget after each call — logging failures never block the response.
    Used for integration health monitoring and debugging.

    integration_id is nullable to support custom URL calls (no AccountIntegration).
    """

    __tablename__ = "integration_call_logs"

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

    endpoint_called = Column(String(500), nullable=True)

    method = Column(String(10), nullable=True)

    status_code = Column(Integer, nullable=True)

    success = Column(Boolean, nullable=False, default=False)

    latency_ms = Column(Integer, nullable=True)

    error_type = Column(String(50), nullable=True)

    error_message = Column(Text, nullable=True)

    called_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self):
        return f"<IntegrationCallLog account={self.account_id} integration={self.integration_id} success={self.success}>"


class IntegrationAction(Base):
    """Reusable action shown in the no-code Action Library.

    Certified actions are owned by the platform and can be backed by an
    AccountIntegration.  Custom HTTP actions are owned by an account and execute
    through the same guarded runtime.
    """

    __tablename__ = "integration_actions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    integration_type_id = Column(
        UUID(as_uuid=True),
        ForeignKey("integration_types.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_endpoint_id = Column(String(255), nullable=True)

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    slug = Column(String(255), nullable=False, index=True)
    kind = Column(SQLEnum(IntegrationActionKind), nullable=False)
    status = Column(
        SQLEnum(IntegrationActionStatus),
        nullable=False,
        default=IntegrationActionStatus.DRAFT,
        index=True,
    )

    published_version_id = Column(UUID(as_uuid=True), nullable=True)
    last_tested_at = Column(DateTime, nullable=True)
    last_test_success = Column(Boolean, nullable=True)
    last_error = Column(Text, nullable=True)

    # Universal Adapter — IMPORTED kind links to the specific connection that
    # owns this operation.  NULL for CERTIFIED / CUSTOM_HTTP kinds.
    connection_id = Column(
        UUID(as_uuid=True),
        ForeignKey("account_integrations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Per-parameter ownership map: {param_name: "llm"|"connection"|"secret"|"fixed"|"derived"}
    param_ownership = Column(JSONB, nullable=True)
    # Response bounding + redaction policy for IMPORTED operations.
    response_policy = Column(JSONB, nullable=True)

    created_by_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    versions = relationship(
        "IntegrationActionVersion",
        back_populates="action",
        cascade="all, delete-orphan",
    )

    def to_dict(self, include_config: bool = False):
        result = {
            "id": str(self.id),
            "account_id": str(self.account_id) if self.account_id else None,
            "integration_type_id": str(self.integration_type_id) if self.integration_type_id else None,
            "source_endpoint_id": self.source_endpoint_id,
            "name": self.name,
            "description": self.description,
            "slug": self.slug,
            "kind": self.kind.value if self.kind else None,
            "status": self.status.value if self.status else None,
            "published_version_id": str(self.published_version_id)
            if self.published_version_id
            else None,
            "last_tested_at": self.last_tested_at.isoformat() if self.last_tested_at else None,
            "last_test_success": self.last_test_success,
            "last_error": self.last_error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_config:
            published = next(
                (v for v in self.versions if str(v.id) == str(self.published_version_id)),
                None,
            )
            if published:
                result["config"] = published.config
                result["input_schema"] = published.input_schema
                result["output_schema"] = published.output_schema
        return result


class IntegrationActionVersion(Base):
    """Versioned action configuration.

    Published versions are immutable runtime contracts; drafts can be edited and
    tested before publishing.
    """

    __tablename__ = "integration_action_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action_id = Column(
        UUID(as_uuid=True),
        ForeignKey("integration_actions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number = Column(Integer, nullable=False)
    status = Column(SQLEnum(IntegrationActionStatus), nullable=False)
    config = Column(JSONB, nullable=False, default=dict)
    input_schema = Column(JSONB, nullable=False, default=dict)
    output_schema = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    published_at = Column(DateTime, nullable=True)

    action = relationship("IntegrationAction", back_populates="versions")

    def to_dict(self):
        return {
            "id": str(self.id),
            "action_id": str(self.action_id),
            "version_number": self.version_number,
            "status": self.status.value if self.status else None,
            "config": self.config,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "published_at": self.published_at.isoformat() if self.published_at else None,
        }


class IntegrationActionInvocation(Base):
    """Normalized audit row for every action execution."""

    __tablename__ = "integration_action_invocations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_id = Column(
        UUID(as_uuid=True),
        ForeignKey("integration_actions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("integration_action_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    integration_id = Column(
        UUID(as_uuid=True),
        ForeignKey("account_integrations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    channel = Column(String(32), nullable=False, default=IntegrationInvocationChannel.API.value)
    call_sid = Column(String(64), nullable=True, index=True)
    call_log_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    tool_id = Column(String(36), nullable=True, index=True)
    flow_version_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    flow_tool_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    node_id = Column(String(255), nullable=True, index=True)
    source_label = Column(String(255), nullable=True)
    request_id = Column(String(64), nullable=False, index=True)

    endpoint_called = Column(String(500), nullable=True)
    method = Column(String(10), nullable=True)
    status_code = Column(Integer, nullable=True)
    success = Column(Boolean, nullable=False, default=False)
    latency_ms = Column(Integer, nullable=True)
    error_type = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    response_metadata = Column(JSONB, nullable=True)
    called_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
