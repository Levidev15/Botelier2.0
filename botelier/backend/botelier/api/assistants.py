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
from botelier.models.user import User
from botelier.auth.middleware import get_current_user, check_account_permission, get_hotel_context, AccountContext
from botelier.models.user import UserType


router = APIRouter(prefix="/api/assistants", tags=["assistants"])


class AssistantCreate(BaseModel):
    """Assistant creation model."""
    account_id: str
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
    call_settings: Optional[dict] = None


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
    call_settings: Optional[dict] = None


class FlowConfigUpdate(BaseModel):
    """Flow configuration update model for the visual editor."""
    flow_config: dict = Field(..., description="Pipecat Flows configuration JSON")


class AssistantResponse(BaseModel):
    """Assistant response model."""
    id: str
    account_id: str
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
    sms_config: Optional[dict] = None
    call_settings: Optional[dict] = None
    created_at: Optional[str]
    updated_at: Optional[str]


class FlowConfigResponse(BaseModel):
    """Flow configuration response model."""
    assistant_id: str
    account_id: str
    flow_config: Optional[dict]
    has_flow: bool


@router.get("", response_model=dict)
async def list_assistants(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    ctx: AccountContext = Depends(get_hotel_context("assistants.view")),
    db: Session = Depends(get_db),
):
    """List all assistants for the authenticated account."""
    account_id = str(ctx.account.id)

    query = db.query(Assistant).filter(Assistant.account_id == account_id)
    
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a specific assistant by ID."""
    assistant = db.query(Assistant).filter(Assistant.id == assistant_id).first()
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    check_account_permission(user, str(assistant.account_id), "assistants.view", db)
    return assistant.to_dict()


@router.post("", response_model=AssistantResponse, status_code=201)
async def create_assistant(
    data: AssistantCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new assistant."""
    check_account_permission(user, data.account_id, "assistants.create", db)
    assistant = Assistant(
        account_id=data.account_id,
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
        call_settings=data.call_settings or {},
    )
    
    db.add(assistant)
    db.commit()
    db.refresh(assistant)
    
    return assistant.to_dict()


