"""
Integration Models - Multi-tenant integration system for third-party services.

Supports platform-level integration types (e.g., Oracle Opera Cloud) that accounts
can connect to with their own credentials. Data is completely isolated per account.

Models:
  IntegrationType      — platform-level registry of available integration types (seeded)
  AccountIntegration   — per-account connection to an integration type (encrypted creds)
  AccountSecret        — per-account encrypted key-value secret store for custom API calls
  IntegrationCallLog   — per-call log of every external API call made via integrations
"""

import uuid
import json
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Text, ForeignKey, Integer, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum
from cryptography.fernet import Fernet
import os

from botelier.database import Base


def get_encryption_key():
    """Get or create encryption key for credential storage."""
    key = os.environ.get("INTEGRATION_ENCRYPTION_KEY")
    if not key:
        key = Fernet.generate_key().decode()
        os.environ["INTEGRATION_ENCRYPTION_KEY"] = key
    return key.encode() if isinstance(key, str) else key


class IntegrationStatus(str, enum.Enum):
    """Status of an account's integration connection."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    TOKEN_EXPIRED = "token_expired"


class IntegrationType(Base):
    """
    Platform-level registry of available integrations.
    
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
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)
    
    account_integrations = relationship("AccountIntegration", back_populates="integration_type", cascade="all, delete-orphan")
    
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
    """
    Per-account connection to an integration type.
    
    Accounts can have multiple connections per integration type (e.g., one per hotel).
    Each connection has a name for identification. Credentials are encrypted at rest.
    """
    __tablename__ = "account_integrations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    
    integration_type_id = Column(UUID(as_uuid=True), ForeignKey("integration_types.id", ondelete="CASCADE"), nullable=False, index=True)
    
    connection_name = Column(String, nullable=True)
    
    status = Column(SQLEnum(IntegrationStatus), default=IntegrationStatus.DISCONNECTED, nullable=False)
    
    credentials_encrypted = Column(Text, nullable=True)
    
    access_token_encrypted = Column(Text, nullable=True)
    refresh_token_encrypted = Column(Text, nullable=True)
    token_expires_at = Column(DateTime, nullable=True)
    
    connection_config = Column(Text, nullable=True)
    
    last_sync_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    
    connected_at = Column(DateTime, nullable=True)
    connected_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)
    
    integration_type = relationship("IntegrationType", back_populates="account_integrations")
    
    def _get_cipher(self):
        """Get Fernet cipher for encryption/decryption."""
        return Fernet(get_encryption_key())
    
    def set_credentials(self, credentials: dict):
        """Encrypt and store credentials."""
        cipher = self._get_cipher()
        data = json.dumps(credentials).encode()
        self.credentials_encrypted = cipher.encrypt(data).decode()
    
    def get_credentials(self) -> dict:
        """Decrypt and return credentials."""
        if not self.credentials_encrypted:
            return {}
        cipher = self._get_cipher()
        data = cipher.decrypt(self.credentials_encrypted.encode())
        return json.loads(data.decode())
    
    def set_access_token(self, token: str):
        """Encrypt and store access token."""
        cipher = self._get_cipher()
        self.access_token_encrypted = cipher.encrypt(token.encode()).decode()
    
    def get_access_token(self) -> str | None:
        """Decrypt and return access token."""
        if not self.access_token_encrypted:
            return None
        cipher = self._get_cipher()
        return cipher.decrypt(self.access_token_encrypted.encode()).decode()
    
    def set_refresh_token(self, token: str):
        """Encrypt and store refresh token."""
        cipher = self._get_cipher()
        self.refresh_token_encrypted = cipher.encrypt(token.encode()).decode()
    
    def get_refresh_token(self) -> str | None:
        """Decrypt and return refresh token."""
        if not self.refresh_token_encrypted:
            return None
        cipher = self._get_cipher()
        return cipher.decrypt(self.refresh_token_encrypted.encode()).decode()
    
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
    """
    Per-account encrypted key-value secret store.

    Stores sensitive values (API keys, tokens) encrypted at rest using the same
    Fernet key as AccountIntegration. Secrets are referenced in flow/tool configs
    as {{secrets.key_name}} — the actual value is never stored in the config.

    The secret value is NEVER returned by any API endpoint. Only metadata
    (id, name, key, description, created_at) is exposed to the frontend.
    """
    __tablename__ = "account_secrets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)

    name = Column(String(255), nullable=False)

    key = Column(String(100), nullable=False, index=True)

    value_encrypted = Column(Text, nullable=False)

    description = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    def _get_cipher(self):
        return Fernet(get_encryption_key())

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
    """
    Log of every external API call made via IntegrationClient or custom URL flows.

    Written fire-and-forget after each call — logging failures never block the response.
    Used for integration health monitoring and debugging.

    integration_id is nullable to support custom URL calls (no AccountIntegration).
    """
    __tablename__ = "integration_call_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    account_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    integration_id = Column(UUID(as_uuid=True), nullable=True, index=True)

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
