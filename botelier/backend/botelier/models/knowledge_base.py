"""
Knowledge Base Model - Named collection of Q&A entries.

Each knowledge base:
- Belongs to an account
- Contains multiple Q&A entries
- Can be assigned to one or more assistants
- Has a name and optional description
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from botelier.database import Base


class KnowledgeBase(Base):
    """
    Knowledge Base model for grouping Q&A entries.
    
    Each knowledge base is:
    - Owned by an account
    - A named collection of entries
    - Assignable to assistants
    """
    __tablename__ = "knowledge_bases"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    entries = relationship("KnowledgeEntry", back_populates="knowledge_base", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<KnowledgeBase {self.name}>"
    
    @property
    def entry_count(self):
        """Count of entries in this knowledge base."""
        return len(self.entries) if self.entries else 0
    
    def to_dict(self, include_entries=False):
        """Convert to dictionary for API responses."""
        result = {
            "id": str(self.id),
            "account_id": str(self.account_id),
            "name": self.name,
            "description": self.description,
            "entry_count": self.entry_count,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "updated_at": self.updated_at.isoformat() + "Z" if self.updated_at else None,
        }
        
        if include_entries and self.entries:
            result["entries"] = [entry.to_dict() for entry in self.entries]
        
        return result
