"""
Assistants API - CRUD operations for voice AI assistants.

Endpoints:
- GET /api/assistants - List hotel's assistants
- POST /api/assistants - Create new assistant
- GET /api/assistants/{id} - Get assistant details
- PUT /api/assistants/{id} - Update assistant
- DELETE /api/assistants/{id} - Delete assistant
"""

from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from uuid import UUID

from botelier.database import get_db
from botelier.models.assistant import Assistant


router = APIRouter(prefix="/api/assistants", tags=["assistants"])


class AssistantResponse(BaseModel):
    """Assistant response model."""
    id: str
    hotel_id: str
    name: str
    description: Optional[str]
    stt_provider: str
    llm_provider: str
    tts_provider: str
    stt_model: Optional[str]
    llm_model: str
    tts_voice: Optional[str]
    system_prompt: str
    first_message: Optional[str]
    language: str
    temperature: Optional[str]
    max_tokens: Optional[str]
    is_active: bool
    created_at: Optional[str]
    updated_at: Optional[str]


@router.get("", response_model=dict)
async def list_assistants(
    hotel_id: Optional[str] = Query(None, description="Filter by hotel ID"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    db: Session = Depends(get_db)
):
    """
    List all assistants, optionally filtered by hotel or status.
    
    Query params:
    - hotel_id: Filter by hotel UUID
    - is_active: Filter by active status
    
    Returns:
    - List of assistants
    """
    query = db.query(Assistant)
    
    if hotel_id:
        query = query.filter(Assistant.hotel_id == hotel_id)
    
    if is_active is not None:
        query = query.filter(Assistant.is_active == is_active)
    
    assistants = query.order_by(Assistant.created_at.desc()).all()
    
    return {
        "assistants": [assistant.to_dict() for assistant in assistants],
        "total": len(assistants)
    }


@router.get("/{assistant_id}", response_model=AssistantResponse)
async def get_assistant(
    assistant_id: str,
    db: Session = Depends(get_db)
):
    """
    Get a specific assistant by ID.
    
    Path params:
    - assistant_id: Assistant UUID
    
    Returns:
    - Assistant details
    """
    assistant = db.query(Assistant).filter(Assistant.id == assistant_id).first()
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    
    return assistant.to_dict()
