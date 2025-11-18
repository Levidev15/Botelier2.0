"""
Knowledge Entry Model - Individual Q&A entries for hotel knowledge base.

Each entry:
- Belongs directly to a hotel (simplified from knowledge_base grouping)
- Contains a question and answer pair
- Can have an optional category/tag for organization
- Can have an optional expiration date for time-sensitive info
"""

import uuid
from datetime import datetime, date
from sqlalchemy import Column, String, Text, DateTime, Date, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from botelier.database import Base


class KnowledgeEntry(Base):
    """
    Knowledge Entry model for storing Q&A pairs.
    
    Each entry is:
    - Owned directly by a hotel
    - Question/answer pair for structured RAG
    - Optionally categorized with free-text tags
    - Optionally expires for time-sensitive information
    """
    __tablename__ = "knowledge_entries"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Direct hotel ownership (simplified from knowledge_base_id)
    hotel_id = Column(UUID(as_uuid=True), ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False)
    
    # Q&A content
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    
    # Organization via free-text category tags
    category = Column(String(100), nullable=True)
    
    # Expiration for time-sensitive info (weekly specials, events, etc.)
    expiration_date = Column(Date, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<KnowledgeEntry {self.question[:50]}...>"
    
    @property
    def is_expired(self):
        """Check if entry is expired."""
        if not self.expiration_date:
            return False
        return date.today() > self.expiration_date
    
    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "hotel_id": str(self.hotel_id),
            "question": self.question,
            "answer": self.answer,
            "category": self.category,
            "expiration_date": self.expiration_date.isoformat() if self.expiration_date else None,
            "is_expired": self.is_expired,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "updated_at": self.updated_at.isoformat() + "Z" if self.updated_at else None,
        }
