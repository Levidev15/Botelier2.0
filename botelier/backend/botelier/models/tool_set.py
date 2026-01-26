"""
ToolSet model for organizing tools into named collections.

ToolSets are named collections of tools that can be assigned to assistants.
This allows tools to be shared across multiple assistants and organized
by purpose (e.g., "Front Desk Tools", "Reservation Tools").
"""

from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid as uuid_pkg

from botelier.database import Base


class ToolSet(Base):
    """
    Named collection of tools belonging to an account.
    
    Attributes:
        id: UUID primary key
        account_id: Parent account UUID
        name: Display name (e.g., "Front Desk Tools")
        description: Optional description
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """
    
    __tablename__ = "tool_sets"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid_pkg.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    tools = relationship("Tool", back_populates="tool_set", lazy="dynamic")
    
    def __repr__(self):
        return f"<ToolSet(id={self.id}, name={self.name})>"
    
    def to_dict(self, include_tool_count: bool = False):
        """Convert model to dictionary for API responses."""
        result = {
            "id": str(self.id),
            "account_id": str(self.account_id),
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        
        if include_tool_count and self.tools:
            result["tool_count"] = self.tools.count()
        
        return result
