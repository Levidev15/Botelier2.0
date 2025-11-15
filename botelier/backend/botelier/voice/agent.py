"""
Botelier Voice Agent

High-level interface for creating and managing voice AI agents.
Hotels interact with this clean API instead of framework internals.
"""

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from enum import Enum


class AgentStatus(str, Enum):
    """Voice agent status"""
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class VoiceAgentConfig(BaseModel):
    """Configuration for a Botelier voice agent"""
    
    agent_id: str
    hotel_id: str
    name: str
    description: Optional[str] = None
    status: AgentStatus = AgentStatus.DRAFT
    
    stt_provider: str = "deepgram"
    stt_model: Optional[str] = None
    stt_language: str = "en"
    stt_config: Dict[str, Any] = Field(default_factory=dict)
    
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.7
    llm_max_tokens: int = 150
    llm_config: Dict[str, Any] = Field(default_factory=dict)
    
    tts_provider: str = "cartesia"
    tts_voice_id: str = "71a7ad14-091c-4e8e-a314-022ece01c121"
    tts_model: Optional[str] = None
    tts_speed: float = 1.0
    tts_config: Dict[str, Any] = Field(default_factory=dict)
    
    system_prompt: str = "You are a friendly hotel concierge assistant."
    greeting_message: str = "Hello! How can I help you today?"
    
    enable_function_calling: bool = False
    functions: List[Dict[str, Any]] = Field(default_factory=list)
    
    enable_interruptions: bool = True
    enable_vad: bool = True
    
    metadata: Dict[str, Any] = Field(default_factory=dict)


class VoiceAgent:
    """
    Botelier Voice Agent
    
    Represents a configured voice AI agent for a hotel.
    This is the main interface hotels use to create conversational AI.
    """
    
    def __init__(self, config: VoiceAgentConfig):
        self.config = config
        self._pipeline = None
        self._transport = None
        
    def to_dict(self) -> Dict[str, Any]:
        """Export agent configuration as dictionary"""
        return self.config.model_dump()
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VoiceAgent":
        """Create agent from dictionary configuration"""
        config = VoiceAgentConfig(**data)
        return cls(config)
    
    def update_config(self, **kwargs) -> None:
        """Update agent configuration"""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
    
    def validate(self) -> List[str]:
        """
        Validate agent configuration
        
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        if not self.config.name:
            errors.append("Agent name is required")
        
        if not self.config.system_prompt:
            errors.append("System prompt is required")
        
        if self.config.llm_temperature < 0 or self.config.llm_temperature > 2:
            errors.append("LLM temperature must be between 0 and 2")
        
        if self.config.tts_speed < 0.5 or self.config.tts_speed > 2.0:
            errors.append("TTS speed must be between 0.5 and 2.0")
        
        return errors
    
    def get_summary(self) -> Dict[str, Any]:
        """Get agent summary for display"""
        return {
            "id": self.config.agent_id,
            "name": self.config.name,
            "status": self.config.status,
            "stt": self.config.stt_provider,
            "llm": f"{self.config.llm_provider}/{self.config.llm_model}",
            "tts": self.config.tts_provider,
            "language": self.config.stt_language,
        }
