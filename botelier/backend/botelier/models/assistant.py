"""
Assistant Model - Represents a voice AI assistant for a hotel.

Each assistant has:
- Voice configuration (STT, LLM, TTS providers)
- System prompt and personality
- Assigned phone numbers
- Function calling tools
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Boolean, ForeignKey, Float, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from botelier.database import Base


class Assistant(Base):
    """
    Assistant model representing a voice AI agent.
    
    Each assistant is:
    - Owned by a hotel
    - Has voice provider configuration
    - Can be assigned to phone numbers
    - Has tools/functions for actions
    """
    __tablename__ = "assistants"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Ownership
    hotel_id = Column(UUID(as_uuid=True), ForeignKey("hotels.id"), nullable=False)
    
    # Basic info
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Voice configuration
    stt_provider = Column(String(50), nullable=False, default="deepgram")  # Speech-to-text
    llm_provider = Column(String(50), nullable=False, default="openai")    # Language model
    tts_provider = Column(String(50), nullable=False, default="cartesia")  # Text-to-speech
    
    # Model selections
    stt_model = Column(String(100), nullable=True)
    llm_model = Column(String(100), nullable=False, default="gpt-4o-mini")
    tts_model = Column(String(100), nullable=True)
    tts_voice = Column(String(100), nullable=True)
    
    # Behavior
    system_prompt = Column(Text, nullable=False, default="You are a helpful hotel assistant.")
    first_message = Column(Text, nullable=True)
    language = Column(String(10), nullable=False, default="en")
    
    # Settings
    temperature = Column(Float, nullable=True, default=0.7)
    max_tokens = Column(Integer, nullable=True)
    
    # Provider-specific configurations (stored as JSONB for flexibility)
    # These map directly to Pipecat's InputParams classes
    stt_config = Column(JSONB, nullable=True, default=dict)  # Deepgram LiveOptions, Flux InputParams, etc.
    llm_config = Column(JSONB, nullable=True, default=dict)  # OpenAI frequency_penalty, Anthropic prompt_caching, etc.
    tts_config = Column(JSONB, nullable=True, default=dict)  # TTS-specific settings
    
    # Status
    is_active = Column(Boolean, default=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<Assistant {self.name}>"
    
    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "hotel_id": str(self.hotel_id),
            "name": self.name,
            "description": self.description,
            "stt_provider": self.stt_provider,
            "llm_provider": self.llm_provider,
            "tts_provider": self.tts_provider,
            "stt_model": self.stt_model,
            "llm_model": self.llm_model,
            "tts_model": self.tts_model,
            "tts_voice": self.tts_voice,
            "system_prompt": self.system_prompt,
            "first_message": self.first_message,
            "language": self.language,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stt_config": self.stt_config or {},
            "llm_config": self.llm_config or {},
            "tts_config": self.tts_config or {},
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "updated_at": self.updated_at.isoformat() + "Z" if self.updated_at else None,
        }
