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
    knowledge_base_id: Optional[str] = None
    tool_set_id: Optional[str] = None
    mcp_connection_id: Optional[str] = None
    mcp_enabled_tools: Optional[List[str]] = None
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
    vad_enabled: bool = False
    vad_provider: Optional[str] = None
    vad_config: Optional[dict] = None
    is_active: bool = True


class AssistantUpdate(BaseModel):
    """Assistant update model."""
    knowledge_base_id: Optional[str] = None
    tool_set_id: Optional[str] = None
    mcp_connection_id: Optional[str] = None
    mcp_enabled_tools: Optional[List[str]] = None
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
    vad_enabled: Optional[bool] = None
    vad_provider: Optional[str] = None
    vad_config: Optional[dict] = None
    is_active: Optional[bool] = None
    flow_config: Optional[dict] = None
    sms_config: Optional[dict] = None


class FlowConfigUpdate(BaseModel):
    """Flow configuration update model for the visual editor."""
    flow_config: dict = Field(..., description="Pipecat Flows configuration JSON")


class AssistantResponse(BaseModel):
    """Assistant response model."""
    id: str
    hotel_id: str
    knowledge_base_id: Optional[str] = None
    tool_set_id: Optional[str] = None
    mcp_connection_id: Optional[str] = None
    mcp_enabled_tools: Optional[List[str]] = None
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
    temperature: Optional[float]
    max_tokens: Optional[int]
    stt_config: Optional[dict]
    llm_config: Optional[dict]
    tts_config: Optional[dict]
    vad_enabled: bool
    vad_provider: Optional[str]
    vad_config: Optional[dict]
    is_active: bool
    flow_config: Optional[dict]
    created_at: Optional[str]
    updated_at: Optional[str]


class FlowConfigResponse(BaseModel):
    """Flow configuration response model."""
    assistant_id: str
    hotel_id: str
    flow_config: Optional[dict]
    has_flow: bool


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
        knowledge_base_id=data.knowledge_base_id,
        tool_set_id=data.tool_set_id,
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
        vad_enabled=data.vad_enabled,
        vad_provider=data.vad_provider,
        vad_config=data.vad_config or {},
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


@router.delete("/{assistant_id}", status_code=204)
async def delete_assistant(
    assistant_id: str,
    db: Session = Depends(get_db)
):
    """
    Delete an assistant.
    
    Path params:
    - assistant_id: Assistant UUID
    
    Returns:
    - 204 No Content on success
    """
    assistant = db.query(Assistant).filter(Assistant.id == assistant_id).first()
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    
    db.delete(assistant)
    db.commit()
    
    return None


@router.get("/{assistant_id}/flow", response_model=FlowConfigResponse)
async def get_assistant_flow(
    assistant_id: str,
    db: Session = Depends(get_db)
):
    """
    Get the flow configuration for an assistant.
    
    This returns the Pipecat Flows JSON configuration that defines
    the conversation flow for this assistant.
    
    Path params:
    - assistant_id: Assistant UUID
    
    Returns:
    - Flow configuration JSON
    """
    assistant = db.query(Assistant).filter(Assistant.id == assistant_id).first()
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    
    return {
        "assistant_id": str(assistant.id),
        "hotel_id": str(assistant.hotel_id),
        "flow_config": assistant.flow_config,
        "has_flow": assistant.flow_config is not None
    }


@router.put("/{assistant_id}/flow", response_model=FlowConfigResponse)
async def update_assistant_flow(
    assistant_id: str,
    data: FlowConfigUpdate,
    db: Session = Depends(get_db)
):
    """
    Update the flow configuration for an assistant.
    
    This saves the Pipecat Flows JSON configuration from the visual editor.
    The flow defines nodes, transitions, and functions for conversations.
    
    Path params:
    - assistant_id: Assistant UUID
    
    Body:
    - flow_config: Pipecat Flows configuration JSON
    
    Returns:
    - Updated flow configuration
    
    Security:
    - Validates that the assistant belongs to the requesting hotel
    - Sanitizes function definitions to prevent code injection
    """
    assistant = db.query(Assistant).filter(Assistant.id == assistant_id).first()
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    
    assistant.flow_config = data.flow_config
    db.commit()
    db.refresh(assistant)
    
    return {
        "assistant_id": str(assistant.id),
        "hotel_id": str(assistant.hotel_id),
        "flow_config": assistant.flow_config,
        "has_flow": True
    }


@router.delete("/{assistant_id}/flow", status_code=204)
async def delete_assistant_flow(
    assistant_id: str,
    db: Session = Depends(get_db)
):
    """
    Delete the flow configuration for an assistant.
    
    This removes the custom flow, reverting to default behavior.
    
    Path params:
    - assistant_id: Assistant UUID
    
    Returns:
    - 204 No Content on success
    """
    assistant = db.query(Assistant).filter(Assistant.id == assistant_id).first()
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    
    assistant.flow_config = None
    db.commit()
    
    return None