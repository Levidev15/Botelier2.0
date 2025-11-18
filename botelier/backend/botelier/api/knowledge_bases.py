"""
Knowledge Bases API - CRUD operations for hotel knowledge bases and Q&A entries.

Endpoints:
- GET /api/knowledge-bases - List hotel's knowledge bases
- POST /api/knowledge-bases - Create new knowledge base
- GET /api/knowledge-bases/{id} - Get knowledge base details
- PUT /api/knowledge-bases/{id} - Update knowledge base
- DELETE /api/knowledge-bases/{id} - Delete knowledge base
- POST /api/knowledge-bases/{id}/entries - Add Q&A entry
- GET /api/knowledge-bases/{id}/entries - List entries (with expired filter)
- GET /api/knowledge-bases/{id}/entries/{entry_id} - Get specific entry
- PUT /api/knowledge-bases/{id}/entries/{entry_id} - Update entry
- DELETE /api/knowledge-bases/{id}/entries/{entry_id} - Delete entry
- POST /api/knowledge-bases/{id}/entries/import-csv - Bulk CSV import
"""

import csv
import io
from datetime import date, datetime
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Query, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from botelier.database import get_db
from botelier.models.knowledge_base import KnowledgeBase
from botelier.models.knowledge_entry import KnowledgeEntry


router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge-bases"])

# Separate router for hotel-wide entry queries
entries_router = APIRouter(prefix="/api/entries", tags=["entries"])


# Pydantic Models

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
    entry_count: int
    created_at: Optional[str]
    updated_at: Optional[str]


class EntryCreate(BaseModel):
    """Request model for creating a Q&A entry."""
    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    category: Optional[str] = Field(None, max_length=100)
    expiration_date: Optional[str] = None  # ISO date string YYYY-MM-DD


class EntryUpdate(BaseModel):
    """Request model for updating a Q&A entry."""
    question: Optional[str] = Field(None, min_length=1)
    answer: Optional[str] = Field(None, min_length=1)
    category: Optional[str] = Field(None, max_length=100)
    expiration_date: Optional[str] = None  # ISO date string YYYY-MM-DD


class EntryResponse(BaseModel):
    """Response model for knowledge entry."""
    id: str
    knowledge_base_id: str
    question: str
    answer: str
    category: Optional[str]
    expiration_date: Optional[str]
    is_expired: bool
    created_at: Optional[str]
    updated_at: Optional[str]


# Knowledge Base Endpoints

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
    - List of knowledge bases with entry counts
    """
    query = db.query(KnowledgeBase)
    
    if hotel_id:
        query = query.filter(KnowledgeBase.hotel_id == hotel_id)
    
    knowledge_bases = query.order_by(KnowledgeBase.created_at.desc()).all()
    
    result = []
    for kb in knowledge_bases:
        entry_count = db.query(KnowledgeEntry).filter(
            KnowledgeEntry.knowledge_base_id == kb.id
        ).count()
        
        kb_dict = kb.to_dict()
        kb_dict["entry_count"] = entry_count
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
    result["entry_count"] = 0
    
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
    - Knowledge base details with entry count
    """
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    entry_count = db.query(KnowledgeEntry).filter(
        KnowledgeEntry.knowledge_base_id == kb.id
    ).count()
    
    result = kb.to_dict()
    result["entry_count"] = entry_count
    
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
    
    entry_count = db.query(KnowledgeEntry).filter(
        KnowledgeEntry.knowledge_base_id == kb.id
    ).count()
    
    result = kb.to_dict()
    result["entry_count"] = entry_count
    
    return result


