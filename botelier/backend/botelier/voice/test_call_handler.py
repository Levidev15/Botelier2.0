"""
Test Call Handler - Browser-based voice testing via WebSocket.

Provides instant assistant testing from the dashboard without requiring phone numbers.
Uses FastAPIWebsocketTransport for direct browser audio streaming.
"""

import os
import asyncio
from typing import Optional
from fastapi import WebSocket
from sqlalchemy.orm import Session
from loguru import logger

from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport, FastAPIWebsocketParams
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.pipeline.runner import PipelineRunner

from .engine import VoiceEngineFactory
from .agent import VoiceAgentConfig
from .function_mapper import FunctionMapper
from .raw_audio_serializer import RawAudioFrameSerializer
from ..models.assistant import Assistant


class TestCallHandler:
    """
    Handles browser-based test calls for assistants.
    
    Similar to CallHandler but for WebSocket audio from browser instead of Twilio.
    Allows hotels to test assistants instantly without phone numbers.
    """
    
    def __init__(self):
        """Initialize test call handler."""
        self.active_sessions = {}
    
    async def handle_test_call(
        self,
        websocket: WebSocket,
        assistant_id: str,
        db: Session
    ):
        """
        Handle test call from browser.
        
        Args:
            websocket: FastAPI WebSocket from browser (already accepted)
            assistant_id: Assistant to test
            db: Database session
        
        Flow:
            1. Load assistant config from database
            2. Create FastAPIWebsocketTransport for browser audio
            3. Build Pipecat pipeline (same as Twilio but without phone serializer)
            4. Stream audio: Browser mic → STT → LLM → TTS → Browser speakers
        """
        session_id = None
        try:
            logger.info(f"🧪 Test call started for assistant: {assistant_id}")
            
            # Load assistant configuration from database
            try:
                assistant = db.query(Assistant).filter(
                    Assistant.id == assistant_id
                ).first()
                
                if not assistant:
                    logger.error(f"❌ Assistant not found: {assistant_id}")
                    db.close()
                    await websocket.close(code=1008, reason="Assistant not found")
                    return
                
                logger.info(f"🤖 Testing assistant: '{assistant.name}'")
                
                # Convert to VoiceAgentConfig
                config = self._create_agent_config(assistant)
                
                # Fetch tools for function calling
                tools = []
                if config.enable_function_calling:
                    from ..models.tool import Tool
                    tools = db.query(Tool).filter(
                        Tool.hotel_id == assistant.hotel_id,
                        Tool.is_active == "true"
                    ).all()
                
                session_id = f"test_{assistant_id}_{asyncio.current_task().get_name()}"
                
            finally:
                # Close database session immediately
                db.close()
            
            # Create transport for browser audio with raw PCM serializer
            transport = FastAPIWebsocketTransport(
                websocket=websocket,
                params=FastAPIWebsocketParams(
                    audio_in_enabled=True,
                    audio_out_enabled=True,
                    add_wav_header=False,
                    serializer=RawAudioFrameSerializer(sample_rate=16000)
                )
            )
            
            # Prepare API keys
            api_keys = {
                'deepgram': config.stt_api_key or os.getenv('DEEPGRAM_API_KEY'),
                'openai': config.llm_api_key or os.getenv('OPENAI_API_KEY'),
                'anthropic': config.llm_api_key or os.getenv('ANTHROPIC_API_KEY'),
                'cartesia': config.tts_api_key or os.getenv('CARTESIA_API_KEY'),
                'elevenlabs': config.tts_api_key or os.getenv('ELEVENLABS_API_KEY'),
            }
            
            # Create Pipecat pipeline
            pipeline, task, llm, context = VoiceEngineFactory.create_pipeline(
                config=config,
                api_keys=api_keys,
                transport=transport,
                tools=tools,
                call_sid=None  # No Twilio call SID for test calls
            )
            
            # Send greeting
            if config.greeting_message:
                await task.queue_frames([TTSSpeakFrame(config.greeting_message)])
            
            # Run the pipeline
            self.active_sessions[session_id] = task
            
            async with PipelineRunner() as runner:
                logger.info(f"🎙️ Test call session started: {session_id}")
                await runner.run(task)
            
            logger.info(f"✅ Test call ended: {session_id}")
            
        except Exception as e:
            logger.error(f"❌ Test call error: {str(e)}")
            logger.exception(e)
            if websocket.client_state.value == 1:  # CONNECTED
                await websocket.close(code=1011, reason="Internal error")
        
        finally:
            if session_id and session_id in self.active_sessions:
                del self.active_sessions[session_id]
    
    def _create_agent_config(self, assistant: Assistant) -> VoiceAgentConfig:
        """Convert database Assistant model to VoiceAgentConfig."""
        import json
        
        return VoiceAgentConfig(
            stt_provider=assistant.stt_provider,
            stt_model=assistant.stt_model,
            stt_language=assistant.stt_language,
            stt_api_key=assistant.stt_api_key,
            
            llm_provider=assistant.llm_provider,
            llm_model=assistant.llm_model,
            llm_api_key=assistant.llm_api_key,
            llm_temperature=assistant.llm_temperature,
            llm_max_tokens=assistant.llm_max_tokens,
            
            tts_provider=assistant.tts_provider,
            tts_voice=assistant.tts_voice,
            tts_model=assistant.tts_model,
            tts_language=assistant.tts_language,
            tts_api_key=assistant.tts_api_key,
            tts_speed=assistant.tts_speed,
            
            system_prompt=assistant.system_prompt,
            greeting_message=assistant.greeting_message,
            
            enable_function_calling=assistant.enable_function_calling,
            context_messages=json.loads(assistant.context_messages) if assistant.context_messages else [],
        )
    
    async def end_test_call(self, session_id: str):
        """End an active test call session."""
        if session_id in self.active_sessions:
            task = self.active_sessions[session_id]
            await task.cancel()
            del self.active_sessions[session_id]
            logger.info(f"🛑 Test call ended: {session_id}")
