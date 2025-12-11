"""
AssistantDisposition Model - Custom call dispositions per assistant.

Each assistant can define its own set of dispositions that the AI
will choose from based on the conversation content.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Boolean, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from botelier.database import Base


class AssistantDisposition(Base):
    """
    AssistantDisposition model for custom call dispositions.
    
    Each assistant can have multiple dispositions configured.
    At call end, AI analyzes the transcript and selects the best-fit disposition.
    """
    __tablename__ = "assistant_dispositions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    assistant_id = Column(UUID(as_uuid=True), ForeignKey("assistants.id", ondelete="CASCADE"), nullable=False, index=True)
    
    name = Column(String(100), nullable=False)
    
    description = Column(Text, nullable=True)
    
    color = Column(String(20), nullable=True, default="#6366f1")
    
    display_order = Column(Integer, nullable=False, default=0)
    
    is_active = Column(Boolean, default=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<AssistantDisposition {self.name}>"
    
    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "assistant_id": str(self.assistant_id),
            "name": self.name,
            "description": self.description,
            "color": self.color,
            "display_order": self.display_order,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "updated_at": self.updated_at.isoformat() + "Z" if self.updated_at else None,
        }
