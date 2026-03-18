"""
Knowledge Bases API - CRUD operations for knowledge base collections and their entries.

Architecture:
- Knowledge Bases are named collections belonging to an account
- Each Knowledge Base contains multiple Q&A entries
- Knowledge Bases can be assigned to assistants

Endpoints:
Knowledge Bases:
- POST /api/knowledge-bases - Create new knowledge base
- GET /api/knowledge-bases - List all knowledge bases for account
- GET /api/knowledge-bases/{kb_id} - Get knowledge base details
- PUT /api/knowledge-bases/{kb_id} - Update knowledge base
- DELETE /api/knowledge-bases/{kb_id} - Delete knowledge base (and all entries)

Entries within a Knowledge Base:
- POST /api/knowledge-bases/{kb_id}/entries - Create entry
- GET /api/knowledge-bases/{kb_id}/entries - List entries
- GET /api/knowledge-bases/{kb_id}/entries/{entry_id} - Get entry
- PUT /api/knowledge-bases/{kb_id}/entries/{entry_id} - Update entry
- DELETE /api/knowledge-bases/{kb_id}/entries/{entry_id} - Delete entry
- DELETE /api/knowledge-bases/{kb_id}/entries/bulk - Bulk delete
- POST /api/knowledge-bases/{kb_id}/entries/import-csv - Import from CSV
- GET /api/knowledge-bases/{kb_id}/entries/export-csv - Export to CSV
"""

import csv
import io
from datetime import date, datetime
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func

from botelier.database import get_db
from botelier.models.knowledge_base import KnowledgeBase
from botelier.models.knowledge_entry import KnowledgeEntry
from botelier.models.user import User
from botelier.auth.middleware import get_current_user, check_account_permission


router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge-bases"])


def _get_kb_and_check(kb_id: str, permission: str, user: User, db: Session) -> KnowledgeBase:
    """Fetch a knowledge base and verify the user has the given permission on its account."""
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    check_account_permission(user, str(kb.account_id), permission, db)
    return kb


# Pydantic Models - Knowledge Bases

class KnowledgeBaseCreate(BaseModel):
    """Request model for creating a knowledge base."""
    account_id: str
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class KnowledgeBaseUpdate(BaseModel):
    """Request model for updating a knowledge base."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None


# Pydantic Models - Entries

class EntryCreate(BaseModel):
    """Request model for creating a Q&A entry."""
    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    category: Optional[str] = Field(None, max_length=100)
    expiration_date: Optional[str] = None


class EntryUpdate(BaseModel):
    """Request model for updating a Q&A entry."""
    question: Optional[str] = Field(None, min_length=1)
    answer: Optional[str] = Field(None, min_length=1)
    category: Optional[str] = Field(None, max_length=100)
    expiration_date: Optional[str] = None


class BulkDeleteRequest(BaseModel):
    """Request model for bulk delete."""
    entry_ids: List[str] = Field(..., min_length=1)


# ============================================================
# Knowledge Base Endpoints
# ============================================================

@router.post("", status_code=201)
async def create_knowledge_base(
    data: KnowledgeBaseCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new knowledge base."""
    check_account_permission(user, data.account_id, "knowledge_base.create", db)
    kb = KnowledgeBase(
        account_id=data.account_id,
        name=data.name,
        description=data.description
    )
    
    db.add(kb)
    db.commit()
    db.refresh(kb)
    
    return kb.to_dict()


