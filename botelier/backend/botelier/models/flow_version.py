"""
Flow Version model for storing versioned flow configurations.

Each flow tool can have multiple versions:
- One active draft (work in progress)
- Multiple published versions (immutable history)
"""

import uuid as uuid_pkg
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Integer, ForeignKey, Enum as SQLEnum, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
import enum

from botelier.database import Base


class FlowVersionStatus(str, enum.Enum):
    """Status of a flow version."""
    DRAFT = "draft"
    PUBLISHED = "published"


class FlowVersion(Base):
    """
    Flow version for storing versioned flow configurations.
    
    Workflow:
    1. User edits flow → saves as DRAFT
    2. User tests in simulator with DRAFT
    3. User publishes → DRAFT becomes new PUBLISHED version
    4. Live calls always use latest PUBLISHED version
    5. User can revert any PUBLISHED version to a new DRAFT
    """
    __tablename__ = "flow_versions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid_pkg.uuid4)
    
    tool_id = Column(String(36), ForeignKey("tools.id", ondelete="CASCADE"), nullable=False, index=True)
    
    version_number = Column(Integer, nullable=False)
    
    status = Column(SQLEnum(FlowVersionStatus), nullable=False, default=FlowVersionStatus.DRAFT)
    
    description = Column(Text, nullable=True)
    
    flow_config = Column(JSONB, nullable=False, default=dict)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(String(255), nullable=True)
    
    published_at = Column(DateTime(timezone=True), nullable=True)
    published_by = Column(String(255), nullable=True)
    
    __table_args__ = (
        UniqueConstraint('tool_id', 'version_number', name='uq_tool_version'),
        Index('ix_flow_versions_tool_status', 'tool_id', 'status'),
    )
    
    def __repr__(self):
        return f"<FlowVersion(tool_id={self.tool_id}, v{self.version_number}, {self.status.value})>"
    
    def to_dict(self):
        """Convert model to dictionary for API responses."""
        return {
            "id": str(self.id),
            "tool_id": self.tool_id,
            "version_number": self.version_number,
            "status": self.status.value,
            "description": self.description,
            "flow_config": self.flow_config,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "created_by": self.created_by,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "published_by": self.published_by,
        }
    
    def to_summary_dict(self):
        """Convert to summary dictionary (without full flow_config)."""
        return {
            "id": str(self.id),
            "tool_id": self.tool_id,
            "version_number": self.version_number,
            "status": self.status.value,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "published_at": self.published_at.isoformat() if self.published_at else None,
        }