@router.put("/{assistant_id}", response_model=AssistantResponse)
async def update_assistant(
    assistant_id: str,
    data: AssistantUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update an existing assistant."""
    assistant = db.query(Assistant).filter(Assistant.id == assistant_id).first()
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    check_account_permission(user, str(assistant.account_id), "assistants.edit", db)

    # Update only fields that are provided
    update_data = data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(assistant, field, value)

    db.commit()
    db.refresh(assistant)

    # Recording is handled per-call via the in-call Recordings REST API
    # (start_in_call_recording in call_handler.py). No phone-number-level
    # VoiceRecord sync needed when the setting changes.

    return assistant.to_dict()


@router.delete("/{assistant_id}", status_code=204)
async def delete_assistant(
    assistant_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete an assistant."""
    assistant = db.query(Assistant).filter(Assistant.id == assistant_id).first()
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    check_account_permission(user, str(assistant.account_id), "assistants.delete", db)
    
    db.delete(assistant)
    db.commit()
    
    return None


@router.get("/{assistant_id}/flow", response_model=FlowConfigResponse)
async def get_assistant_flow(
    assistant_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get the flow configuration for an assistant."""
    assistant = db.query(Assistant).filter(Assistant.id == assistant_id).first()
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    check_account_permission(user, str(assistant.account_id), "flows.view", db)
    
    return {
        "assistant_id": str(assistant.id),
        "account_id": str(assistant.account_id),
        "flow_config": assistant.flow_config,
        "has_flow": assistant.flow_config is not None
    }


@router.put("/{assistant_id}/flow", response_model=FlowConfigResponse)
async def update_assistant_flow(
    assistant_id: str,
    data: FlowConfigUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update the flow configuration for an assistant."""
    assistant = db.query(Assistant).filter(Assistant.id == assistant_id).first()
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    check_account_permission(user, str(assistant.account_id), "flows.edit", db)
    
    assistant.flow_config = data.flow_config
    db.commit()
    db.refresh(assistant)
    
    return {
        "assistant_id": str(assistant.id),
        "account_id": str(assistant.account_id),
        "flow_config": assistant.flow_config,
        "has_flow": True
    }


@router.delete("/{assistant_id}/flow", status_code=204)
async def delete_assistant_flow(
    assistant_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete the flow configuration for an assistant."""
    assistant = db.query(Assistant).filter(Assistant.id == assistant_id).first()
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    check_account_permission(user, str(assistant.account_id), "flows.edit", db)
    
    assistant.flow_config = None
    db.commit()
    
    return None


@router.get("/{assistant_id}/acw-config")
async def get_acw_config(
    assistant_id: str,
    account_id: str = Query(..., description="Account ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, account_id, "assistants.view", db)
    assistant = db.query(Assistant).filter(
        Assistant.id == assistant_id,
        Assistant.account_id == account_id
    ).first()
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")

    return assistant.acw_config or {}


class AcwConfigUpdate(BaseModel):
    auto_run: Optional[bool] = None
    quality_rubric: Optional[str] = None
    summary_enabled: Optional[bool] = None
    summary_prompt: Optional[str] = None
    llm_model: Optional[str] = None


@router.patch("/{assistant_id}/acw-config")
async def update_acw_config(
    assistant_id: str,
    updates: AcwConfigUpdate,
    account_id: str = Query(..., description="Account ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, account_id, "assistants.edit", db)
    assistant = db.query(Assistant).filter(
        Assistant.id == assistant_id,
        Assistant.account_id == account_id
    ).first()
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")

    filtered = updates.model_dump(exclude_unset=True)

    if not filtered:
        raise HTTPException(status_code=400, detail="No valid fields provided")

    current = dict(assistant.acw_config or {})
    current.update(filtered)
    assistant.acw_config = current
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(assistant, "acw_config")
    db.commit()
    db.refresh(assistant)
    return assistant.acw_config


@router.get("/{assistant_id}/greeting-cache-status")
async def get_greeting_cache_status(
    assistant_id: str,
    account_id: str = Query(..., description="Account ID for multi-tenant isolation"),
    greeting_text: Optional[str] = Query(None, description="Override greeting text; defaults to assistant.first_message"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return whether the greeting audio is currently cached for this assistant.

    An optional ``greeting_text`` query parameter allows callers such as the flow
    editor (where the initial-node greeting may differ from ``first_message``) to
    check the cache status for an arbitrary text without modifying the assistant.
    """
    check_account_permission(user, account_id, "assistants.view", db)
    assistant = db.query(Assistant).filter(
        Assistant.id == assistant_id,
        Assistant.account_id == account_id,
    ).first()
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")

    if (assistant.tts_provider or "").lower() != "deepgram":
        return {"cached": False, "cached_at": None, "supported": False}

    from botelier.voice.greeting_cache import get_cache_status
    effective_text = greeting_text or assistant.first_message or "Hello! How can I help you today?"
    _voice = assistant.tts_voice or "aura-2-helena-en"
    tts_cfg = {
        "model": assistant.tts_model or _voice,
        "voice": _voice,
    }
    status = get_cache_status(effective_text, tts_cfg, assistant_id=assistant_id)
    return {
        "cached": status["cached"],
        "cached_at": status["cached_at"].isoformat() if status["cached_at"] else None,
        "text_matches_cache": status["text_matches_cache"],
        "outdated": status["outdated"],
        "supported": True,
    }


@router.post("/{assistant_id}/cache-greeting")
async def cache_assistant_greeting(
    assistant_id: str,
    account_id: str = Query(..., description="Account ID for multi-tenant isolation"),
    greeting_text: Optional[str] = Query(None, description="Override greeting text; defaults to assistant.first_message"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Generate and cache the greeting audio for this assistant.

    An optional ``greeting_text`` query parameter allows callers such as the flow
    editor to pre-generate the cache for a specific text (e.g. the Initial Node
    greeting) that may differ from ``assistant.first_message``.
    """
    check_account_permission(user, account_id, "assistants.edit", db)
    assistant = db.query(Assistant).filter(
        Assistant.id == assistant_id,
        Assistant.account_id == account_id,
    ).first()
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")

    if (assistant.tts_provider or "").lower() != "deepgram":
        raise HTTPException(
            status_code=400,
            detail="Greeting cache is only supported for the Deepgram TTS provider",
        )

    import os
    api_key = os.environ.get("DEEPGRAM_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="DEEPGRAM_API_KEY not configured")

    from botelier.voice.greeting_cache import get_or_generate_greeting_audio, get_cache_status
    effective_text = greeting_text or assistant.first_message or "Hello! How can I help you today?"
    _voice = assistant.tts_voice or "aura-2-helena-en"
    tts_cfg = {
        "model": assistant.tts_model or _voice,
        "voice": _voice,
    }

    try:
        await get_or_generate_greeting_audio(
            effective_text, tts_cfg, api_key, assistant_id=assistant_id
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Deepgram TTS error: {exc}")

    status = get_cache_status(effective_text, tts_cfg, assistant_id=assistant_id)
    return {
        "cached": status["cached"],
        "cached_at": status["cached_at"].isoformat() if status["cached_at"] else None,
        "text_matches_cache": status["text_matches_cache"],
        "outdated": status["outdated"],
    }