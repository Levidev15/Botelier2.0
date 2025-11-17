"""
Knowledge Document Model - Individual documents within a knowledge base.

Each document:
- Belongs to one knowledge base
- Contains text content for RAG queries
- Tracks file metadata (name, size, type)
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from botelier.database import Base


class KnowledgeDocument(Base):
    """
    Knowledge Document model for storing individual text documents.
    
    Each document is:
    - Part of a knowledge base
    - Plain text content (or parsed from PDF/DOCX)
    - Searchable via RAG function calling
    """
    __tablename__ = "knowledge_documents"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Ownership
    knowledge_base_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False)
    
    # Document metadata
    filename = Column(String(255), nullable=False)
    content_type = Column(String(50), nullable=False, default="text")  # text, pdf, docx
    
    # Content
    content = Column(Text, nullable=False)  # Actual text content
    character_count = Column(Integer, nullable=False, default=0)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<KnowledgeDocument {self.filename}>"
    
    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "knowledge_base_id": str(self.knowledge_base_id),
            "filename": self.filename,
            "content_type": self.content_type,
            "character_count": self.character_count,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
        }
