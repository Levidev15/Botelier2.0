"""
Knowledge Entries API - CRUD operations for hotel Q&A entries.

Simplified architecture: Entries belong directly to hotels (no knowledge_base grouping).

Endpoints:
- POST /api/entries - Create new Q&A entry
- GET /api/entries - List all hotel entries (consolidated endpoint)
- GET /api/entries/{entry_id} - Get specific entry
- PUT /api/entries/{entry_id} - Update entry
- DELETE /api/entries/{entry_id} - Delete entry
- DELETE /api/entries/bulk - Bulk delete entries
- PUT /api/entries/bulk - Bulk update entries
- POST /api/entries/import-csv - Bulk CSV import
"""

import csv
import io
from datetime import date, datetime
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Query, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from botelier.database import get_db
from botelier.models.knowledge_entry import KnowledgeEntry


router = APIRouter(prefix="/api/entries", tags=["entries"])


# Pydantic Models

class EntryCreate(BaseModel):
    """Request model for creating a Q&A entry."""
    hotel_id: str
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


class BulkDeleteRequest(BaseModel):
    """Request model for bulk delete."""
    entry_ids: List[str] = Field(..., min_items=1)


class BulkUpdateRequest(BaseModel):
    """Request model for bulk update."""
    entry_ids: List[str] = Field(..., min_items=1)
    category: Optional[str] = None


class EntryResponse(BaseModel):
    """Response model for knowledge entry."""
    id: str
    hotel_id: str
    question: str
    answer: str
    category: Optional[str]
    expiration_date: Optional[str]
    is_expired: bool
    created_at: Optional[str]
    updated_at: Optional[str]


# Entry Endpoints

@router.post("", status_code=201)
async def create_entry(
    data: EntryCreate,
    db: Session = Depends(get_db)
):
    """
    Create a Q&A entry for a hotel.
    
    Body:
    - hotel_id: UUID of the hotel
    - question: The question
    - answer: The answer
    - category: Optional category/tag
    - expiration_date: Optional expiration (YYYY-MM-DD)
    
    Returns:
    - Created entry
    """
    # Parse expiration date if provided
    exp_date = None
    if data.expiration_date:
        try:
            exp_date = datetime.fromisoformat(data.expiration_date).date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    entry = KnowledgeEntry(
        hotel_id=data.hotel_id,
        question=data.question,
        answer=data.answer,
        category=data.category,
        expiration_date=exp_date
    )
    
    db.add(entry)
    db.commit()
    db.refresh(entry)
    
    return entry.to_dict()


@router.get("", response_model=dict)
async def list_entries(
    hotel_id: str = Query(..., description="Hotel UUID"),
    include_expired: bool = Query(False, description="Include expired entries"),
    category: Optional[str] = Query(None, description="Filter by category"),
    db: Session = Depends(get_db)
):
    """
    List all Q&A entries for a hotel.
    
    Query params:
    - hotel_id: Hotel UUID (required)
    - include_expired: Include expired entries (default: false)
    - category: Filter by category
    
    Returns:
    - List of all entries
    """
    query = db.query(KnowledgeEntry).filter(KnowledgeEntry.hotel_id == hotel_id)
    
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


@router.delete("/bulk", status_code=200)
async def bulk_delete_entries(
    data: BulkDeleteRequest,
    db: Session = Depends(get_db)
):
    """
    Bulk delete multiple entries.
    
    Body:
    - entry_ids: List of entry UUIDs to delete
    
    Returns:
    - Count of deleted entries
    """
    deleted_count = db.query(KnowledgeEntry).filter(
        KnowledgeEntry.id.in_(data.entry_ids)
    ).delete(synchronize_session=False)
    
    db.commit()
    
    return {
        "success": True,
        "deleted": deleted_count
    }


@router.put("/bulk", status_code=200)
async def bulk_update_entries(
    data: BulkUpdateRequest,
    db: Session = Depends(get_db)
):
    """
    Bulk update category for multiple entries.
    
    Body:
    - entry_ids: List of entry UUIDs to update
    - category: New category to set (or null to clear)
    
    Returns:
    - Count of updated entries
    """
    updated_count = db.query(KnowledgeEntry).filter(
        KnowledgeEntry.id.in_(data.entry_ids)
    ).update(
        {"category": data.category},
        synchronize_session=False
    )
    
    db.commit()
    
    return {
        "success": True,
        "updated": updated_count
    }


@router.get("/{entry_id}")
async def get_entry(
    entry_id: str,
    db: Session = Depends(get_db)
):
    """
    Get a specific entry by ID.
    
    Path params:
    - entry_id: Entry UUID
    
    Returns:
    - Entry details
    """
    entry = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
    
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    
    return entry.to_dict()


@router.put("/{entry_id}")
async def update_entry(
    entry_id: str,
    data: EntryUpdate,
    db: Session = Depends(get_db)
):
    """
    Update a Q&A entry.
    
    Path params:
    - entry_id: Entry UUID
    
    Body:
    - question: Optional new question
    - answer: Optional new answer
    - category: Optional new category
    - expiration_date: Optional new expiration (YYYY-MM-DD)
    
    Returns:
    - Updated entry
    """
    entry = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
    
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


@router.delete("/{entry_id}", status_code=204)
async def delete_entry(
    entry_id: str,
    db: Session = Depends(get_db)
):
    """
    Delete a Q&A entry.
    
    Path params:
    - entry_id: Entry UUID
    
    Returns:
    - 204 No Content on success
    """
    entry = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
    
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    
    db.delete(entry)
    db.commit()


@router.post("/import-csv", status_code=201)
async def import_csv(
    hotel_id: str = Query(..., description="Hotel UUID"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Bulk import Q&A entries from CSV file.
    
    Query params:
    - hotel_id: Hotel UUID
    
    File Format:
    - Required columns: question, answer
    - Optional columns: category, expiration_date (YYYY-MM-DD)
    
    Returns:
    - Import summary with counts
    """
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
                hotel_id=hotel_id,
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