@router.delete("/{kb_id}", status_code=204)
async def delete_knowledge_base(
    kb_id: str,
    db: Session = Depends(get_db)
):
    """
    Delete a knowledge base and all its entries.
    
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


# Entry Endpoints

@router.post("/{kb_id}/entries", status_code=201)
async def create_entry(
    kb_id: str,
    data: EntryCreate,
    db: Session = Depends(get_db)
):
    """
    Add a Q&A entry to a knowledge base.
    
    Path params:
    - kb_id: Knowledge base UUID
    
    Body:
    - question: The question
    - answer: The answer
    - category: Optional category/tag
    - expiration_date: Optional expiration (YYYY-MM-DD)
    
    Returns:
    - Created entry
    """
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    # Parse expiration date if provided
    exp_date = None
    if data.expiration_date:
        try:
            exp_date = datetime.fromisoformat(data.expiration_date).date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    entry = KnowledgeEntry(
        knowledge_base_id=kb_id,
        question=data.question,
        answer=data.answer,
        category=data.category,
        expiration_date=exp_date
    )
    
    db.add(entry)
    db.commit()
    db.refresh(entry)
    
    return entry.to_dict()


@router.get("/{kb_id}/entries")
async def list_entries(
    kb_id: str,
    include_expired: bool = Query(False, description="Include expired entries"),
    category: Optional[str] = Query(None, description="Filter by category"),
    db: Session = Depends(get_db)
):
    """
    List all entries in a knowledge base.
    
    Path params:
    - kb_id: Knowledge base UUID
    
    Query params:
    - include_expired: Include expired entries (default: false)
    - category: Filter by category
    
    Returns:
    - List of entries
    """
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    query = db.query(KnowledgeEntry).filter(
        KnowledgeEntry.knowledge_base_id == kb_id
    )
    
    # Filter by category if provided
    if category:
        query = query.filter(KnowledgeEntry.category == category)
    
    # Filter expired entries unless explicitly included
    if not include_expired:
        today = date.today()
        query = query.filter(
            (KnowledgeEntry.expiration_date.is_(None)) | 
            (KnowledgeEntry.expiration_date >= today)
        )
    
    entries = query.order_by(KnowledgeEntry.created_at.desc()).all()
    
    return {
        "entries": [entry.to_dict() for entry in entries],
        "total": len(entries)
    }


@router.get("/{kb_id}/entries/{entry_id}")
async def get_entry(
    kb_id: str,
    entry_id: str,
    db: Session = Depends(get_db)
):
    """
    Get a specific entry by ID.
    
    Path params:
    - kb_id: Knowledge base UUID
    - entry_id: Entry UUID
    
    Returns:
    - Entry details
    """
    entry = db.query(KnowledgeEntry).filter(
        KnowledgeEntry.id == entry_id,
        KnowledgeEntry.knowledge_base_id == kb_id
    ).first()
    
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    
    return entry.to_dict()


@router.put("/{kb_id}/entries/{entry_id}")
async def update_entry(
    kb_id: str,
    entry_id: str,
    data: EntryUpdate,
    db: Session = Depends(get_db)
):
    """
    Update a Q&A entry.
    
    Path params:
    - kb_id: Knowledge base UUID
    - entry_id: Entry UUID
    
    Body:
    - question: Optional new question
    - answer: Optional new answer
    - category: Optional new category
    - expiration_date: Optional new expiration (YYYY-MM-DD)
    
    Returns:
    - Updated entry
    """
    entry = db.query(KnowledgeEntry).filter(
        KnowledgeEntry.id == entry_id,
        KnowledgeEntry.knowledge_base_id == kb_id
    ).first()
    
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    
    if data.question is not None:
        entry.question = data.question
    if data.answer is not None:
        entry.answer = data.answer
    if data.category is not None:
        entry.category = data.category
    if data.expiration_date is not None:
        try:
            entry.expiration_date = datetime.fromisoformat(data.expiration_date).date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    db.commit()
    db.refresh(entry)
    
    return entry.to_dict()


@router.delete("/{kb_id}/entries/{entry_id}", status_code=204)
async def delete_entry(
    kb_id: str,
    entry_id: str,
    db: Session = Depends(get_db)
):
    """
    Delete an entry from a knowledge base.
    
    Path params:
    - kb_id: Knowledge base UUID
    - entry_id: Entry UUID
    
    Returns:
    - 204 No Content on success
    """
    entry = db.query(KnowledgeEntry).filter(
        KnowledgeEntry.id == entry_id,
        KnowledgeEntry.knowledge_base_id == kb_id
    ).first()
    
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    
    db.delete(entry)
    db.commit()


@router.post("/{kb_id}/entries/import-csv", status_code=201)
async def import_csv(
    kb_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Bulk import Q&A entries from CSV file.
    
    Path params:
    - kb_id: Knowledge base UUID
    
    File Format:
    - Required columns: question, answer
    - Optional columns: category, expiration_date (YYYY-MM-DD)
    
    Returns:
    - Import summary with counts
    """
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    # Validate file type
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV")
    
    # Read CSV content
    content = await file.read()
    csv_text = content.decode('utf-8')
    csv_reader = csv.DictReader(io.StringIO(csv_text))
    
    # Validate required columns
    if not csv_reader.fieldnames or 'question' not in csv_reader.fieldnames or 'answer' not in csv_reader.fieldnames:
        raise HTTPException(
            status_code=400, 
            detail="CSV must contain 'question' and 'answer' columns"
        )
    
    # Process rows
    created_count = 0
    error_count = 0
    errors = []
    
    for row_num, row in enumerate(csv_reader, start=2):  # Start at 2 (header is row 1)
        try:
            question = row.get('question', '').strip()
            answer = row.get('answer', '').strip()
            
            if not question or not answer:
                error_count += 1
                errors.append(f"Row {row_num}: Missing question or answer")
                continue
            
            # Parse optional fields
            category = row.get('category', '').strip() or None
            
            exp_date = None
            exp_date_str = row.get('expiration_date', '').strip()
            if exp_date_str:
                try:
                    exp_date = datetime.fromisoformat(exp_date_str).date()
                except ValueError:
                    error_count += 1
                    errors.append(f"Row {row_num}: Invalid date format '{exp_date_str}'")
                    continue
            
            # Create entry
            entry = KnowledgeEntry(
                knowledge_base_id=kb_id,
                question=question,
                answer=answer,
                category=category,
                expiration_date=exp_date
            )
            
            db.add(entry)
            created_count += 1
            
        except Exception as e:
            error_count += 1
            errors.append(f"Row {row_num}: {str(e)}")
    
    # Commit all entries
    if created_count > 0:
        db.commit()
    
    return {
        "success": True,
        "created": created_count,
        "errors": error_count,
        "error_details": errors[:10]  # Limit to first 10 errors
    }


