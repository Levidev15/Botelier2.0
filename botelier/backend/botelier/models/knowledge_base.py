"""
Knowledge Base Model - Represents a collection of documents for RAG.

Each knowledge base:
- Contains multiple documents (policies, menus, guides)
- Can be assigned to multiple assistants
- Owned by a hotel for multi-tenancy
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from botelier.database import Base


class KnowledgeBase(Base):
    """
    Knowledge Base model for storing hotel information.
    
    Each knowledge base is:
    - Owned by a hotel
    - Can contain multiple documents
    - Assigned to assistants for RAG queries
    """
    __tablename__ = "knowledge_bases"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Ownership
    hotel_id = Column(UUID(as_uuid=True), ForeignKey("hotels.id"), nullable=False)
    
    # Basic info
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<KnowledgeBase {self.name}>"
    
    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "hotel_id": str(self.hotel_id),
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "updated_at": self.updated_at.isoformat() + "Z" if self.updated_at else None,
        }