@router.get("")
async def list_knowledge_bases(
    account_id: str = Query(..., description="Account UUID"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all knowledge bases for an account with entry counts."""
    check_account_permission(user, account_id, "knowledge_base.view", db)
    kbs = db.query(KnowledgeBase).filter(
        KnowledgeBase.account_id == account_id
    ).order_by(KnowledgeBase.created_at.desc()).all()
    
    return {
        "knowledge_bases": [kb.to_dict() for kb in kbs],
        "total": len(kbs)
    }


@router.get("/{kb_id}")
async def get_knowledge_base(
    kb_id: str,
    include_entries: bool = Query(False, description="Include all entries"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a specific knowledge base by ID."""
    kb = _get_kb_and_check(kb_id, "knowledge_base.view", user, db)
    return kb.to_dict(include_entries=include_entries)


@router.put("/{kb_id}")
async def update_knowledge_base(
    kb_id: str,
    data: KnowledgeBaseUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update a knowledge base."""
    kb = _get_kb_and_check(kb_id, "knowledge_base.edit", user, db)

    if data.name is not None:
        kb.name = data.name
    if data.description is not None:
        kb.description = data.description
    
    db.commit()
    db.refresh(kb)
    
    return kb.to_dict()


@router.delete("/{kb_id}", status_code=204)
async def delete_knowledge_base(
    kb_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a knowledge base and all its entries."""
    kb = _get_kb_and_check(kb_id, "knowledge_base.delete", user, db)
    db.delete(kb)
    db.commit()


# ============================================================
# Entry Endpoints (within a Knowledge Base)
# ============================================================

@router.post("/{kb_id}/entries", status_code=201)
async def create_entry(
    kb_id: str,
    data: EntryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a Q&A entry in a knowledge base."""
    kb = _get_kb_and_check(kb_id, "knowledge_base.create", user, db)
    
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all entries in a knowledge base."""
    kb = _get_kb_and_check(kb_id, "knowledge_base.view", user, db)
    
    query = db.query(KnowledgeEntry).filter(KnowledgeEntry.knowledge_base_id == kb_id)
    
    if category:
        query = query.filter(KnowledgeEntry.category == category)
    
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


@router.get("/{kb_id}/entries/export-csv")
async def export_entries_csv(
    kb_id: str,
    include_expired: bool = Query(True, description="Include expired entries"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Export all entries to CSV file."""
    kb = _get_kb_and_check(kb_id, "knowledge_base.view", user, db)
    
    query = db.query(KnowledgeEntry).filter(KnowledgeEntry.knowledge_base_id == kb_id)
    
    if not include_expired:
        today = date.today()
        query = query.filter(
            (KnowledgeEntry.expiration_date.is_(None)) | 
            (KnowledgeEntry.expiration_date >= today)
        )
    
    entries = query.order_by(KnowledgeEntry.created_at.desc()).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["question", "answer", "category", "expiration_date", "created_at"])
    
    for entry in entries:
        writer.writerow([
            entry.question,
            entry.answer,
            entry.category or "",
            entry.expiration_date.isoformat() if entry.expiration_date else "",
            entry.created_at.isoformat() if entry.created_at else ""
        ])
    
    output.seek(0)
    filename = f"{kb.name.replace(' ', '_')}_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.delete("/{kb_id}/entries/bulk", status_code=200)
async def bulk_delete_entries(
    kb_id: str,
    data: BulkDeleteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bulk delete entries."""
    _get_kb_and_check(kb_id, "knowledge_base.delete", user, db)
    deleted_count = db.query(KnowledgeEntry).filter(
        KnowledgeEntry.knowledge_base_id == kb_id,
        KnowledgeEntry.id.in_(data.entry_ids)
    ).delete(synchronize_session=False)
    
    db.commit()
    
    return {"success": True, "deleted": deleted_count}


@router.get("/{kb_id}/entries/{entry_id}")
async def get_entry(
    kb_id: str,
    entry_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a specific entry."""
    _get_kb_and_check(kb_id, "knowledge_base.view", user, db)
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update a Q&A entry."""
    _get_kb_and_check(kb_id, "knowledge_base.edit", user, db)
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a Q&A entry."""
    _get_kb_and_check(kb_id, "knowledge_base.delete", user, db)
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bulk import Q&A entries from CSV file."""
    kb = _get_kb_and_check(kb_id, "knowledge_base.import", user, db)
    
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV")
    
    content = await file.read()
    csv_text = content.decode('utf-8')
    csv_reader = csv.DictReader(io.StringIO(csv_text))
    
    if not csv_reader.fieldnames or 'question' not in csv_reader.fieldnames or 'answer' not in csv_reader.fieldnames:
        raise HTTPException(
            status_code=400, 
            detail="CSV must contain 'question' and 'answer' columns"
        )
    
    created_count = 0
    error_count = 0
    errors = []
    
    for row_num, row in enumerate(csv_reader, start=2):
        try:
            question = row.get('question', '').strip()
            answer = row.get('answer', '').strip()
            
            if not question or not answer:
                error_count += 1
                errors.append(f"Row {row_num}: Missing question or answer")
                continue
            
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
    
    if created_count > 0:
        db.commit()
    
    return {
        "success": True,
        "created": created_count,
        "errors": error_count,
        "error_details": errors[:10]
    }


# ============================================================
# Legacy Endpoints (for backward compatibility during migration)
# TODO: Remove after frontend migration complete
# ============================================================

legacy_router = APIRouter(prefix="/api/entries", tags=["entries-legacy"])


@legacy_router.get("")
async def legacy_list_entries(
    hotel_id: str = Query(None, description="Hotel UUID (legacy)"),
    knowledge_base_id: str = Query(None, description="Knowledge Base UUID"),
    include_expired: bool = Query(False),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Legacy endpoint - list entries by hotel_id or knowledge_base_id."""
    if knowledge_base_id:
        query = db.query(KnowledgeEntry).filter(
            KnowledgeEntry.knowledge_base_id == knowledge_base_id
        )
    elif hotel_id:
        query = db.query(KnowledgeEntry).filter(
            KnowledgeEntry.hotel_id == hotel_id
        )
    else:
        raise HTTPException(status_code=400, detail="Either hotel_id or knowledge_base_id required")
    
    if category:
        query = query.filter(KnowledgeEntry.category == category)
    
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