# Hotel-Wide Entry Endpoints

@entries_router.get("", response_model=dict)
async def get_all_hotel_entries(
    hotel_id: str = Query(..., description="Hotel UUID"),
    include_expired: bool = Query(False, description="Include expired entries"),
    category: Optional[str] = Query(None, description="Filter by category"),
    db: Session = Depends(get_db)
):
    """
    Get ALL entries for a hotel across all knowledge bases in one query.
    
    This consolidated endpoint prevents N+1 queries from the frontend.
    
    Query params:
    - hotel_id: Hotel UUID (required)
    - include_expired: Include expired entries (default: false)
    - category: Filter by category
    
    Returns:
    - List of all entries with knowledge base names
    """
    # Get all knowledge bases for this hotel
    kbs = db.query(KnowledgeBase).filter(KnowledgeBase.hotel_id == hotel_id).all()
    
    if not kbs:
        return {"entries": [], "total": 0}
    
    kb_ids = [kb.id for kb in kbs]
    kb_map = {kb.id: kb.name for kb in kbs}
    
    # Build query for entries
    query = db.query(KnowledgeEntry).filter(
        KnowledgeEntry.knowledge_base_id.in_(kb_ids)
    )
    
    # Filter by category if provided
    if category:
        query = query.filter(KnowledgeEntry.category == category)
    
    # Filter expired entries unless explicitly included
    if not include_expired:
        today = date.today()
        query = query.filter(
            (KnowledgeEntry.expiration_date.is_(None)) | 
            (KnowledgeEntry.expiration_date >= today)
        )
    
    entries = query.order_by(KnowledgeEntry.created_at.desc()).all()
    
    # Add KB name to each entry
    result = []
    for entry in entries:
        entry_dict = entry.to_dict()
        entry_dict["knowledge_base_name"] = kb_map.get(entry.knowledge_base_id, "Unknown")
        result.append(entry_dict)
    
    return {
        "entries": result,
        "total": len(result)
    }
