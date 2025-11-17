"""
Assistant Knowledge Base Link - Many-to-many relationship.

Links assistants to knowledge bases:
- One assistant can have multiple knowledge bases
- One knowledge base can be used by multiple assistants
"""

from sqlalchemy import Column, ForeignKey, PrimaryKeyConstraint
from sqlalchemy.dialects.postgresql import UUID
from botelier.database import Base


class AssistantKnowledgeBase(Base):
    """
    Junction table linking assistants to knowledge bases.
    
    This enables:
    - Assistants to use multiple knowledge bases
    - Knowledge bases to be shared across assistants
    """
    __tablename__ = "assistant_knowledge_bases"
    
    assistant_id = Column(UUID(as_uuid=True), ForeignKey("assistants.id", ondelete="CASCADE"), nullable=False)
    knowledge_base_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False)
    
    __table_args__ = (
        PrimaryKeyConstraint('assistant_id', 'knowledge_base_id'),
    )
    
    def __repr__(self):
        return f"<AssistantKnowledgeBase assistant={self.assistant_id} kb={self.knowledge_base_id}>"
