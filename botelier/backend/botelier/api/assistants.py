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


class AssistantCreate(BaseModel):
    """Assistant creation model."""
    hotel_id: str
    name: str
    description: Optional[str] = None
    stt_provider: str = "deepgram"
    llm_provider: str = "openai"
    tts_provider: str = "cartesia"
    stt_model: Optional[str] = None
    llm_model: str = "gpt-4o-mini"
    tts_model: Optional[str] = None
    tts_voice: Optional[str] = None
    system_prompt: str = "You are a helpful hotel assistant."
    first_message: Optional[str] = None
    language: str = "en"
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None
    stt_config: Optional[dict] = None
    llm_config: Optional[dict] = None
    tts_config: Optional[dict] = None
    is_active: bool = True


class AssistantUpdate(BaseModel):
    """Assistant update model."""
    name: Optional[str] = None
    description: Optional[str] = None
    stt_provider: Optional[str] = None
    llm_provider: Optional[str] = None
    tts_provider: Optional[str] = None
    stt_model: Optional[str] = None
    llm_model: Optional[str] = None
    tts_model: Optional[str] = None
    tts_voice: Optional[str] = None
    system_prompt: Optional[str] = None
    first_message: Optional[str] = None
    language: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    stt_config: Optional[dict] = None
    llm_config: Optional[dict] = None
    tts_config: Optional[dict] = None
    is_active: Optional[bool] = None


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
    tts_model: Optional[str]
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


@router.post("", response_model=AssistantResponse, status_code=201)
async def create_assistant(
    data: AssistantCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new assistant.
    
    Body:
    - Assistant creation data
    
    Returns:
    - Created assistant details
    """
    assistant = Assistant(
        hotel_id=data.hotel_id,
        name=data.name,
        description=data.description,
        stt_provider=data.stt_provider,
        llm_provider=data.llm_provider,
        tts_provider=data.tts_provider,
        stt_model=data.stt_model,
        llm_model=data.llm_model,
        tts_model=data.tts_model,
        tts_voice=data.tts_voice,
        system_prompt=data.system_prompt,
        first_message=data.first_message,
        language=data.language,
        temperature=data.temperature,
        max_tokens=data.max_tokens,
        stt_config=data.stt_config or {},
        llm_config=data.llm_config or {},
        tts_config=data.tts_config or {},
        is_active=data.is_active,
    )
    
    db.add(assistant)
    db.commit()
    db.refresh(assistant)
    
    return assistant.to_dict()


@router.put("/{assistant_id}", response_model=AssistantResponse)
async def update_assistant(
    assistant_id: str,
    data: AssistantUpdate,
    db: Session = Depends(get_db)
):
    """
    Update an existing assistant.
    
    Path params:
    - assistant_id: Assistant UUID
    
    Body:
    - Assistant update data
    
    Returns:
    - Updated assistant details
    """
    assistant = db.query(Assistant).filter(Assistant.id == assistant_id).first()
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    
    # Update only fields that are provided
    update_data = data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(assistant, field, value)
    
    db.commit()
    db.refresh(assistant)
    
    return assistant.to_dict()
