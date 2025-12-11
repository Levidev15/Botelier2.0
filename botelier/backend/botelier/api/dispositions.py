"""
Dispositions API - CRUD endpoints for assistant call dispositions.
"""

from typing import List, Optional
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from loguru import logger

from ..database import get_db
from ..models import AssistantDisposition, Assistant


router = APIRouter(prefix="/api/assistants", tags=["Dispositions"])


class DispositionCreate(BaseModel):
    name: str
    description: Optional[str] = None
    color: Optional[str] = "#6366f1"
    display_order: Optional[int] = 0
    is_active: Optional[bool] = True


class DispositionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class DispositionReorder(BaseModel):
    disposition_ids: List[str]


@router.get("/{assistant_id}/dispositions")
async def list_dispositions(
    assistant_id: UUID,
    hotel_id: UUID = Query(..., description="Hotel ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
):
    """List all dispositions for an assistant."""
    assistant = db.query(Assistant).filter(
        Assistant.id == assistant_id,
        Assistant.hotel_id == hotel_id
    ).first()
    
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    
    dispositions = db.query(AssistantDisposition).filter(
        AssistantDisposition.assistant_id == assistant_id
    ).order_by(AssistantDisposition.display_order, AssistantDisposition.created_at).all()
    
    return [d.to_dict() for d in dispositions]


@router.post("/{assistant_id}/dispositions", status_code=status.HTTP_201_CREATED)
async def create_disposition(
    assistant_id: UUID,
    data: DispositionCreate,
    hotel_id: UUID = Query(..., description="Hotel ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
):
    """Create a new disposition for an assistant."""
    assistant = db.query(Assistant).filter(
        Assistant.id == assistant_id,
        Assistant.hotel_id == hotel_id
    ).first()
    
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    
    max_order = db.query(AssistantDisposition).filter(
        AssistantDisposition.assistant_id == assistant_id
    ).count()
    
    disposition = AssistantDisposition(
        assistant_id=assistant_id,
        name=data.name,
        description=data.description,
        color=data.color,
        display_order=data.display_order if data.display_order else max_order,
        is_active=data.is_active,
    )
    
    db.add(disposition)
    db.commit()
    db.refresh(disposition)
    
    logger.info(f"Created disposition '{data.name}' for assistant {assistant_id}")
    return disposition.to_dict()


@router.get("/{assistant_id}/dispositions/{disposition_id}")
async def get_disposition(
    assistant_id: UUID,
    disposition_id: UUID,
    hotel_id: UUID = Query(..., description="Hotel ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
):
    """Get a specific disposition."""
    assistant = db.query(Assistant).filter(
        Assistant.id == assistant_id,
        Assistant.hotel_id == hotel_id
    ).first()
    
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    
    disposition = db.query(AssistantDisposition).filter(
        AssistantDisposition.id == disposition_id,
        AssistantDisposition.assistant_id == assistant_id
    ).first()
    
    if not disposition:
        raise HTTPException(status_code=404, detail="Disposition not found")
    
    return disposition.to_dict()


@router.patch("/{assistant_id}/dispositions/{disposition_id}")
async def update_disposition(
    assistant_id: UUID,
    disposition_id: UUID,
    data: DispositionUpdate,
    hotel_id: UUID = Query(..., description="Hotel ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
):
    """Update a disposition."""
    assistant = db.query(Assistant).filter(
        Assistant.id == assistant_id,
        Assistant.hotel_id == hotel_id
    ).first()
    
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    
    disposition = db.query(AssistantDisposition).filter(
        AssistantDisposition.id == disposition_id,
        AssistantDisposition.assistant_id == assistant_id
    ).first()
    
    if not disposition:
        raise HTTPException(status_code=404, detail="Disposition not found")
    
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(disposition, key, value)
    
    disposition.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(disposition)
    
    logger.info(f"Updated disposition {disposition_id}")
    return disposition.to_dict()


@router.delete("/{assistant_id}/dispositions/{disposition_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_disposition(
    assistant_id: UUID,
    disposition_id: UUID,
    hotel_id: UUID = Query(..., description="Hotel ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
):
    """Delete a disposition."""
    assistant = db.query(Assistant).filter(
        Assistant.id == assistant_id,
        Assistant.hotel_id == hotel_id
    ).first()
    
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    
    disposition = db.query(AssistantDisposition).filter(
        AssistantDisposition.id == disposition_id,
        AssistantDisposition.assistant_id == assistant_id
    ).first()
    
    if not disposition:
        raise HTTPException(status_code=404, detail="Disposition not found")
    
    db.delete(disposition)
    db.commit()
    
    logger.info(f"Deleted disposition {disposition_id}")
    return None


@router.post("/{assistant_id}/dispositions/reorder")
async def reorder_dispositions(
    assistant_id: UUID,
    data: DispositionReorder,
    hotel_id: UUID = Query(..., description="Hotel ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
):
    """Reorder dispositions by providing ordered list of IDs."""
    assistant = db.query(Assistant).filter(
        Assistant.id == assistant_id,
        Assistant.hotel_id == hotel_id
    ).first()
    
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    
    for idx, disp_id in enumerate(data.disposition_ids):
        disposition = db.query(AssistantDisposition).filter(
            AssistantDisposition.id == disp_id,
            AssistantDisposition.assistant_id == assistant_id
        ).first()
        if disposition:
            disposition.display_order = idx
    
    db.commit()
    
    dispositions = db.query(AssistantDisposition).filter(
        AssistantDisposition.assistant_id == assistant_id
    ).order_by(AssistantDisposition.display_order).all()
    
    return [d.to_dict() for d in dispositions]
