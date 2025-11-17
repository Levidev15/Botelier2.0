"""
Knowledge Bases API - CRUD operations for hotel knowledge bases.

Endpoints:
- GET /api/knowledge-bases - List hotel's knowledge bases
- POST /api/knowledge-bases - Create new knowledge base
- GET /api/knowledge-bases/{id} - Get knowledge base details
- PUT /api/knowledge-bases/{id} - Update knowledge base
- DELETE /api/knowledge-bases/{id} - Delete knowledge base
- POST /api/knowledge-bases/{id}/documents - Add document to knowledge base
- GET /api/knowledge-bases/{id}/documents - List documents in knowledge base
- DELETE /api/knowledge-bases/{id}/documents/{doc_id} - Delete document
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from botelier.database import get_db
from botelier.models.knowledge_base import KnowledgeBase
from botelier.models.knowledge_document import KnowledgeDocument


router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge-bases"])


class KnowledgeBaseCreate(BaseModel):
    """Request model for creating a knowledge base."""
    hotel_id: str
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class KnowledgeBaseUpdate(BaseModel):
    """Request model for updating a knowledge base."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None


class KnowledgeBaseResponse(BaseModel):
    """Response model for knowledge base."""
    id: str
    hotel_id: str
    name: str
    description: Optional[str]
    document_count: int
    created_at: Optional[str]
    updated_at: Optional[str]


class DocumentCreate(BaseModel):
    """Request model for adding a document."""
    filename: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    content_type: str = Field(default="text", pattern="^(text|pdf|docx)$")


class DocumentResponse(BaseModel):
    """Response model for knowledge document."""
    id: str
    knowledge_base_id: str
    filename: str
    content_type: str
    character_count: int
    created_at: Optional[str]


@router.get("", response_model=dict)
async def list_knowledge_bases(
    hotel_id: Optional[str] = Query(None, description="Filter by hotel ID"),
    db: Session = Depends(get_db)
):
    """
    List all knowledge bases, optionally filtered by hotel.
    
    Query params:
    - hotel_id: Filter by hotel UUID
    
    Returns:
    - List of knowledge bases with document counts
    """
    query = db.query(KnowledgeBase)
    
    if hotel_id:
        query = query.filter(KnowledgeBase.hotel_id == hotel_id)
    
    knowledge_bases = query.order_by(KnowledgeBase.created_at.desc()).all()
    
    result = []
    for kb in knowledge_bases:
        doc_count = db.query(KnowledgeDocument).filter(
            KnowledgeDocument.knowledge_base_id == kb.id
        ).count()
        
        kb_dict = kb.to_dict()
        kb_dict["document_count"] = doc_count
        result.append(kb_dict)
    
    return {
        "knowledge_bases": result,
        "total": len(result)
    }


@router.post("", status_code=201)
async def create_knowledge_base(
    data: KnowledgeBaseCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new knowledge base for a hotel.
    
    Body:
    - hotel_id: UUID of the hotel
    - name: Name of the knowledge base
    - description: Optional description
    
    Returns:
    - Created knowledge base
    """
    kb = KnowledgeBase(
        hotel_id=data.hotel_id,
        name=data.name,
        description=data.description
    )
    
    db.add(kb)
    db.commit()
    db.refresh(kb)
    
    result = kb.to_dict()
    result["document_count"] = 0
    
    return result


@router.get("/{kb_id}")
async def get_knowledge_base(
    kb_id: str,
    db: Session = Depends(get_db)
):
    """
    Get a specific knowledge base by ID.
    
    Path params:
    - kb_id: Knowledge base UUID
    
    Returns:
    - Knowledge base details with document count
    """
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    doc_count = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.knowledge_base_id == kb.id
    ).count()
    
    result = kb.to_dict()
    result["document_count"] = doc_count
    
    return result


@router.put("/{kb_id}")
async def update_knowledge_base(
    kb_id: str,
    data: KnowledgeBaseUpdate,
    db: Session = Depends(get_db)
):
    """
    Update a knowledge base.
    
    Path params:
    - kb_id: Knowledge base UUID
    
    Body:
    - name: Optional new name
    - description: Optional new description
    
    Returns:
    - Updated knowledge base
    """
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    if data.name is not None:
        kb.name = data.name
    if data.description is not None:
        kb.description = data.description
    
    db.commit()
    db.refresh(kb)
    
    doc_count = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.knowledge_base_id == kb.id
    ).count()
    
    result = kb.to_dict()
    result["document_count"] = doc_count
    
    return result


@router.delete("/{kb_id}", status_code=204)
async def delete_knowledge_base(
    kb_id: str,
    db: Session = Depends(get_db)
):
    """
    Delete a knowledge base and all its documents.
    
    Path params:
    - kb_id: Knowledge base UUID
    
    Returns:
    - 204 No Content on success
    """
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    db.delete(kb)
    db.commit()


@router.post("/{kb_id}/documents", status_code=201)
async def add_document(
    kb_id: str,
    data: DocumentCreate,
    db: Session = Depends(get_db)
):
    """
    Add a document to a knowledge base.
    
    Path params:
    - kb_id: Knowledge base UUID
    
    Body:
    - filename: Document filename
    - content: Text content
    - content_type: Type (text, pdf, docx)
    
    Returns:
    - Created document
    """
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    doc = KnowledgeDocument(
        knowledge_base_id=kb_id,
        filename=data.filename,
        content=data.content,
        content_type=data.content_type,
        character_count=len(data.content)
    )
    
    db.add(doc)
    db.commit()
    db.refresh(doc)
    
    return doc.to_dict()


@router.get("/{kb_id}/documents")
async def list_documents(
    kb_id: str,
    db: Session = Depends(get_db)
):
    """
    List all documents in a knowledge base.
    
    Path params:
    - kb_id: Knowledge base UUID
    
    Returns:
    - List of documents
    """
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    documents = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.knowledge_base_id == kb_id
    ).order_by(KnowledgeDocument.created_at.desc()).all()
    
    return {
        "documents": [doc.to_dict() for doc in documents],
        "total": len(documents)
    }


@router.delete("/{kb_id}/documents/{doc_id}", status_code=204)
async def delete_document(
    kb_id: str,
    doc_id: str,
    db: Session = Depends(get_db)
):
    """
    Delete a document from a knowledge base.
    
    Path params:
    - kb_id: Knowledge base UUID
    - doc_id: Document UUID
    
    Returns:
    - 204 No Content on success
    """
    doc = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.id == doc_id,
        KnowledgeDocument.knowledge_base_id == kb_id
    ).first()
    
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    db.delete(doc)
    db.commit()
