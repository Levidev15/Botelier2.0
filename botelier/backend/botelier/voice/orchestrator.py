"""
Botelier Agent Orchestrator

Manages multiple voice agent sessions and handles routing.
"""

from typing import Dict, Optional
from .session import VoiceSession
from .agent import VoiceAgent


class AgentOrchestrator:
    """
    Orchestrates multiple voice agents across hotels
    
    This manages the lifecycle of agent sessions and routes
    incoming calls to the appropriate agent.
    """
    
    def __init__(self):
        self.active_sessions: Dict[str, VoiceSession] = {}
        self.agents: Dict[str, VoiceAgent] = {}
    
    def register_agent(self, agent: VoiceAgent) -> None:
        """Register a voice agent"""
        self.agents[agent.config.agent_id] = agent
    
    def unregister_agent(self, agent_id: str) -> None:
        """Unregister a voice agent"""
        if agent_id in self.agents:
            del self.agents[agent_id]
    
    def get_agent(self, agent_id: str) -> Optional[VoiceAgent]:
        """Get agent by ID"""
        return self.agents.get(agent_id)
    
    def create_session(
        self,
        agent_id: str,
        session_id: str,
        metadata: Optional[Dict] = None
    ) -> VoiceSession:
        """Create a new voice session for an agent"""
        agent = self.agents.get(agent_id)
        if not agent:
            raise ValueError(f"Agent not found: {agent_id}")
        
        session = VoiceSession(
            session_id=session_id,
            agent=agent,
            metadata=metadata or {}
        )
        
        self.active_sessions[session_id] = session
        return session
    
    def end_session(self, session_id: str) -> None:
        """End a voice session"""
        if session_id in self.active_sessions:
            session = self.active_sessions[session_id]
            session.end()
            del self.active_sessions[session_id]
    
    def get_session(self, session_id: str) -> Optional[VoiceSession]:
        """Get active session by ID"""
        return self.active_sessions.get(session_id)
    
    def get_active_session_count(self) -> int:
        """Get count of active sessions"""
        return len(self.active_sessions)
    
    def get_sessions_for_agent(self, agent_id: str) -> list[VoiceSession]:
        """Get all active sessions for a specific agent"""
        return [
            session for session in self.active_sessions.values()
            if session.agent.config.agent_id == agent_id
        ]
