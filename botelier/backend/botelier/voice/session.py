"""
Botelier Voice Session

Represents an active conversation session between a caller and an agent.
"""

from datetime import datetime
from typing import Dict, Any, Optional, List
from enum import Enum
from .agent import VoiceAgent


class SessionStatus(str, Enum):
    """Voice session status"""
    INITIALIZING = "initializing"
    ACTIVE = "active"
    ENDED = "ended"
    ERROR = "error"


class VoiceSession:
    """
    Active voice conversation session
    
    Tracks a single conversation between a caller and a voice agent.
    """
    
    def __init__(
        self,
        session_id: str,
        agent: VoiceAgent,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.session_id = session_id
        self.agent = agent
        self.status = SessionStatus.INITIALIZING
        self.metadata = metadata or {}
        
        self.started_at = datetime.utcnow()
        self.ended_at: Optional[datetime] = None
        
        self.messages: List[Dict[str, Any]] = []
        self.events: List[Dict[str, Any]] = []
        
        self._record_event("session_created", {
            "agent_id": agent.config.agent_id,
            "hotel_id": agent.config.hotel_id,
        })
    
    def start(self) -> None:
        """Mark session as active"""
        self.status = SessionStatus.ACTIVE
        self._record_event("session_started", {})
    
    def end(self) -> None:
        """End the session"""
        self.status = SessionStatus.ENDED
        self.ended_at = datetime.utcnow()
        self._record_event("session_ended", {
            "duration_seconds": self.get_duration()
        })
    
    def record_message(
        self,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Record a message in the conversation"""
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": metadata or {}
        }
        self.messages.append(message)
    
    def _record_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Record a session event"""
        event = {
            "type": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "data": data
        }
        self.events.append(event)
    
    def get_duration(self) -> Optional[int]:
        """Get session duration in seconds"""
        if not self.started_at:
            return None
        
        end_time = self.ended_at or datetime.utcnow()
        return int((end_time - self.started_at).total_seconds())
    
    def get_summary(self) -> Dict[str, Any]:
        """Get session summary"""
        return {
            "session_id": self.session_id,
            "agent_id": self.agent.config.agent_id,
            "hotel_id": self.agent.config.hotel_id,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_seconds": self.get_duration(),
            "message_count": len(self.messages),
            "event_count": len(self.events),
        }
