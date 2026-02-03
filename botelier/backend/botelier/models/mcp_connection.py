"""
MCP Connection Model - Multi-tenant MCP (Model Context Protocol) server connections.

Each account can connect to one or more MCP servers to provide dynamic tools
for their assistants. This follows the named collections pattern (like KnowledgeBase/ToolSet).
"""

import uuid
import json
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Text, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
import enum
from cryptography.fernet import Fernet
import os

from botelier.database import Base


def get_mcp_encryption_key():
    """Get or create encryption key for MCP credential storage."""
    key = os.environ.get("MCP_ENCRYPTION_KEY")
    if not key:
        key = os.environ.get("INTEGRATION_ENCRYPTION_KEY")
    if not key:
        key = Fernet.generate_key().decode()
        os.environ["MCP_ENCRYPTION_KEY"] = key
    return key.encode() if isinstance(key, str) else key


class MCPConnectionStatus(str, enum.Enum):
    """Status of an MCP connection."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class MCPAuthType(str, enum.Enum):
    """Authentication type for MCP servers."""
    NONE = "none"
    API_KEY = "api_key"
    BEARER = "bearer"
    BASIC = "basic"
    OAUTH2 = "oauth2"


class MCPTransportType(str, enum.Enum):
    """Transport type for MCP server connections."""
    STDIO = "stdio"
    HTTP = "http"
    SSE = "sse"
    WEBSOCKET = "websocket"


class MCPConnection(Base):
    """
    MCP Connection model for connecting to external MCP servers.
    
    Each connection allows an account to access tools provided by an MCP server.
    Follows the named collections pattern - assistants reference connections by ID.
    
    Key features:
    - Encrypted credential storage
    - Tool discovery and caching
    - Per-assistant tool enable/disable (via assistant's mcp_enabled_tools JSONB)
    """
    __tablename__ = "mcp_connections"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    transport_type = Column(SQLEnum(MCPTransportType), default=MCPTransportType.SSE, nullable=False)
    
    server_url = Column(String, nullable=False)
    
    auth_type = Column(SQLEnum(MCPAuthType), default=MCPAuthType.NONE, nullable=False)
    
    credentials_encrypted = Column(Text, nullable=True)
    
    status = Column(SQLEnum(MCPConnectionStatus), default=MCPConnectionStatus.DISCONNECTED, nullable=False)
    
    discovered_tools = Column(JSONB, nullable=True, default=list)
    
    last_connected_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    
    is_active = Column(Boolean, default=True, nullable=False)
    
    connection_config = Column(JSONB, nullable=True, default=dict)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)
    
    def _get_cipher(self):
        """Get Fernet cipher for encryption/decryption."""
        return Fernet(get_mcp_encryption_key())
    
    def set_credentials(self, credentials: dict):
        """Encrypt and store credentials."""
        if not credentials:
            self.credentials_encrypted = None
            return
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
    
    def get_discovered_tools(self) -> list:
        """Get list of discovered tools from the MCP server."""
        return self.discovered_tools or []
    
    def set_discovered_tools(self, tools: list):
        """Store discovered tools list."""
        self.discovered_tools = tools
    
    def get_connection_config(self) -> dict:
        """Get additional connection configuration."""
        return self.connection_config or {}
    
    def set_connection_config(self, config: dict):
        """Set additional connection configuration."""
        self.connection_config = config
    
    def to_dict(self, include_tools: bool = True) -> dict:
        """Convert to dictionary for API responses."""
        result = {
            "id": str(self.id),
            "account_id": str(self.account_id),
            "name": self.name,
            "description": self.description,
            "transport_type": self.transport_type.value if self.transport_type else "sse",
            "server_url": self.server_url,
            "auth_type": self.auth_type.value if self.auth_type else "none",
            "status": self.status.value if self.status else "disconnected",
            "last_connected_at": self.last_connected_at.isoformat() + "Z" if self.last_connected_at else None,
            "last_error": self.last_error,
            "is_active": self.is_active,
            "connection_config": self.get_connection_config(),
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "updated_at": self.updated_at.isoformat() + "Z" if self.updated_at else None,
        }
        
        if include_tools:
            result["discovered_tools"] = self.get_discovered_tools()
        
        return result
    
    def __repr__(self):
        return f"<MCPConnection {self.name} ({self.status.value if self.status else 'unknown'})>"
